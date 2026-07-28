# -*- coding: utf-8 -*-
"""
ingest_documents.py — OCR เอกสารโครงการ → chunk → upsert ขึ้น Pinecone (+ สำเนาลง document_chunks)

รันมือ offline เท่านั้น ไม่อยู่ใน request path (ดู docs/rag_pinecone_plan.md §3.1, §6.3)

    python -m scripts.ingest_documents --project MOCK-CON-001 --dry-run   # ดู chunk + token ไม่แตะอะไร
    python -m scripts.ingest_documents --project MOCK-CON-001             # OCR + upsert + เขียน DB
    python -m scripts.ingest_documents --all                              # ทุกโครงการที่มี file_path

หลักการที่ห้ามพัง (แผน §4.4, §6.3):
  * **read-only ต่อ `project_documents`** — สคริปต์นี้ไม่ UPDATE ตารางนั้นแม้แต่คอลัมน์เดียว
    (`status`/`extracted_json`/`source`/`file_path` เป็นของ `seed_database.py` ผู้เดียว)
    risk factor L1/L3 ที่อ่าน `status` จึงไม่มีทางถูกกระทบจากสคริปต์นี้
  * **record id ของ Pinecone มาจาก natural key** `project_id:doc_type_code:chunk_no` ไม่ใช่ `chunk_id`
    ที่เป็น IDENTITY — เพราะ reseed ทุก deploy ทำให้ค่า IDENTITY เปลี่ยนหมด (แผน §4.2)
    ผลพลอยได้: รันซ้ำเป็น idempotent upsert
  * **ไฟล์หายให้ fail ดังๆ** ไม่ skip เงียบ (จะกลายเป็น "RAG ไม่มีข้อมูลใบนั้น" ที่หาสาเหตุยาก)
  * **chunk เกินลิมิต token ให้ fail** ไม่ใช่แค่เตือน — `multilingual-e5-large` truncate ส่วนเกิน
    โดยไม่มี error และส่วนที่หายมักเป็นยอดรวมท้ายตาราง (แผน §6.3)

⚠️ `document_chunks`: `seed_database.py::seed_legal_layer` ใส่ `summary_text` ไว้เป็น chunk_no=1
   ของทุกเอกสาร status='present' อยู่แล้ว — สคริปต์นี้ **ลบ chunk เดิมของ doc_id นั้นทิ้งแล้วเขียนทับ
   ด้วย chunk จาก OCR** (ตัดสินใจไว้ตอน implement) สรุปสั้นๆ คือ หลัง ingest ตารางนี้ = สำเนาของสิ่งที่
   อยู่บน Pinecone ล้วนๆ ส่วนสรุปที่คนเขียนยังอยู่ครบที่ `project_documents.summary_text` เหมือนเดิม
   และ retrieval ไม่ได้อ่านตารางนี้อยู่แล้ว (แผน §4.3)
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


# .env ถูกโหลดโดย src.config ตอน import (config.load_dotenv — shell env ชนะ .env เสมอ)
# คีย์ที่สคริปต์นี้ต้องใช้: TYPHOON_OCR_API_KEY (OCR), PINECONE_API_KEY (upsert + นับ token)
from src.config import (  # noqa: E402
    BASE_DIR,
    PINECONE_API_KEY,
    PINECONE_EMBED_MODEL,
    PINECONE_INDEX,
    PINECONE_NAMESPACE,
    PINECONE_TEXT_FIELD,
    RAG_MAX_CHUNK_TOKENS,
)
from src.database import db_session  # noqa: E402

WORK_DIR = os.path.join(str(BASE_DIR), "ocr_pipeline", "work")

# ขนาด chunk: เพดานแข็งคือ token ของโมเดล (นับจริงก่อน upsert) — ตัวเลขอักษรเป็นแค่เป้าตอนตัด
# 600 (ไม่ใช่ 700 ตามแผน §6.3) เพราะตาราง BOQ ไทยที่มีตัวเลข+หน่วยกิน token ราว 1 ต่อ 1.4 อักษร
# → 700 อักษรแตะ 480 token พอดี ไม่มี headroom เหลือให้หัวตารางที่ทำซ้ำทุก chunk
DEFAULT_MAX_CHARS = 600
DEFAULT_OVERLAP = 100
PINECONE_UPSERT_BATCH = 90   # upsert_records ของ integrated index รับได้ 96 record/ครั้ง

TABLE_RE = re.compile(r"^\s*\|")
SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]+\|?\s*$")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")

# Typhoon คืนตารางมาเป็น HTML (<table><tr><td>) ไม่ใช่ตาราง markdown แบบ | — ต้องรู้จักทั้งสองแบบ
HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
HTML_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
HTML_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
HTML_BR_RE = re.compile(r"<br\s*/?>", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")


# ──────────────────────────────────────────────────────────────────────────────
# chunking (ฟังก์ชันบริสุทธิ์ — ไม่แตะ DB/Pinecone เพื่อให้เทสต์/dry-run ได้ offline)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Block:
    kind: str          # "table" (markdown |) | "html_table" | "text"
    lines: list[str] = field(default_factory=list)
    heading: str = ""  # หัวข้อล่าสุดก่อนหน้าบล็อกนี้ (ใส่นำหน้าทุก chunk เพื่อไม่ให้ context หาย)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip("\n")


def _clean_cell(html: str) -> str:
    text = HTML_BR_RE.sub(" ", html)
    text = HTML_TAG_RE.sub("", text)
    return " ".join(text.split()).replace("|", "\\|")


def html_table_to_markdown(table_html: str) -> list[str]:
    """<table> → ตาราง markdown แบบ | (แถวละบรรทัด)

    ทำไมต้องแปลง: แท็ก `</td><td>` กิน token ทิ้งเปล่าราว 3–4 token ต่อช่อง ทั้งที่ไม่มีความหมาย
    ให้ค้นหา และทำให้ chunk ที่ตัดกลางตารางอ่านไม่รู้เรื่อง — ตาราง markdown ทำซ้ำหัวคอลัมน์
    ได้ถูกกว่ามาก ส่วนต้นฉบับ HTML ยังอยู่ครบใน cache ocr_pipeline/work/ (audit trail ไม่หาย)
    """
    rows = HTML_ROW_RE.findall(table_html)
    out: list[str] = []
    for i, row in enumerate(rows):
        cells = [_clean_cell(c) for c in HTML_CELL_RE.findall(row)]
        if not any(cells):
            continue
        out.append("| " + " | ".join(cells) + " |")
        if i == 0:
            out.append("| " + " | ".join("---" for _ in cells) + " |")
    return out


def split_blocks(markdown: str, table_format: str = "markdown") -> list[Block]:
    """แยกเนื้อหา 1 หน้าเป็นบล็อก: ตาราง 1 ตาราง = 1 บล็อก, ย่อหน้าคั่นด้วยบรรทัดว่าง = 1 บล็อก

    ตัดตามโครงเอกสารก่อนเสมอ — การตัดทุก N ตัวอักษรจะฉีกแถวตาราง BOQ ขาดกลางคัน
    ทำให้ได้ chunk ที่มีตัวเลขแต่ไม่มีหัวคอลัมน์ = ตอบผิดแบบดูน่าเชื่อ (แผน §6.3)

    รองรับตาราง 2 แบบ: markdown (`|`) และ HTML (`<table>` — แบบที่ Typhoon คืนมาจริง)
    `table_format='markdown'` แปลง HTML เป็น markdown ก่อน, `'html'` เก็บแท็กไว้ตามต้นฉบับ
    """
    blocks: list[Block] = []
    pos = 0
    for m in HTML_TABLE_RE.finditer(markdown):
        blocks.extend(_split_text_blocks(markdown[pos:m.start()], blocks))
        heading = next((b.heading or b.lines[0] for b in reversed(blocks)
                        if b.kind == "text" and HEADING_RE.match(b.lines[0])), "")
        if table_format == "markdown":
            lines = html_table_to_markdown(m.group(0))
            if lines:
                blocks.append(Block(kind="table", lines=lines, heading=heading))
        else:
            blocks.append(Block(kind="html_table", lines=[m.group(0)], heading=heading))
        pos = m.end()
    blocks.extend(_split_text_blocks(markdown[pos:], blocks))
    return [b for b in blocks if b.text.strip()]


def _split_text_blocks(markdown: str, prev_blocks: list[Block]) -> list[Block]:
    """ส่วนที่ไม่ใช่ตาราง HTML — แยกตามบรรทัดว่าง/หัวข้อ/ตาราง markdown (ตรรกะเดิม)"""
    blocks: list[Block] = []
    heading = next((b.lines[0] for b in reversed(prev_blocks)
                    if b.kind == "text" and HEADING_RE.match(b.lines[0])), "")
    cur: Block | None = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        is_table = bool(TABLE_RE.match(line))
        is_blank = not line.strip()

        if HEADING_RE.match(line):
            cur = None
            heading = line.strip()
            blocks.append(Block(kind="text", lines=[line], heading=""))
            continue

        if is_blank:
            cur = None
            continue

        kind = "table" if is_table else "text"
        if cur is None or cur.kind != kind:
            cur = Block(kind=kind, lines=[], heading=heading)
            blocks.append(cur)
        cur.lines.append(line)

    return blocks


def _table_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """คืน (แถวหัวตาราง, แถวข้อมูล) — หัวตารางถูกทำซ้ำไว้ต้นทุก chunk ย่อย"""
    if len(lines) >= 2 and SEPARATOR_RE.match(lines[1]):
        return lines[:2], lines[2:]
    return lines[:1], lines[1:]


def _with_heading(heading: str, body: str) -> str:
    return f"{heading}\n{body}" if heading and not body.startswith(heading) else body


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """ตัดข้อความยาวโดยพยายามตัดที่ขึ้นบรรทัด/ช่องว่างที่ใกล้เพดานที่สุด + overlap"""
    if len(text) <= max_chars:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(" "))
            if cut > max_chars * 0.5:
                end = start + cut
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c]


def chunk_block(block: Block, max_chars: int, overlap: int) -> list[str]:
    body = block.text
    full = _with_heading(block.heading, body)
    if len(full) <= max_chars:
        return [full]

    if block.kind == "html_table":
        rows = HTML_ROW_RE.findall(block.text)
        if not rows:
            return [full]
        header, body_rows = rows[0], rows[1:]
        prefix = _with_heading(block.heading, "<table>" + header)
        chunks, cur_rows = [], []
        for row in body_rows:
            if cur_rows and len(prefix) + sum(len(r) for r in cur_rows) + len(row) + 8 > max_chars:
                chunks.append(prefix + "".join(cur_rows) + "</table>")
                cur_rows = [cur_rows[-1]] if overlap else []
            cur_rows.append(row)
        if cur_rows:
            chunks.append(prefix + "".join(cur_rows) + "</table>")
        return chunks

    if block.kind == "table":
        header, rows = _table_header(block.lines)
        prefix = _with_heading(block.heading, "\n".join(header))
        chunks, cur_rows = [], []
        for row in rows:
            candidate = len(prefix) + 1 + sum(len(r) + 1 for r in cur_rows) + len(row)
            if cur_rows and candidate > max_chars:
                chunks.append(prefix + "\n" + "\n".join(cur_rows))
                cur_rows = [cur_rows[-1]] if overlap else []   # ทับแถวสุดท้าย 1 แถวกันบริบทขาด
            cur_rows.append(row)
        if cur_rows:
            chunks.append(prefix + "\n" + "\n".join(cur_rows))
        return chunks

    budget = max(max_chars - len(block.heading) - 1, 200)   # กันหัวข้อที่เติมนำหน้าดันให้เกินเพดาน
    return [_with_heading(block.heading, part) for part in _split_text(body, budget, overlap)]


def chunk_document(
    pages: list[tuple[int, str]], max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP, table_format: str = "markdown",
) -> list[dict]:
    """[(page_no, markdown)] → [{chunk_no, page_no, text}] โดย chunk_no ไล่ต่อเนื่องทั้งเอกสาร"""
    chunks: list[dict] = []
    for page_no, markdown in pages:
        for block in split_blocks(markdown, table_format):
            # บล็อกที่เป็น "หัวข้อล้วน" ไม่ต้องทำเป็น chunk เดี่ยว — มันถูกเติมนำหน้าทุก chunk
            # ของเนื้อหาที่ตามมาอยู่แล้ว ปล่อยไว้จะได้ chunk สั้นๆ ที่ไม่มีข้อมูลมาแย่งอันดับผลค้น
            if block.kind == "text" and len(block.lines) == 1 and HEADING_RE.match(block.lines[0]):
                continue
            for text in chunk_block(block, max_chars, overlap):
                text = text.strip()
                if text:
                    chunks.append({"chunk_no": len(chunks) + 1, "page_no": page_no, "text": text})
    return chunks


def chunk_key(project_id: str, doc_type_code: str, chunk_no: int) -> str:
    """id ที่ stable ข้าม reseed — ห้ามใช้ chunk_id/doc_id ที่เป็น IDENTITY (แผน §4.2)"""
    return f"{project_id}:{doc_type_code}:{chunk_no}"


# ──────────────────────────────────────────────────────────────────────────────
# token counting — ต้องนับจริง ไม่เดาจากจำนวนอักษร (ไทย ≈ 1 token ต่อ 1.5–2 อักษร)
# ──────────────────────────────────────────────────────────────────────────────
def make_token_counter(method: str):
    """คืน (fn(text) -> int, ชื่อวิธีที่ใช้จริง)"""
    if method in ("auto", "transformers"):
        try:
            from transformers import AutoTokenizer

            tok = AutoTokenizer.from_pretrained(f"intfloat/{PINECONE_EMBED_MODEL}")
            return (lambda t: len(tok.encode(t))), "transformers"
        except Exception as exc:                       # noqa: BLE001
            if method == "transformers":
                raise SystemExit(f"โหลด tokenizer ไม่สำเร็จ: {exc}\nลง `pip install transformers` ก่อน")
            print(f"[token] ใช้ transformers ไม่ได้ ({type(exc).__name__}) — ลองวิธีถัดไป")

    if method in ("auto", "pinecone"):
        if not PINECONE_API_KEY:
            if method == "pinecone":
                raise SystemExit("วิธีนับ token แบบ pinecone ต้องมี PINECONE_API_KEY")
        else:
            from pinecone import Pinecone

            pc = Pinecone(api_key=PINECONE_API_KEY)

            def _count(text: str) -> int:
                r = pc.inference.embed(
                    model=PINECONE_EMBED_MODEL, inputs=[text],
                    parameters={"input_type": "passage", "truncate": "END"},
                )
                return int(r.usage.total_tokens)

            return _count, "pinecone"

    if method in ("auto", "estimate"):
        if method == "auto":
            raise SystemExit(
                "นับ token ไม่ได้: ไม่มีทั้ง transformers และ PINECONE_API_KEY\n"
                "  pip install transformers   หรือ   ตั้ง PINECONE_API_KEY   หรือ\n"
                "  --token-counter estimate   (ประมาณคร่าวๆ — ใช้ดูคร่าวๆ เท่านั้น ห้ามใช้ตัดสินใจ upsert)"
            )
        return (lambda t: math.ceil(len(t) / 1.4)), "estimate"

    raise SystemExit(f"ไม่รู้จัก --token-counter: {method}")


# ──────────────────────────────────────────────────────────────────────────────
# OCR (+ cache ตาม audit-trail convention ของ ocr_pipeline)
# ──────────────────────────────────────────────────────────────────────────────
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ocr_pages(abs_path: str, cache_dir: str, force_ocr: bool) -> tuple[list[tuple[int, str]], dict]:
    """OCR ไฟล์เดียว → [(page_no, markdown)] พร้อม cache ลง work/<run_id>/ocr/<doc>/page_NN.md

    ถ้ามี cache อยู่แล้วจะใช้ซ้ำ (ประหยัดโควตา Typhoon และทำให้รันซ้ำได้เร็ว) — `--force-ocr` เพื่อ OCR ใหม่
    """
    os.makedirs(cache_dir, exist_ok=True)
    cached = sorted(f for f in os.listdir(cache_dir) if f.endswith(".md"))
    if cached and not force_ocr:
        pages = []
        for name in cached:
            with open(os.path.join(cache_dir, name), encoding="utf-8") as f:
                pages.append((int(re.sub(r"\D", "", name) or 1), f.read()))
        return pages, {"extractor": "cache", "version": None}

    from ocr_pipeline.extractors import extractor_for_path

    ex = extractor_for_path(abs_path)
    pages = []
    for pg in ex.extract(abs_path):
        path = os.path.join(cache_dir, f"page_{pg.page:02d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(pg.markdown)
        pages.append((pg.page, pg.markdown))
    return pages, {"extractor": ex.name, "version": ex.version}


# ──────────────────────────────────────────────────────────────────────────────
# DB / Pinecone
# ──────────────────────────────────────────────────────────────────────────────
def fetch_documents(conn, project_id: str | None) -> list[dict]:
    sql = """
        SELECT pd.doc_id, pd.project_id, pd.doc_type_code, pd.doc_no,
               pd.file_path, p.subdistrict_id
        FROM project_documents pd
        JOIN projects p ON p.project_id = pd.project_id
        WHERE pd.status = 'present' AND pd.file_path IS NOT NULL AND pd.file_path <> ''
    """
    params: list = []
    if project_id:
        sql += " AND pd.project_id = ?"
        params.append(project_id)
    sql += " ORDER BY pd.project_id, pd.doc_type_code"
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def write_document_chunks(conn, doc_id: int, chunks: list[dict]) -> None:
    """สำเนา local — retrieval ไม่ได้อ่านตารางนี้ (§4.3) มีไว้เพื่อ debug/diff และเผื่อย้าย pgvector

    ลบของเดิมของ doc_id นี้ก่อนเสมอ (รวมแถว summary_text ที่ seed ใส่ไว้) แล้ว insert ใหม่ทั้งชุด
    → รันซ้ำกี่ครั้งก็ไม่เกิดแถวซ้ำ เพราะตารางไม่มี UNIQUE (doc_id, chunk_no)
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
    cur.executemany(
        "INSERT INTO document_chunks (doc_id, chunk_no, page_no, content_text) VALUES (?,?,?,?)",
        [(doc_id, c["chunk_no"], c["page_no"], c["text"]) for c in chunks],
    )


def upsert_pinecone(records: list[dict]) -> None:
    if not PINECONE_API_KEY:
        raise SystemExit("ต้องตั้ง env PINECONE_API_KEY ก่อน (หรือใช้ --dry-run)")
    from pinecone import Pinecone

    index = Pinecone(api_key=PINECONE_API_KEY).Index(PINECONE_INDEX)
    for i in range(0, len(records), PINECONE_UPSERT_BATCH):
        batch = records[i:i + PINECONE_UPSERT_BATCH]
        index.upsert_records(namespace=PINECONE_NAMESPACE, records=batch)
        print(f"[pinecone] upsert {len(batch)} record (รวม {min(i + len(batch), len(records))}/{len(records)})")


def build_record(doc: dict, chunk: dict) -> dict:
    """ชื่อ field ข้อความต้องตรงกับ field map ของ index — Pinecone จะ embed field นี้ให้เอง

    ⚠️ ห้ามเติม prefix "passage: " เอง — integrated index เติมให้แล้ว เติมซ้ำคุณภาพจะตก (แผน §6.2)
    """
    return {
        "_id": chunk_key(doc["project_id"], doc["doc_type_code"], chunk["chunk_no"]),
        PINECONE_TEXT_FIELD: chunk["text"],
        "project_id": doc["project_id"],
        "subdistrict_id": int(doc["subdistrict_id"]),
        "doc_type_code": doc["doc_type_code"],
        "chunk_no": chunk["chunk_no"],
        "page_no": chunk["page_no"] or 1,
    }


# ──────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="OCR + chunk + upsert เอกสารโครงการขึ้น Pinecone")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", help="project_id ที่จะ ingest")
    g.add_argument("--all", action="store_true", help="ทุกโครงการที่มี file_path")
    ap.add_argument("--dry-run", action="store_true", help="แสดง chunk + token โดยไม่แตะ Pinecone/DB")
    ap.add_argument("--force-ocr", action="store_true", help="OCR ใหม่ ไม่ใช้ cache")
    ap.add_argument("--run-id", default="rag-ingest", help="โฟลเดอร์ cache ocr_pipeline/work/<run_id>/")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    ap.add_argument("--table-format", default="markdown", choices=["markdown", "html"],
                    help="Typhoon คืนตารางเป็น HTML — 'markdown' แปลงเป็นตาราง | ก่อน chunk (ค่าเริ่มต้น), "
                         "'html' เก็บแท็กไว้ตามต้นฉบับ")
    ap.add_argument("--token-counter", default="auto",
                    choices=["auto", "transformers", "pinecone", "estimate"])
    ap.add_argument("--show-chunks", action="store_true", help="พิมพ์เนื้อ chunk เต็มตอน dry-run")
    args = ap.parse_args()

    count_tokens, counter_name = make_token_counter(args.token_counter)
    print(f"[token] นับด้วยวิธี: {counter_name} (เพดาน {RAG_MAX_CHUNK_TOKENS} token/chunk)")

    run_dir = os.path.join(WORK_DIR, args.run_id)
    manifest = {"run_id": args.run_id, "purpose": "rag-ingest", "documents": [],
                "chunking": {"max_chars": args.max_chars, "overlap": args.overlap,
                             "table_format": args.table_format, "token_counter": counter_name}}

    with db_session() as conn:
        docs = fetch_documents(conn, None if args.all else args.project)
        if not docs:
            raise SystemExit("ไม่พบเอกสารที่ status='present' และมี file_path — ตรวจ mock_documents/project_documents.csv")

        all_records: list[dict] = []
        per_doc: list[tuple[dict, list[dict]]] = []
        oversize: list[str] = []

        for doc in docs:
            abs_path = os.path.join(str(BASE_DIR), doc["file_path"])
            if not os.path.isfile(abs_path):
                # fail ดังๆ — skip เงียบจะกลายเป็น "RAG ไม่มีข้อมูลใบนั้น" ที่หาสาเหตุยาก (แผน §6.3)
                raise SystemExit(
                    f"ไฟล์ไม่มีอยู่จริง: {abs_path}\n"
                    f"  (มาจาก project_documents.file_path ของ {doc['project_id']}/{doc['doc_type_code']})"
                )

            cache_dir = os.path.join(run_dir, "ocr", f"{doc['project_id']}-{doc['doc_type_code']}")
            pages, ex_info = ocr_pages(abs_path, cache_dir, args.force_ocr)
            chunks = chunk_document(pages, args.max_chars, args.overlap, args.table_format)

            print(f"\n=== {doc['project_id']} / {doc['doc_type_code']} ({doc['doc_no'] or '-'}) "
                  f"— {len(pages)} หน้า, {len(chunks)} chunk, extractor={ex_info['extractor']}")
            for c in chunks:
                c["tokens"] = count_tokens(c["text"])
                flag = "  ⚠️ เกินลิมิต" if c["tokens"] > RAG_MAX_CHUNK_TOKENS else ""
                head = c["text"].replace("\n", " ⏎ ")[:70]
                print(f"  #{c['chunk_no']:>3} หน้า {c['page_no']} | {len(c['text']):>4} อักษร | "
                      f"{c['tokens']:>4} token | {head}{flag}")
                if args.show_chunks:
                    print("  " + "-" * 70 + "\n  " + c["text"].replace("\n", "\n  ") + "\n  " + "-" * 70)
                if c["tokens"] > RAG_MAX_CHUNK_TOKENS:
                    oversize.append(chunk_key(doc["project_id"], doc["doc_type_code"], c["chunk_no"]))

            per_doc.append((doc, chunks))
            all_records.extend(build_record(doc, c) for c in chunks)
            manifest["documents"].append({
                "project_id": doc["project_id"], "doc_type_code": doc["doc_type_code"],
                "file_path": doc["file_path"], "sha256": sha256_file(abs_path),
                "extractor": ex_info, "pages": len(pages), "chunks": len(chunks),
                "max_tokens": max((c["tokens"] for c in chunks), default=0),
            })

        total = sum(len(c) for _, c in per_doc)
        print(f"\nรวม {len(per_doc)} เอกสาร / {total} chunk / "
              f"token สูงสุด {max((c['tokens'] for _, cs in per_doc for c in cs), default=0)}")

        if oversize:
            # fail ไม่ใช่แค่เตือน — e5 จะ truncate ส่วนเกินโดยไม่มี error และตรวจจากผลลัพธ์ไม่ได้
            raise SystemExit(
                f"\n❌ มี {len(oversize)} chunk เกิน {RAG_MAX_CHUNK_TOKENS} token: {', '.join(oversize)}\n"
                f"   ลด --max-chars (ตอนนี้ {args.max_chars}) แล้วรันใหม่ ห้าม upsert ทั้งที่รู้ว่าจะถูก truncate"
            )
        if counter_name == "estimate" and not args.dry_run:
            raise SystemExit("❌ --token-counter estimate ใช้ upsert จริงไม่ได้ (ตัวเลขไม่ตรงกับโมเดล)")

        if args.dry_run:
            print("\n--dry-run: ไม่ได้แตะ Pinecone และไม่ได้เขียน document_chunks")
            return 0

        upsert_pinecone(all_records)
        for doc, chunks in per_doc:
            write_document_chunks(conn, doc["doc_id"], chunks)
        conn.commit()
        print(f"[db] เขียนสำเนาลง document_chunks แล้ว {total} แถว "
              f"(project_documents ไม่ถูกแตะต้อง)")

    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[manifest] {os.path.join(run_dir, 'manifest.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
