# -*- coding: utf-8 -*-
"""
retrieval.py (service) — ค้นเนื้อหาเอกสารเต็ม (ปร.4/5/6) จาก Pinecone

ใช้ index แบบ integrated inference (`multilingual-e5-large`, 1024 dim, cosine)
→ **ไม่มีการเรียก embedding API เอง** Pinecone embed ให้ทั้งตอน ingest และตอน query
⚠️ ห้ามเติม prefix `"query: "` / `"passage: "` ลงในข้อความเอง — integrated index เติมให้แล้ว
   เติมซ้ำ = prefix ซ้อนสองชั้น คุณภาพการค้นตกโดยไม่มี error (แผน §6.2)

**scope guard สองชั้น** (แผน §5) — Pinecone อยู่นอก transaction ของ Postgres จึงเชื่อไม่ได้:
  ชั้น 1  pre-filter ที่ Pinecone ด้วย `subdistrict_id` ที่มาจาก JWT (ไม่ใช่ args ที่ LLM ส่งมา)
  ชั้น 2  post-verify กับ Postgres — ถามใหม่ว่า "ตอนนี้" เอกสารพวกนี้เป็นของตำบลไหน
          เพราะ metadata บน Pinecone เป็นสำเนา ณ ตอน ingest ถ้าโครงการย้ายตำบล/ingest ไม่สมบูรณ์
          ชั้น 1 จะปล่อยข้อมูลข้ามตำบลรั่วแบบไม่มี error ให้เห็น (ผู้ใช้ระบบนี้คือหน่วยตรวจสอบราชการ)
          ชั้น 2 ใช้ natural key ล้วน (project_id, doc_type_code) จึงรอด reseed ทุก deploy (แผน §4.2)

**ข้อความมาจาก Pinecone ไม่ใช่ `document_chunks`** — `seed_database.py --force` ล้างตารางนั้นทุก deploy
ถ้า retrieval พึ่งมัน RAG จะพังทุก deploy จนกว่าจะรัน ingest ใหม่ (แผน §4.3 + เทสต์ §9 แถวสุดท้าย)
"""
import logging

from .. import observability as obs
from ..config import (
    PINECONE_API_KEY,
    PINECONE_INDEX,
    PINECONE_NAMESPACE,
    PINECONE_TEXT_FIELD,
    RAG_MIN_SCORE,
    RAG_TOP_K,
)
from .common import ServiceError, load_project_in_scope

log = logging.getLogger("finrisk.retrieval")

# field ที่ขอคืนมาจาก Pinecone — ต้องมีครบพอทำ citation (doc_type_code + page_no + chunk_no)
SEARCH_FIELDS = [PINECONE_TEXT_FIELD, "project_id", "doc_type_code", "chunk_no", "page_no"]

EMPTY_NOTE = "ไม่พบเนื้อหาที่เกี่ยวข้องในเอกสารที่คุณมีสิทธิ์เข้าถึง"
DISABLED_MSG = "ยังไม่ได้เปิดใช้การค้นเนื้อหาเอกสาร (PINECONE_API_KEY ว่าง)"


def rag_enabled() -> bool:
    """feature flag — คีย์ว่าง = ไม่ประกาศ tool ให้ Gemini และ endpoint search ตอบ 503

    อ่านค่า global ตอนเรียก (ไม่ใช่ตอน import) เพื่อให้ monkeypatch ในเทสต์ได้ — pattern เดียวกับ
    `chatbot.GEMINI_API_KEY`
    """
    return bool(PINECONE_API_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# ชั้นที่ผูกกับ Pinecone — ฟังก์ชันเดียวในระบบ ย้ายไป pgvector ภายหลังแตะแค่ตรงนี้ (แผน §12)
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_hit(hit) -> dict:
    """hit ของ SDK → dict ธรรมดา

    pinecone SDK 9 คืน msgspec Struct (`.id` / `.score` / `.fields`) ส่วน SDK 7/8 คืน dict
    ที่ใช้คีย์ `_id`/`_score` — รองรับทั้งสองแบบเพื่อไม่ให้ SDK อัปเกรดแล้วพังเงียบ
    """
    if hasattr(hit, "fields"):          # SDK 9 (Struct)
        hit_id, score, fields = hit.id, hit.score, dict(hit.fields or {})
    else:                               # SDK 7/8 (dict)
        hit_id, score, fields = hit["_id"], hit["_score"], dict(hit.get("fields") or {})
    return {
        "_id": hit_id,
        "score": float(score),
        "text": fields.get(PINECONE_TEXT_FIELD, ""),
        "project_id": fields.get("project_id"),
        "doc_type_code": fields.get("doc_type_code"),
        "chunk_no": fields.get("chunk_no"),
        "page_no": fields.get("page_no"),
    }


def _response_hits(response) -> list:
    result = response.result if hasattr(response, "result") else response["result"]
    return list(result.hits if hasattr(result, "hits") else result["hits"])


_INDEX = None


def _index():
    """cache client ไว้ทั้ง process — `Pinecone().Index(name)` ยิง describe เพื่อหา host ทุกครั้งที่สร้าง
    สร้างใหม่ทุก request = เพิ่ม round trip ฟรีๆ ต่อคำถามที่ใช้ RAG

    (เทสต์ stub `_vector_search` ทั้งก้อนอยู่แล้ว จึงไม่เคยแตะ cache นี้)
    """
    global _INDEX
    if _INDEX is None:
        from pinecone import Pinecone

        _INDEX = Pinecone(api_key=PINECONE_API_KEY).Index(PINECONE_INDEX)
    return _INDEX


@obs.traceable(
    run_type="retriever", name="pinecone.search", process_outputs=obs.shape_retriever_outputs
)
def _vector_search(query: str, top_k: int, flt: dict | None) -> list[dict]:
    """ยิง Pinecone จริง — แยกออกมาเพื่อ monkeypatch ในเทสต์ (pattern เดียวกับ chatbot._call_gemini)"""
    response = _index().search(
        namespace=PINECONE_NAMESPACE,
        top_k=top_k,
        inputs={"text": query},          # ← Pinecone embed ให้เอง (ห้ามเติม prefix "query: ")
        filter=flt or None,
        fields=SEARCH_FIELDS,
    )
    return [_normalize_hit(h) for h in _response_hits(response)]


# ──────────────────────────────────────────────────────────────────────────────
# post-verify (ชั้น 2) — Postgres เป็น authority ของ "สิทธิ์" เสมอ
# ──────────────────────────────────────────────────────────────────────────────
@obs.traceable(
    run_type="tool",
    name="postgres.post_verify",
    process_inputs=obs.redact_verify_inputs,
    process_outputs=obs.shape_verify_outputs,
)
def _verify_and_enrich(conn, keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """(project_id, doc_type_code) → {doc_no, subdistrict_id} ตามที่ Postgres บอก ณ ตอนนี้

    เอกสารที่ไม่มีในระบบแล้วจะไม่อยู่ใน dict ที่คืน → ผู้เรียกต้องทิ้ง hit นั้น
    """
    if not keys:
        return {}
    keys = list(keys)
    placeholders = ", ".join("(?, ?)" for _ in keys)   # interpolate แค่จำนวน ? ไม่ใช่ค่า
    params: list = []
    for project_id, doc_type_code in keys:
        params.extend([project_id, doc_type_code])
    rows = conn.execute(
        f"""SELECT pd.project_id, pd.doc_type_code, pd.doc_no, p.subdistrict_id
            FROM project_documents pd
            JOIN projects p ON p.project_id = pd.project_id
            WHERE (pd.project_id, pd.doc_type_code) IN ({placeholders})""",
        tuple(params),
    ).fetchall()
    return {
        (r["project_id"], r["doc_type_code"]): {
            "doc_no": r["doc_no"],
            "subdistrict_id": r["subdistrict_id"],
        }
        for r in rows
    }


@obs.traceable(
    run_type="chain", name="search_document_text", process_inputs=obs.redact_search_inputs
)
def search_document_text(
    conn,
    user: dict,
    query: str,
    project_id: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> dict:
    """ค้นข้อความจากเอกสารเต็มภายในขอบเขตสิทธิ์ของ user

    คืน {"query", "chunks": [...], "note"?} โดย chunk มี text/score/doc_no/page_no ครบสำหรับทำ citation
    `min_score=0` = ไม่กรองคะแนน (ใช้ตอน calibrate — ดู scripts/calibrate_rag.py)

    NotFoundError/ForbiddenError โยนออกไปจาก load_project_in_scope ตามเดิม (router แปลงเป็น 404/403,
    chatbot แปลงเป็น {"error": ...})
    """
    if not rag_enabled():
        raise ServiceError(DISABLED_MSG)

    from ..auth import scope_subdistrict_ids  # เลี่ยง circular import (auth → database → services)

    allowed = scope_subdistrict_ids(conn, user)     # จาก JWT เท่านั้น — LLM ส่งมาเองไม่ได้
    if allowed is not None and not allowed:
        # user ที่ถูก scope แต่ไม่มี subdistrict_id (ข้อมูลผู้ใช้ไม่ครบ) — ไม่ควรเห็นอะไรเลย
        # และ `$in: []` เป็น filter ที่ Pinecone ไม่รับ จึงต้องตัดจบตรงนี้ ไม่ใช่ปล่อยไปให้ error
        return {"query": query, "chunks": [], "note": EMPTY_NOTE}
    if project_id:
        # 403/404 ตั้งแต่ก่อนยิง Pinecone (ถูกต้องกว่า และไม่เสีย read unit ไปเปล่าๆ)
        load_project_in_scope(conn, project_id, user)

    flt: dict = {}
    if allowed is not None:
        flt["subdistrict_id"] = {"$in": [int(s) for s in allowed]}    # ── ชั้น 1
    if project_id:
        flt["project_id"] = project_id

    threshold = RAG_MIN_SCORE if min_score is None else float(min_score)
    try:
        hits = _vector_search(query, top_k or RAG_TOP_K, flt)
    except Exception as exc:  # noqa: BLE001 — Pinecone ล่ม/เน็ตมีปัญหา ต้องไม่ทำให้ request พังเป็น 500
        log.warning("เรียก Pinecone ไม่สำเร็จ: %s: %s", type(exc).__name__, exc)
        raise ServiceError("ค้นเนื้อหาเอกสารไม่สำเร็จ กรุณาลองใหม่อีกครั้ง") from exc
    if not hits:
        return {"query": query, "chunks": [], "note": EMPTY_NOTE}

    # ── ชั้น 2: ถาม Postgres ว่าเอกสารพวกนี้เป็นของตำบลไหน "ตอนนี้" + ดึง doc_no มาทำ citation
    meta = _verify_and_enrich(
        conn, {(h["project_id"], h["doc_type_code"]) for h in hits if h["project_id"]}
    )
    chunks = []
    for h in hits:
        m = meta.get((h["project_id"], h["doc_type_code"]))
        if m is None:
            log.warning("post-verify: hit ที่ไม่มีในระบบแล้ว %s (user=%s)", h["_id"], user["username"])
            continue
        if allowed is not None and m["subdistrict_id"] not in allowed:
            log.warning("post-verify: กรอง hit นอก scope %s (user=%s)", h["_id"], user["username"])
            continue
        if h["score"] < threshold:
            continue
        chunks.append(
            {
                "chunk_id": h["_id"],
                "project_id": h["project_id"],
                "doc_type_code": h["doc_type_code"],
                "doc_no": m["doc_no"],
                "page_no": h["page_no"],
                "chunk_no": h["chunk_no"],
                "score": round(h["score"], 4),
                "text": h["text"],
            }
        )

    out = {"query": query, "chunks": chunks}
    if not chunks:
        out["note"] = EMPTY_NOTE
    return out
