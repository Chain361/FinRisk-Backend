# RAG บนเอกสารเต็ม (ปร.4/5/6) ด้วย Pinecone — แผน implement

> สถานะ: **งาน 1–6, 8 implement แล้ว / เหลืองาน 4.5 (calibrate) กับงาน 7 (env บน Vercel)** — ดู §0.1
> ถ้าโค้ดจริงต่างจากนี้ให้ยึดโค้ดแล้วแก้เอกสารตาม
> อัปเดตล่าสุด: เปลี่ยน embedding model เป็น **`multilingual-e5-large` (1024 dim)** — ปิดความเสี่ยงภาษาไทยที่เคยเป็นข้อ #1 ของร่างก่อน
> อ่านคู่กัน: `docs/chatbot_architecture.md` (orchestration ปัจจุบัน), `docs/legal_linkage_plan.md` §5 (ชั้นเอกสาร), `CLAUDE.md`
>
> ⚠️ `docs/chatbot_architecture.md` หัวข้อ "ทำไมไม่ใช้ RAG" จะขัดกับเอกสารนี้ทันทีที่ implement เสร็จ — แก้เป็น "ขอบเขตที่ใช้ / ไม่ใช้ RAG" ใน PR เดียวกัน

---

## 0. ข้อตัดสินใจที่ล็อกแล้ว

| # | ข้อตัดสินใจ | ผลต่อแผน |
| :--- | :--- | :--- |
| 1 | **เก็บ content เต็มไว้ใน Pinecone ได้** — demo ใช้ข้อมูล mock, production จริงจะใช้ infra ในประเทศ | post-verify ไม่ต้องพึ่ง `document_chunks` (§5) — และข้อนี้**ถูกบังคับโดยข้อ 3 อยู่แล้ว** |
| 2 | **reseed ทุก deploy ต่อไปก่อน** — อนาคตค่อยลอง Airflow แยก branch | ต้องรัน ingest ใหม่หลัง deploy (§7.1) และมีผลข้างเคียงที่ไม่เกี่ยวกับ RAG (§7.2 ⚠️) |
| 3 | **Pinecone พร้อมแล้ว**: index `pr-documents`, model **`multilingual-e5-large`, 1024 dim**, cosine, field map `text`, us-east-1 | เป็น **integrated-inference index** → ไม่ต้องเรียก embedding API เอง โค้ดสั้นลงมาก (§6.2) โมเดลฐาน XLM-RoBERTa ครอบคลุมภาษาไทย จึงไม่มีความเสี่ยงเรื่องภาษาแล้ว แต่มีลิมิต **507 token/record** ที่กำหนดขนาด chunk (§6.3) |

---

## 0.1 สถานะ implement + สิ่งที่ต่างจากแผน

| งาน (§10) | สถานะ | ไฟล์ |
| :--- | :--- | :--- |
| 1 `image_typhoon.py` + OCR 3 ไฟล์ | ✅ | `ocr_pipeline/extractors/image_typhoon.py` (+ `extractor_for_path()` ใน `extractors/__init__.py`) |
| 2 `ingest_documents.py --dry-run` | ✅ | `scripts/ingest_documents.py` |
| 3 ingest จริง | ✅ | ผลรัน: 3 เอกสาร / 13 chunk / token สูงสุด 331 |
| 4 `retrieval.py` + endpoint search | ✅ | `src/services/retrieval.py` + `GET /projects/{id}/documents/search` (`src/routers/documents.py`) |
| 4.5 calibrate `RAG_MIN_SCORE` | ⬜ **เหลืองานนี้** — เครื่องมือทำไว้แล้ว ต้องรันเองในเครื่องที่ต่อ Pinecone ได้ (ค่าใน config ยังเป็น 0.82 ที่เดาไว้) | `scripts/calibrate_rag.py` |
| 5 tool ตัวที่ 6 + system prompt | ✅ | `src/services/chatbot.py` (`SEARCH_DOC_DECLARATION`, `_tools()`, กติกาข้อ 6–7, `citations`) |
| 6 เทสต์ §9 | ✅ 10 เทสต์ (`pytest -q` → 63 passed, 8 skipped) | `tests/test_retrieval.py` |
| 7 env บน Vercel | ⬜ ติด blocker เดิม (ยังไม่ provision managed Postgres) | |
| 8 อัปเดตเอกสาร | ✅ | ไฟล์นี้ + `CLAUDE.md` + `README.md` + `_schema_dictionary.md` + `chatbot_architecture.md` |

**6 จุดที่เพิ่มจากแผนตอน implement งาน 4–6**

| # | เพิ่มอะไร | ทำไม |
| :--- | :--- | :--- |
| 1 | `src/config.py::load_dotenv()` — ทุกทางเข้าโหลด `.env` เองตอน import config (shell/Vercel env ชนะ `.env` เสมอ) | เดิมมีแต่ `scripts/ingest_documents.py` กับ `run_pipeline.py` ที่โหลด `.env` เอง → `uvicorn src.main:app` มองไม่เห็น `PINECONE_API_KEY` แล้ว RAG จะ**ปิดเงียบ**ทั้งที่คีย์อยู่ในไฟล์ตรงหน้า (feature flag ที่ปิดตัวเองเพราะอ่านไฟล์ไม่เจอ คือ failure mode ที่หาสาเหตุนาน) ตอนนี้ตัวโหลดอยู่ที่เดียว ingest ก็ใช้ตัวเดียวกัน |
| 2 | `_normalize_hit()` รองรับ hit ทั้งแบบ dict (SDK 7/8) และ msgspec Struct (SDK 9) | SDK ที่ติดตั้งจริงคือ **9.1.0** ซึ่ง `h["_id"]`/`h["_score"]` ตามที่ §6.2 เขียนไว้ **ใช้ไม่ได้แล้ว** (เป็น `.id`/`.score`) — `requirements.txt` เปลี่ยน pin เป็น `pinecone>=9,<10` ให้ตรงกับของจริง |
| 3 | `_index()` cache client ทั้ง process | `Pinecone().Index(name)` ยิง describe หา host ทุกครั้งที่สร้าง = เพิ่ม round trip ฟรีๆ ต่อคำถามที่ใช้ RAG |
| 4 | จับ exception ของ Pinecone แปลงเป็น `ServiceError` | Pinecone ล่ม/เน็ตมีปัญหาต้องได้ 503 พร้อมข้อความไทย ไม่ใช่ 500 stack trace (chatbot ได้ `{"error": ...}` แล้วตอบผู้ใช้ตามกติกาข้อ 4 ของ system prompt) |
| 5 | พารามิเตอร์ `min_score` (service + endpoint) | จำเป็นต่องาน #4.5 — ถ้ากรองที่ `RAG_MIN_SCORE` เสมอ จะไม่มีวันเห็นคะแนนของ hit ที่ถูกตัดทิ้ง = calibrate ไม่ได้ `min_score=0` จึงคืนคะแนนดิบทุก hit |
| 6 | เทสต์เกินตาราง §9 อีก 5 ตัว | hit ที่ไม่มีแถวใน Postgres แล้ว (record ค้างจาก ingest รอบก่อน — §0.1 "ยังไม่ปิด"), `min_score` กรองถูกต้อง, tool ถูกประกาศเมื่อมีคีย์, `citations` ใน response ของ `/chatbot`, และ `ServiceError` ตอนปิด flag |

**3 จุดที่ของจริงต่างจากแผน (ชั้น ingest)**

| # | แผนเขียนไว้ | ของจริง | เหตุผล |
| :--- | :--- | :--- | :--- |
| 1 | ตัดตาม "บล็อกตารางใน markdown ที่ Typhoon คืนมา" (§6.3) | **Typhoon คืนตารางเป็น HTML** (`<table><tr><td>`) ไม่ใช่ตาราง markdown แบบ `\|` — chunker จึงต้องรู้จัก `<table>` ตัดที่ขอบ `</tr>` และมี `--table-format markdown\|html` (default `markdown` = แปลงเป็นตาราง `\|` ก่อน chunk) | ร่างแรกมองไม่เห็นตาราง เลยตัดกลาง `<td>` ได้ chunk ที่มีตัวเลขแต่ไม่มีหัวคอลัมน์ — failure mode ที่ §6.3 เตือนไว้เอง แท็ก `</td><td>` ยังกิน token ทิ้งเปล่า 3–4 token/ช่อง |
| 2 | บล็อกยาวเกิน **~700 อักษร** ค่อยตัดย่อย | `--max-chars` default **600** | 700 อักษรของตาราง BOQ ไทย ≈ 480 token = ชนเพดานพอดี ไม่เหลือ headroom ให้หัวตารางที่ทำซ้ำทุก chunk |
| 3 | `document_chunks` = สำเนา chunk จาก ingest (§4.3) | `seed_legal_layer` **เขียนตารางนี้อยู่ก่อนแล้ว** (ใส่ `summary_text` เป็น chunk_no=1 ของทุกเอกสาร `status='present'`) → ingest **ลบ chunk ของ doc_id นั้นทิ้งแล้วเขียนทับ** | แผนไม่รู้ว่า seed แตะตารางนี้ ถ้าไม่ลบก่อนจะได้ chunk_no ซ้ำ (ตารางไม่มี UNIQUE constraint) สรุปที่คนเขียนยังอยู่ครบที่ `project_documents.summary_text` และ retrieval ไม่ได้อ่านตารางนี้อยู่แล้ว |

**ของแถมที่ไม่ได้อยู่ในแผน:** cache OCR ที่ `ocr_pipeline/work/<run-id>/ocr/<project>-<doctype>/page_NN.md`
(รันซ้ำไม่เสียโควตา Typhoon — `--force-ocr` เพื่อ OCR ใหม่), `manifest.json` บันทึก sha256/extractor/พารามิเตอร์ chunk,
และ `_load_dotenv()` ในสคริปต์ (ตรรกะเดียวกับ `run_pipeline.py` เพราะ `src/config.py` อ่าน env ตอน import)

**ยังไม่ปิด:** ถ้า ingest รอบใหม่ได้ chunk **น้อยลงกว่ารอบก่อน** record เบอร์ท้ายๆ ของรอบเก่าจะค้างบน Pinecone
(เช่นเคยมี 6 เหลือ 4 → `:5`, `:6` ยังอยู่) ตอนนี้ยังไม่มีขั้นตอนลบส่วนเกิน — เอกสารชุด demo คงที่จึงยังไม่กระทบ

---

## 1. ปัญหาที่แก้ + ขอบเขต

**คำถามที่ระบบปัจจุบันตอบไม่ได้:** "เอกสารเต็มของ ปร.5 ระบุว่าอะไรบ้าง"

`project_documents.summary_text` เก็บสรุป 2–3 บรรทัดที่มนุษย์เขียนไว้ล่วงหน้า และ `extracted_json` เก็บเฉพาะ field ที่ risk engine ใช้ (`ราคากลาง`, `factor_f`, `base_cost`) — คำถามที่ต้องอ่าน "บรรทัดที่ 7 ของตาราง BOQ" หรือ "หมายเหตุท้ายเอกสาร" ตอบไม่ได้ เพราะข้อมูลไม่เคยเข้าระบบ

**สิ่งที่ RAG เพิ่ม:** ค้นข้อความเต็มแบบ semantic แล้วให้ chatbot อ้างอิงคำตอบจาก chunk จริงพร้อมเลขหน้า

**สิ่งที่ RAG *ไม่* แทน:** tool เดิม 5 ตัวยังเป็นทางหลัก — risk score, legal refs, เอกสารขาด/ไม่ขาด ต้องเดินผ่าน structured query เหมือนเดิม RAG ใช้เฉพาะเมื่อคำตอบอยู่ใน "เนื้อความ" ที่ไม่ถูก normalize ลงคอลัมน์ใด

**ขอบเขตรอบนี้:** MOCK-CON-001 เอกสาร ปร.4/5/6 จาก `raw_documents/*.png` (3 ไฟล์)

---

## 2. หลักการออกแบบ

1. **Postgres คือ authority ของ "สิทธิ์"** — `projects.subdistrict_id` เป็นคำตอบสุดท้ายว่าใครเห็นอะไรได้ ไม่ว่า Pinecone จะคืนอะไรมา
2. **Pinecone คือ authority ของ "ข้อความ"** (เปลี่ยนจากร่างแรก ตามข้อตัดสินใจ #1) — `upsert_records()` ของ integrated index เก็บ text field เป็น metadata ให้อัตโนมัติและ **ปิดไม่ได้** จึงไม่มีเหตุผลจะบังคับอ่านข้อความจาก Postgres อีก
3. **scope guard เป็น deterministic** — เช็คสิทธิ์ใน Python + SQL ไม่ขึ้นกับว่า LLM หรือ Pinecone จะทำตัวดีหรือไม่
4. **ทุก key ต้อง stable ข้าม reseed** — เพราะข้อตัดสินใจ #2 ทำให้ `doc_id`/`chunk_id` เปลี่ยนทุก deploy (§4.2)
5. **feature flag ได้** — `PINECONE_API_KEY` ว่าง = tool ตัวที่ 6 ไม่ถูกประกาศให้ Gemini เลย ระบบเดิมทำงานครบ
6. **ingest ไม่เขียน `project_documents` เลย** — `seed_database.py` เป็นผู้เขียนตารางนั้นเพียงผู้เดียวเหมือนเดิม (§4.4)

---

## 3. Data flow

### 3.1 Ingest (offline รันมือ ไม่อยู่ใน request path)

```
raw_documents/MOCK-CON-001-PR5.png
   └─ ImageTyphoonExtractor.extract()        [ocr_pipeline/extractors/image_typhoon.py — ใหม่]
        └─ markdown (cache ลง ocr_pipeline/work/<run_id>/ocr/ ตาม audit-trail convention เดิม)
             └─ chunk_document()              [scripts/ingest_documents.py — ใหม่]
                  ├─ index.upsert_records(...)          ← Pinecone embed ให้เอง (ไม่เรียก embedding API)
                  └─ INSERT document_chunks (สำเนา local — ไม่ใช่ทางที่ retrieval ใช้ ดู §4.3)
```

### 3.2 Query (ใน request ของ `POST /chatbot`)

```
ผู้ใช้: "เอกสารเต็มของ ปร.5 ระบุอะไรบ้าง"
  └─ Gemini เลือกเรียก search_document_text(query=..., project_id="MOCK-CON-001")
       └─ retrieval.search_document_text(conn, user, ...)
            ├─ [1] scope_subdistrict_ids(conn, user)     ← จาก JWT เท่านั้น ไม่ใช่ args ของ LLM
            ├─ [2] index.search(query={inputs:{text}}, filter={subdistrict_id:{$in:[...]}})  ← ชั้นกรอง 1
            ├─ [3] SELECT ... FROM project_documents JOIN projects WHERE (project_id, doc_type_code) IN (...)
            │                                             ← ชั้นกรอง 2 (บังคับ) + ดึง doc_no มาทำ citation
            └─ [4] คืน text + doc_type_code + doc_no + page_no → Gemini → reply + citations
```

**ไม่มีการเรียก embedding API ในทั้งสองเส้น** — Pinecone integrated inference จัดการให้ทั้ง ingest และ query

---

## 4. Data model

### 4.1 ไม่มี DDL ใหม่

`document_chunks` มีอยู่แล้วใน `seed_database.py` และพอใช้เป็นสำเนา local:

```sql
CREATE TABLE document_chunks (
    chunk_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    doc_id    INTEGER NOT NULL REFERENCES project_documents(doc_id),
    chunk_no  INTEGER NOT NULL, page_no INTEGER,
    content_text TEXT NOT NULL,
    embedding BYTEA          -- ยังคง NULL: เวกเตอร์อยู่ที่ Pinecone และสร้างโดย Pinecone
);
```

### 4.2 ⚠️ Record ID ต้อง stable ข้าม reseed

ข้อตัดสินใจ #2 (reseed ทุก deploy) ทำให้ `--force` drop ทุกตารางแล้วสร้างใหม่ → `doc_id`/`chunk_id` ที่เป็น `GENERATED ALWAYS AS IDENTITY` **ได้ค่าใหม่หมดทุก deploy**

ถ้า record ID ใน Pinecone ผูกกับ `chunk_id` ผลคือหลัง deploy ครั้งถัดไป Pinecone คืน ID ที่ join กลับ Postgres ไม่เจอ → post-verify กรองทิ้งหมด → **RAG คืนผลว่างโดยไม่มี error ใดๆ** ผู้ใช้เห็นแค่ "ไม่พบข้อมูลในเอกสาร" ซึ่งดูเหมือนคำตอบปกติ

**ข้อบังคับ:** ID มาจาก natural key ที่มาจาก CSV จึงเหมือนเดิมทุก reseed

```python
def chunk_key(project_id: str, doc_type_code: str, chunk_no: int) -> str:
    return f"{project_id}:{doc_type_code}:{chunk_no}"     # "MOCK-CON-001:PR5:3"
```

ผลพลอยได้: ingest ซ้ำเป็น idempotent upsert — รันกี่ครั้งก็ไม่เกิด record ค้างหรือซ้ำ ซึ่งจำเป็นมากเมื่อต้องรัน ingest ใหม่ทุก deploy

### 4.3 Record ที่ upsert ขึ้น Pinecone

```python
index.upsert_records(namespace="pr-documents", records=[{
    "_id": "MOCK-CON-001:PR5:3",
    "text": "…เนื้อหา chunk เต็ม…",   # ← ชื่อ field ต้องตรงกับ field map ที่ตั้งไว้ ('text')
    "project_id": "MOCK-CON-001",
    "subdistrict_id": 3,               # int — ใช้กับ $in filter
    "doc_type_code": "PR5",
    "chunk_no": 3,
    "page_no": 1,
}])
```

`text` คือ field ที่ Pinecone เอาไป embed ตาม field map และมันจะ **ถูกเก็บเป็น metadata กลับมาด้วยเสมอ ปิดไม่ได้** — ซึ่งตรงกับข้อตัดสินใจ #1 พอดี ไม่ต้องออกแบบอะไรเพิ่ม

**`document_chunks` ยังเขียนอยู่ไหม — เขียน แต่ retrieval ไม่พึ่ง**

เขียนไว้เพราะราคาถูกและได้ประโยชน์ 2 อย่าง: debug/diff เทียบกับสิ่งที่อยู่บน Pinecone ได้ และเป็นจุดตั้งต้นถ้าย้ายไป pgvector (§12) แต่ **retrieval ต้องไม่ SELECT ข้อความจากตารางนี้** เพราะ reseed ทุก deploy จะทำให้มันว่างจนกว่าจะรัน ingest ใหม่ — ถ้า retrieval พึ่งมัน RAG จะพังทุก deploy

### 4.4 การแบ่งความเป็นเจ้าของข้อมูล — `mock_documents/` กับ `raw_documents/` แยกกัน

สองโฟลเดอร์นี้ป้อนข้อมูลคนละชั้น ไม่ทับกัน:

| แหล่ง | เจ้าของอะไร | ทางเข้าระบบ |
| :--- | :--- | :--- |
| `mock_documents/*.csv` | **แถว** ใน `project_documents`, `document_types`, `document_findings`, `finding_legal_map` | `seed_database.py::seed_legal_layer` (บรรทัด 935 — **ที่เดียวในทั้ง repo ที่เขียน `project_documents`**) |
| `raw_documents/*.png` | **ข้อความเต็ม** ของเอกสาร | `scripts/ingest_documents.py` → Pinecone (+ สำเนา `document_chunks`) |

จุดที่เคยทับกันคือคอลัมน์ `file_path` และ `source` ซึ่งร่างก่อนหน้าให้ ingest ไป `UPDATE` — **ยกเลิกแนวทางนั้น** ด้วยเหตุผล 2 ข้อ:

1. `--force` reseed ทุก deploy (ข้อตัดสินใจ #2) เขียน `file_path=NULL` กลับทุกครั้ง → ต้องรัน ingest ใหม่แค่เพื่อเติมคอลัมน์ ทั้งที่ Pinecone ไม่ได้หายไปไหน
2. `source='ocr'` **ระบุ provenance ผิด** — แถวนั้น `status`/`summary_text`/`extracted_json` ยังเป็นของที่คนเขียนมือทั้งหมด มีเพียง chunk ที่มาจาก OCR การตั้งทั้งแถวเป็น `'ocr'` เท่ากับอ้างว่า `extracted_json` (ที่ risk engine ใช้) มาจาก OCR ซึ่งไม่จริง และจะขัดกับ `document_findings` ของโครงการเดียวกันที่ยังเป็น `source='mock'`

**แนวทางที่ใช้แทน:** ใส่ `file_path` ลงใน CSV ตั้งแต่ต้น (ทำแล้ว) — `seed_legal_layer` อ่าน `r["file_path"].strip() or None` อยู่แล้ว จึงไม่ต้องแก้โค้ด seed เลย

```csv
MOCK-CON-001,PR4,present,ปร.4-เดโม-001,2025-01-15,"…","{…}",raw_documents/MOCK-CON-001-PR4.png,mock
```

`source` คงเป็น `'mock'` เพราะตรงกับความจริงของแถว — เปลี่ยนเป็น `'ocr'` วันที่ต่อ OCR เข้าชั้นเอกสารจริงทั้งแถว (พร้อม review gate ตาม §11)

ผลที่ได้: **ไม่มี split ownership**, reseed ไม่ทำให้อะไร drift, และความเสี่ยง "ingest เขียนทับ `status` → risk score เปลี่ยนเงียบๆ" หายไปทั้งข้อ เพราะไม่มีโค้ดใดที่ UPDATE ตารางนี้อีกแล้ว — ไม่ต้องพึ่งวินัยของคนเขียนโค้ด

### 4.5 Namespace

ใช้ namespace เดียว `pr-documents` + metadata filter — free tier ให้ index เดียว และ query ยิงได้ทีละ namespace ถ้าแบ่ง namespace ตามตำบล role ที่เห็นทุกตำบล (`admin`/`regional_supervisor`) ต้อง fan-out หลาย query โดยไม่ได้ความปลอดภัยเพิ่ม เพราะการกันข้อมูลรั่วอยู่ที่ post-verify ใน Postgres อยู่แล้ว

---

## 5. Scope guard — สองชั้น

tool เดิมทั้ง 5 ตัวเรียก `load_project_in_scope()` ซึ่งบังคับสิทธิ์ใน Python เสมอ แต่ Pinecone อยู่นอก transaction — ต้องสร้างการรับประกันขึ้นมาเอง

```python
def search_document_text(conn, user, query, project_id=None, top_k=None):
    allowed = scope_subdistrict_ids(conn, user)          # จาก JWT — LLM ส่งมาเองไม่ได้

    if project_id:
        load_project_in_scope(conn, project_id, user)    # 403/404 ก่อนยิง Pinecone (ประหยัดด้วย)

    flt = {}
    if allowed is not None:
        flt["subdistrict_id"] = {"$in": [int(s) for s in allowed]}    # ── ชั้น 1: pre-filter
    if project_id:
        flt["project_id"] = project_id

    hits = _vector_search(query, top_k=top_k or RAG_TOP_K, flt=flt)
    if not hits:
        return {"chunks": [], "note": "ไม่พบเนื้อหาที่เกี่ยวข้องในเอกสารที่คุณมีสิทธิ์เข้าถึง"}

    # ── ชั้น 2: post-verify — ถาม Postgres ว่า "ตอนนี้" เอกสารพวกนี้เป็นของตำบลไหน
    meta = _verify_and_enrich(conn, {(h["project_id"], h["doc_type_code"]) for h in hits})
    out = []
    for h in hits:
        m = meta.get((h["project_id"], h["doc_type_code"]))
        if m is None:                                     # ไม่มีในระบบแล้ว → ทิ้ง
            continue
        if allowed is not None and m["subdistrict_id"] not in allowed:
            log.warning("post-verify กรอง hit นอก scope: %s (user=%s)", h["_id"], user["username"])
            continue
        out.append({**h, "doc_no": m["doc_no"], "score": h["score"]})
    return {"chunks": [c for c in out if c["score"] >= RAG_MIN_SCORE]}
```

query ของชั้น 2 ใช้ natural key ล้วน จึงรอด reseed:

```sql
SELECT pd.project_id, pd.doc_type_code, pd.doc_no, p.subdistrict_id
FROM project_documents pd
JOIN projects p ON p.project_id = pd.project_id
WHERE (pd.project_id, pd.doc_type_code) IN %s
```

**ทำไมต้องมีชั้น 2 ทั้งที่ชั้น 1 กรองแล้ว**

ชั้น 1 เชื่อ metadata ที่ **สำเนาไว้ตอน ingest** ถ้าโครงการย้ายตำบล, ingest ไม่สมบูรณ์, หรือ upsert ผิด key metadata จะไม่ตรงกับความจริงใน Postgres → ข้อมูลข้ามตำบลรั่ว **แบบไม่มี error ให้เห็น** ผู้ใช้ระบบนี้คือหน่วยตรวจสอบราชการ ความเสียหายของการที่เจ้าหน้าที่ตำบลหนึ่งอ่านเอกสารตำบลอื่นได้ ไม่ใช่แค่บั๊ก

ความเสี่ยงนี้ **สูงขึ้น** ภายใต้ข้อตัดสินใจ #2 เพราะ reseed ทุก deploy = มีหน้าต่างเวลาที่ Postgres กับ Pinecone ไม่ตรงกันทุกครั้งที่ deploy จนกว่าจะ ingest เสร็จ

ต้นทุนของชั้น 2 คือ 1 query ที่ join ด้วย primary key และได้ `doc_no` สำหรับ citation มาในคำสั่งเดียวกันอยู่แล้ว

---

## 6. จุดแก้โค้ด รายไฟล์

### 6.1 `src/config.py` — เพิ่มท้ายไฟล์

```python
# Pinecone integrated-inference index — ค้นเนื้อหาเอกสารเต็ม (ดู docs/rag_pinecone_plan.md)
# ⚠️ PINECONE_API_KEY ว่าง = tool ค้นเอกสารไม่ถูกประกาศให้ Gemini (chatbot ทำงานปกติด้วย tool เดิม 5 ตัว)
PINECONE_API_KEY   = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX     = os.getenv("PINECONE_INDEX", "pr-documents")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "pr-documents")
PINECONE_TEXT_FIELD = os.getenv("PINECONE_TEXT_FIELD", "text")   # ต้องตรงกับ field map ตอนสร้าง index

RAG_TOP_K     = int(os.getenv("RAG_TOP_K", "6"))
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.82"))  # cosine — ดูหมายเหตุเรื่อง score ของ e5 ด้านล่าง

RAG_MAX_CHUNK_TOKENS = int(os.getenv("RAG_MAX_CHUNK_TOKENS", "480"))  # ลิมิตจริงของโมเดลคือ 507 (§6.3)
```

**ไม่มี `EMBED_MODEL` / `EMBED_DIM`** — โมเดลและ dimension ถูกล็อกไว้ที่ index (`multilingual-e5-large`, 1024) ตั้งแต่ตอนสร้างแล้ว เปลี่ยนภายหลังต้องสร้าง index ใหม่ ไม่ใช่แก้ env

**⚠️ `RAG_MIN_SCORE` = 0.55 ใช้กับ e5 ไม่ได้** — e5 ถูกเทรนแบบ contrastive ทำให้ cosine similarity ถูกบีบอยู่ในช่วงแคบและสูง คู่ข้อความที่**ไม่เกี่ยวกันเลย**ก็มักได้ 0.70–0.78 ตั้ง threshold ที่ 0.55 จึงเท่ากับไม่กรองอะไรเลย และจะปล่อย chunk มั่วเข้าไปให้ Gemini ตอบ ค่า 0.82 เป็นจุดตั้งต้นที่สมเหตุสมผล แต่ **ต้อง calibrate กับ chunk จริง — งาน #4.5 ของ §10** โดยยิงคำถามที่รู้คำตอบแล้วดูช่วงคะแนนของ hit ที่ถูกกับที่ผิด

เพิ่ม warning log ใน `src/main.py` ข้าง `GEMINI_API_KEY` ที่มีอยู่:

```python
if not PINECONE_API_KEY:
    log.warning("PINECONE_API_KEY ยังไม่ได้ตั้งค่า — chatbot จะไม่มี tool ค้นเนื้อหาเอกสารเต็ม")
```

### 6.2 `src/services/retrieval.py` — ไฟล์ใหม่

integrated index ทำให้ไฟล์นี้สั้นกว่าร่างแรกมาก — **ไม่มี `_embed()` ไม่มี normalize เวกเตอร์ ไม่มีเรื่อง `task_type`** ทั้งหมดเป็นหน้าที่ของ Pinecone

```python
def _vector_search(query: str, top_k: int, flt: dict) -> list[dict]:
    """แยกออกมาเพื่อ monkeypatch ในเทสต์ (ไม่ยิง Pinecone จริงใน pytest)
    — pattern เดียวกับ chatbot._call_gemini"""
    from pinecone import Pinecone
    index = Pinecone(api_key=PINECONE_API_KEY).Index(PINECONE_INDEX)
    r = index.search(
        namespace=PINECONE_NAMESPACE,
        query={"inputs": {"text": query}, "top_k": top_k, "filter": flt or None},
        fields=[PINECONE_TEXT_FIELD, "project_id", "doc_type_code", "chunk_no", "page_no"],
    )
    return [
        {"_id": h["_id"], "score": h["_score"], "text": h["fields"][PINECONE_TEXT_FIELD],
         "project_id": h["fields"]["project_id"], "doc_type_code": h["fields"]["doc_type_code"],
         "chunk_no": h["fields"]["chunk_no"], "page_no": h["fields"].get("page_no")}
        for h in r["result"]["hits"]
    ]
```

`_vector_search` เป็นฟังก์ชันเดียวที่ผูกกับ Pinecone — การย้ายไป pgvector ภายหลังแตะแค่นี้ (§12)

**e5 ต้องการ prefix `query:` / `passage:` แต่ที่นี่ไม่ต้องเติมเอง** — โมเดลตระกูล e5 เทรนโดยแยก prompt ของ query กับ passage ถ้าใช้ผิดฝั่งคุณภาพจะตก แต่ integrated index จัดการให้แล้ว: `upsert_records()` = `passage`, `index.search()` = `query` **ห้ามเติม `"query: "` ลงในสตริงเองเด็ดขาด** เพราะจะกลายเป็น prefix ซ้อน สองชั้น
⚠️ ถ้าวันหนึ่งย้ายไปเรียก `pc.inference.embed()` ตรงๆ หรือย้ายไป pgvector (§12) **ต้องเติม prefix เองทั้งสองฝั่ง** — จุดนี้อยู่ใน `_vector_search` + ingest เท่านั้น

### 6.3 `scripts/ingest_documents.py` — ไฟล์ใหม่ (offline CLI)

```bash
python -m scripts.ingest_documents --project MOCK-CON-001
python -m scripts.ingest_documents --project MOCK-CON-001 --dry-run   # ดู chunk โดยไม่แตะ Pinecone
```

**ingest เป็น read-only ต่อ `project_documents`** — อ่านว่าเอกสารใบไหนคู่กับไฟล์ไหน แล้วเขียนออกไปที่ Pinecone กับ `document_chunks` เท่านั้น (§4.4)

```sql
-- หาไฟล์ที่ต้อง OCR จาก DB ไม่ใช่จากการ scan โฟลเดอร์
SELECT doc_id, project_id, doc_type_code, file_path
FROM project_documents
WHERE project_id = ? AND status = 'present' AND file_path IS NOT NULL
```

ขั้นตอนต่อ 1 เอกสาร:

1. อ่าน `file_path` จาก DB (มาจาก `mock_documents/project_documents.csv` — CSV เป็นแหล่งเดียวที่บอกว่าไฟล์ไหนคู่กับเอกสารใบใด)
2. OCR ผ่าน `ImageTyphoonExtractor` → markdown + cache ลง `ocr_pipeline/work/<run_id>/ocr/`
3. chunk → `index.upsert_records()` พร้อม `_id = chunk_key(...)`
4. เขียนสำเนาลง `document_chunks` (ลบ chunk เดิมของ `doc_id` นั้นก่อน แล้ว insert ใหม่ ใน transaction เดียว)

**ไม่มีขั้นตอนที่เขียน `project_documents`** — `status`, `extracted_json`, `source`, `file_path` เป็นของ seed ทั้งหมด เหตุผลอยู่ที่ §4.4 ผลคือ risk factor L1 (`ทุก required doc_type มีแถว explicit → computable`) และ L3 (`computable เมื่อมีเอกสาร status='present' ≥ 1`) ที่อ่านคอลัมน์ `status` โดยตรง **ไม่มีทางถูกกระทบจาก ingest ไม่ว่าเขียนโค้ดพลาดแค่ไหน**

ถ้า `file_path` ใน DB ชี้ไปไฟล์ที่ไม่มีอยู่จริง ให้ ingest fail ดังๆ พร้อมบอก path — อย่า skip เงียบ เพราะจะกลายเป็น "RAG ไม่มีข้อมูลใบนั้น" ที่หาสาเหตุยาก

**กลยุทธ์ chunk สำหรับ ปร.4/5/6**

เอกสารกลุ่มนี้เป็นตารางเกือบทั้งฉบับ (BOQ, สรุปค่าก่อสร้าง) — chunk แบบตัดทุก N ตัวอักษรจะฉีกแถวตารางขาดกลางคัน ทำให้ค้น "งานฐานราก ราคาต่อหน่วยเท่าไร" แล้วได้ chunk ที่มีตัวเลขแต่ไม่มีหัวคอลัมน์ = ตอบผิดแบบดูน่าเชื่อ

**⚠️ เพดานแข็งจากโมเดล: 507 token/record** `multilingual-e5-large` truncate ส่วนที่เกิน **โดยไม่ error** และ tokenizer ของ XLM-RoBERTa กินภาษาไทยเปลืองกว่าอังกฤษมาก — ประมาณ **1 token ต่อ 1.5–2 อักษรไทย** ตัวเลข/หน่วยในตาราง BOQ ยิ่งเปลืองกว่านั้น ดังนั้น **~1,200 อักษรไทยของร่างก่อนหน้า ≈ 600–800 token = เกินลิมิต** ท้าย chunk จะหายเงียบๆ ซึ่งคือส่วนที่มักเป็นยอดรวมของตาราง

- ตัดตามหัวข้อ/บล็อกตารางใน markdown ที่ Typhoon คืนมาก่อน
- บล็อกที่ยาวเกิน **~700 อักษร** ค่อยตัดย่อย โดย **ทำซ้ำแถวหัวตารางไว้ต้นทุก chunk ย่อย** (หัวตารางกินโควตา token ของทุก chunk ย่อย — เผื่อไว้ด้วย)
- overlap ~100 อักษร
- เก็บ `page_no` ทุก chunk (จำเป็นสำหรับ citation)

**นับ token จริงก่อน upsert อย่าเดาจากจำนวนอักษร** — `--dry-run` ต้องพิมพ์จำนวน token ต่อ chunk และ **fail ถ้ามี chunk ไหนเกิน `RAG_MAX_CHUNK_TOKENS` (480)** ไม่ใช่แค่เตือน เพราะการ truncate เป็น failure mode ที่เงียบสนิทและตรวจจากผลลัพธ์ไม่ได้ นับด้วย tokenizer ตัวเดียวกับโมเดล:

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-large")   # dev-only dependency
n = len(tok.encode(chunk_text))
```

ถ้าไม่อยากลง `transformers` ในเครื่อง ใช้ `pc.inference.embed(model="multilingual-e5-large", inputs=[chunk])` แล้วอ่าน `usage.total_tokens` แทนได้ (เสียค่า token เล็กน้อย แต่ตรงกับที่ index ใช้จริง 100%)

3 ไฟล์นี้น่าจะได้ราว 10–25 chunk รวม (มากกว่าร่างก่อนเพราะ chunk เล็กลง) — ยังเล็กมากเทียบกับ free tier 2GB

### 6.4 `ocr_pipeline/extractors/image_typhoon.py` — ไฟล์ใหม่ (เล็ก)

`TyphoonExtractor` ปัจจุบันใช้ `PdfReader(pdf_path).pages` นับหน้า → **โยน exception ทันทีกับไฟล์ PNG** แต่ `typhoon_ocr.ocr_document` รับ image อยู่แล้ว (พารามิเตอร์ชื่อ `pdf_or_image_path`) เขียน subclass สั้นๆ จบ:

```python
class ImageTyphoonExtractor(TyphoonExtractor):
    name = "typhoon-image"

    def extract(self, path: str) -> list[PageMarkdown]:
        from typhoon_ocr import ocr_document
        md = ocr_document(pdf_or_image_path=path, task_type=self.task_type,
                          page_num=1, model=self.model)
        return [PageMarkdown(page=1, markdown=md)]
```

เมื่อเอกสารจริงเป็น PDF หลายหน้า กลับไปใช้ `TyphoonExtractor` เดิมได้เลย — interface `extract() → list[PageMarkdown]` เหมือนกัน `ingest_documents.py` เลือก extractor ตามนามสกุลไฟล์

**⚠️ ห้ามส่งเอกสาร ปร. เข้า `ocr_pipeline/run.py`** — pipeline นั้นทั้งเส้น (`parse → normalize → validate → emit`) ออกแบบสำหรับ **งบการเงิน** ปลายทางเป็น `out.csv` คอลัมน์ `รายการบัญชี`/`มูลค่า` ที่ match กับ `reference/` ของผังบัญชี เอกสาร ปร. ไม่มีโครงนั้นและจะตกลง review queue ทั้งหมด — ใช้ซ้ำเฉพาะชั้น `extractors/`

### 6.5 `src/services/chatbot.py` — tool ตัวที่ 6

```python
types.FunctionDeclaration(
    name="search_document_text",
    description=(
        "ค้นหาข้อความจากเนื้อหาเอกสารเต็มของโครงการ (ปร.4/ปร.5/ปร.6) — ใช้เมื่อผู้ใช้ถามถึง"
        "รายละเอียดที่อยู่ในตัวเอกสาร เช่น 'ปร.5 ระบุอะไรบ้าง' 'ในเอกสารเขียนว่าอย่างไร' "
        "อย่าใช้เครื่องมือนี้ถามเรื่องสถานะเอกสารขาด/ไม่ขาด หรือ risk score (ใช้ get_project_documents "
        "และ get_project แทน ซึ่งแม่นยำกว่าเพราะอ่านจากข้อมูลที่ตรวจสอบแล้ว)"
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "ข้อความค้นหาเป็นภาษาไทย"},
            "project_id": {"type": "string", "description": "จำกัดเฉพาะโครงการนี้ (แนะนำให้ระบุเสมอถ้ารู้)"},
        },
        "required": ["query"],
    },
)
```

`description` ที่บอก **ว่าเมื่อไรไม่ควรใช้** สำคัญพอๆ กับบอกว่าเมื่อไรควรใช้ — ไม่งั้น Gemini จะเริ่มใช้ RAG ตอบคำถามที่ structured query ตอบแม่นกว่า ซึ่งเป็นการถอยหลังจากจุดแข็งเดิมของระบบ

**ประกาศแบบมีเงื่อนไข** (ให้ flag ปิดได้จริง):

```python
def _tools() -> list[types.Tool]:
    decls = list(TOOL_DECLARATIONS)
    if PINECONE_API_KEY:
        decls.append(SEARCH_DOC_DECLARATION)
    return [types.Tool(function_declarations=decls)]
```

เพิ่มใน `TOOL_DISPATCH` + กติกาข้อ 6–7 ใน `SYSTEM_PROMPT`:

```
6. ผลจาก search_document_text คือ "ข้อความที่คัดมาจากเอกสารจริง" — ตอบโดยอ้างอิงเฉพาะข้อความใน chunk
   ที่ได้รับเท่านั้น ห้ามเติมเนื้อหาที่ไม่ได้อยู่ใน chunk และทุกครั้งที่อ้างเนื้อหาเอกสาร
   ต้องระบุว่ามาจากเอกสารใด เลขที่เท่าไร หน้าใด (doc_type_code, doc_no, page_no ที่เครื่องมือคืนมา)
7. ถ้า search_document_text คืนผลว่าง ให้ตอบว่าไม่พบข้อความที่เกี่ยวข้องในเอกสารที่มีในระบบ
   ห้ามใช้ summary_text หรือความรู้ทั่วไปมาตอบแทน
```

### 6.6 `src/routers/documents.py` — endpoint ใหม่ (แนะนำให้ทำ)

```python
@project_router.get("/{project_id}/documents/search")
```

ไม่จำเป็นสำหรับ demo (chatbot เรียก service ตรง) แต่ทำให้ทดสอบด้วย curl ได้โดยไม่ผ่าน Gemini — **จำเป็นสำหรับการ calibrate `RAG_MIN_SCORE` (งาน #4.5 ของ §10)** เพราะเห็นคะแนนดิบของทุก hit และแยกปัญหา "ค้นไม่เจอ" ออกจาก "LLM ตอบไม่ดี" ได้ ให้ endpoint คืน `score` ติดมาด้วยเสมอ

### 6.7 `requirements.txt`

```
pinecone[grpc]==7.*    # integrated-inference index สำหรับค้นเนื้อหาเอกสาร (src/services/retrieval.py)
```

ตรวจว่า SDK รุ่นที่ติดตั้งมี `upsert_records`/`search` ในตัวหรือต้องลง `pinecone-plugin-records` เพิ่ม (SDK รุ่นเก่าต้องลงแยก)
`typhoon-ocr` + `pypdf` อยู่ฝั่ง `ocr_pipeline/requirements.txt` และ **ไม่ต้องติดตั้งบน Vercel** เพราะ ingest รัน offline

`transformers` (สำหรับนับ token ตอน `--dry-run` ตาม §6.3) เป็น **dev/ingest dependency เท่านั้น** — ใส่ที่ `ocr_pipeline/requirements.txt` ไม่ใช่ที่นี่ API ตอน runtime ไม่ต้องนับ token เพราะ query ของผู้ใช้สั้นกว่าลิมิตมาก และไม่ควรลาก dependency ขนาดนั้นขึ้น Vercel

---

## 7. Deploy

### 7.1 ลำดับหลัง deploy (ภายใต้ข้อตัดสินใจ #2)

reseed ทุก deploy ทำให้ `document_chunks` ว่างทุกครั้ง — แต่ **RAG ยังทำงานได้** เพราะข้อความอยู่ใน Pinecone และ post-verify ใช้ `projects`/`project_documents` ซึ่งถูก reseed จาก CSV ด้วยค่าเดิมทุกครั้ง (§4.2, §5)

runbook หลัง deploy:

```bash
# 1. deploy → Vercel รัน seed_database.py --force เอง
#    (project_documents ถูกสร้างกลับมาครบพร้อม file_path จาก CSV — ดู §4.4)
# 2. เติมสำเนา local + sync Pinecone (idempotent upsert — รันซ้ำได้)
DATABASE_URL=<managed-postgres> python -m scripts.ingest_documents --project MOCK-CON-001
# 3. smoke test
curl -H "Authorization: Bearer <auditor3-token>" \
     "$API/projects/MOCK-CON-001/documents/search?q=Factor%20F"
```

ข้อ 2 ข้ามได้ถ้าไม่รีบ — **RAG ยังตอบได้ตามปกติจาก Pinecone** เพราะทั้งข้อความและ metadata ที่ post-verify ต้องใช้ (`project_documents`, `projects`) กลับมาครบจาก CSV แล้ว สิ่งเดียวที่ว่างคือสำเนา `document_chunks` ซึ่ง retrieval ไม่ได้ใช้ (§4.3)

### 7.2 ⚠️ ผลข้างเคียงของ reseed ที่ไม่เกี่ยวกับ RAG แต่กระทบ demo

`seed_database.py --force` drop **ทุก** ตาราง รวมถึงตารางที่ผู้ใช้สร้างผ่านแอป:

| ตาราง | ข้อมูลที่หาย |
| :--- | :--- |
| `auditor_feedback` | ความเห็นผู้ตรวจสอบทั้งหมด (รวม draft) |
| `assignments` + `assignment_status_history` | งานที่มอบหมาย + ประวัติสถานะ |
| `audit_reports` | รายงานผลตรวจ |
| `access_log` | accountability trail ที่ middleware บันทึกไว้ |

ถ้า demo มีฉาก "ผู้ตรวจสอบบันทึกความเห็น → หัวหน้าเห็น" แล้วมี deploy คั่นกลาง **ข้อมูลที่เพิ่งกรอกจะหายไปกลางการนำเสนอ** สำหรับ demo ยอมรับได้ถ้ารู้ตัว — แค่อย่า deploy ระหว่างสาธิต และเขียนไว้ในสคริปต์ demo

เรื่องนี้ไม่เกี่ยวกับ RAG และมีอยู่ก่อนแล้ว แต่จะกลายเป็นบล็อกเกอร์จริงตอนขึ้น production — เป็นเหตุผลที่ Airflow (หรืออะไรก็ตามที่แยก "seed schema" ออกจาก "load data") มีคุณค่ามากกว่าแค่ความสวยงามของ orchestration

### 7.3 Env vars บน Vercel

| ตัวแปร | หมายเหตุ |
| :--- | :--- |
| `DATABASE_URL` | managed Postgres (Neon/Supabase) — **ยังไม่ provision** ตาม `CLAUDE.md` §สิ่งที่ยังไม่ทำ |
| `JWT_SECRET` | ค่าสุ่มยาว — ยังเป็น default อยู่ |
| `GEMINI_API_KEY` | chatbot (ไม่ได้ใช้ทำ embedding แล้ว) |
| `PINECONE_API_KEY` | ใหม่ |
| `PINECONE_INDEX` | `pr-documents` |
| `PINECONE_NAMESPACE` | `pr-documents` |

`TYPHOON_OCR_API_KEY` **ไม่ต้อง**ตั้งบน Vercel (ingest รัน offline)

### 7.4 Index — สร้างแล้ว

`pr-documents` · **`multilingual-e5-large`** · **1024 dim** · cosine · field map `text` · us-east-1 · aws serverless
**max input 507 token/record** (เกินกว่านั้นถูก truncate — ดู §6.3)

```python
pc.create_index_for_model(
    name="pr-documents", cloud="aws", region="us-east-1",
    embed={"model": "multilingual-e5-large", "field_map": {"text": "text"}},
)
```

Free tier ปี 2026: 1 index, 2GB, single region, ไม่มี RBAC — พอสำหรับ demo อย่างมาก (เอกสาร 3 ใบใช้ไม่ถึง 1MB) ข้อจำกัด "ไม่มี RBAC" ไม่กระทบเพราะสิทธิ์ผู้ใช้บังคับที่ Postgres ทั้งหมด

**ข้อจำกัดที่ต้องรู้: free tier มี index เดียว และโมเดล/dimension ล็อกตั้งแต่ตอนสร้าง** → เปลี่ยนโมเดลอีกครั้ง = ลบ `pr-documents` ทิ้งแล้วสร้างใหม่ + ingest ใหม่ทั้งหมด (การเปลี่ยนมาเป็น e5 รอบนี้ก็ผ่านขั้นตอนนี้แล้ว) ค่า env ไม่ต้องแก้ตราบใดที่ยังใช้ชื่อ index เดิม

---

## 8. ผลกระทบฝั่ง frontend

**ไม่มี breaking change** — `POST /chatbot` ยังรับ `{message, history}` และคืน `{reply, tool_calls}` เหมือนเดิม

| รายการ | ระดับ | รายละเอียด |
| :--- | :--- | :--- |
| ป้ายชื่อ tool ใน chip | **แก้ 1 บรรทัด** | ถ้า frontend map ชื่อ tool → ป้ายไทยด้วย object ตายตัว ชื่อ `search_document_text` จะแสดงเป็นค่าดิบหรือ `undefined` |
| `citations` | additive | field ใหม่ ของเดิมไม่พัง — client เก่าเมินไปเฉยๆ |
| latency | ต้องเช็ค | เพิ่มราว 0.3–1.5 วิ/คำถามที่เรียก RAG (integrated inference เร็วกว่าเรียก embedding API แยก) ถ้าตั้ง timeout ตึงหรือไม่มี loading state ที่ทนรอ ต้องปรับ |
| หน้าค้นเอกสารแยก | งานใหม่ | ถ้าจะใช้ `GET /projects/{id}/documents/search` เป็น UI ของตัวเอง — ไม่ต้องทำรอบนี้ |

**เรื่อง `citations` — ควรทำ ไม่ใช่ nice-to-have**

ระบบนี้บังคับ guardrail ว่า "ห้ามอ้างมาตรากฎหมายที่ไม่มีใน `legal_refs`" เพราะผู้ใช้เป็นเจ้าหน้าที่ตรวจสอบที่ต้องเปิดเอกสารจริงไปยืนยันได้ RAG ที่ยกข้อความจากเอกสารมาตอบโดยไม่บอกว่ามาจากหน้าไหน ขัดกับหลักเดียวกันนั้น — **และยิ่งจำเป็นเมื่อ OCR ภาษาไทยอาจอ่านตัวเลขผิด** ถ้าไม่ทำ citations ก็ไม่ควรเปิด RAG

```json
{
  "reply": "ปร.5 ระบุค่างานต้นทุน 3,980,000 บาท ใช้ Factor F = 1.3061 …",
  "tool_calls": [{"name": "search_document_text", "args": {"query": "…"}}],
  "citations": [
    {"project_id": "MOCK-CON-001", "doc_type_code": "PR5",
     "doc_no": "ปร.5-เดโม-001", "page_no": 1, "chunk_no": 3}
  ]
}
```

---

## 9. เทสต์

ต่อยอด pattern เดิมใน `tests/test_chatbot.py` (monkeypatch `_call_gemini` ไม่ยิง API จริง) — เพิ่ม monkeypatch `retrieval._vector_search`

| เทสต์ | ยืนยันอะไร |
| :--- | :--- |
| `test_search_requires_pinecone_key` | `PINECONE_API_KEY` ว่าง → tool ไม่ถูกประกาศ, chatbot เดิมยังทำงาน |
| `test_search_scoped_to_own_subdistrict` | `auditor3` (โยนก) ค้นแล้วได้ chunk ของ MOCK-CON-001 |
| **`test_search_post_verify_blocks_poisoned_hit`** | **สำคัญที่สุด** — stub `_vector_search` จงใจคืน chunk ของ MOCK-CON-001 (โยนก) ให้ `auditor1` (ท่าช้าง) โดยข้าม pre-filter → ต้องถูกกรองทิ้งที่ชั้น 2 คืนผลว่าง |
| `test_search_project_id_out_of_scope_403` | `auditor1` ระบุ `project_id="MOCK-CON-001"` → `ForbiddenError` ก่อนยิง Pinecone |
| `test_search_survives_empty_document_chunks` | ลบ `document_chunks` ทั้งตาราง → RAG ยังคืนผลได้ (พิสูจน์ว่า retrieval ไม่พึ่งตารางนี้ ตาม §4.3 — กันบั๊กที่จะโผล่ทุก deploy) |

เทสต์แถวที่ 3 คือเหตุผลทั้งหมดที่ชั้น 2 มีอยู่ ถ้าเขียนแล้วไม่ผ่าน แปลว่าสถาปัตยกรรมยังผิด
เทสต์แถวที่ 5 คือเหตุผลที่ §4.3 แยก "สำเนา local" ออกจาก "แหล่งข้อความ" ให้ชัด

### ⚠️ ผู้ใช้ที่ต้องใช้ตอน demo

**MOCK-CON-001 และ MOCK-CON-002 อยู่ตำบลโยนกทั้งคู่** (`seed_database.py::MOCK_PROJECTS`)

| username | role | เห็น MOCK-CON-001 |
| :--- | :--- | :--- |
| `auditor3` / `analyst3` | project_auditor / risk_analyst (โยนก) | ✅ |
| `admin` | admin | ✅ |
| `auditor1` / `analyst1` | ท่าช้าง | ❌ (ถูกต้องตาม scope guard) |

ถ้า demo ด้วย `auditor1` **จะได้ผลว่างเสมอ** ซึ่งถูกต้องแต่ดูเหมือน RAG พัง — ใช้ `auditor3` เป็น user หลัก แล้วสลับไป `auditor1` เพื่อ**โชว์ว่า scope guard ทำงาน** เป็นอีกฉากหนึ่ง

---

## 10. ลำดับงาน

| # | งาน | ผลลัพธ์ที่ตรวจได้ |
| :--- | :--- | :--- |
| 1 | `image_typhoon.py` + OCR 3 ไฟล์ | markdown 3 ไฟล์ใน `ocr_pipeline/work/<run_id>/ocr/` อ่านออกเป็นภาษาไทย ตัวเลขตรงกับรูป |
| 2 | `ingest_documents.py` โหมด `--dry-run` | เห็น chunk ที่จะสร้าง **พร้อมจำนวน token ต่อ chunk — ไม่มีตัวไหนเกิน 480** และตารางไม่ถูกฉีกกลางแถว |
| 3 | ingest จริง | Pinecone stats ตรงกับจำนวน chunk, `document_chunks` เพิ่ม, **`project_documents` ไม่เปลี่ยนเลยแม้แต่คอลัมน์เดียว** |
| 4 | `retrieval.py` + `GET .../documents/search` | curl ค้น "Factor F" แล้วได้ chunk ของ ปร.5 |
| 4.5 | **calibrate `RAG_MIN_SCORE`** | ยิง 5–10 คำถามที่รู้คำตอบผ่าน endpoint งาน #4 บันทึกคะแนนของ hit ที่ถูกกับที่ผิด แล้วตั้ง threshold ให้แยกสองกลุ่มได้ (ค่าตั้งต้น 0.82 — ดู §6.1) |
| 5 | tool ตัวที่ 6 + system prompt | ถาม chatbot ด้วย `auditor3` ว่า "ปร.5 ระบุอะไรบ้าง" ได้คำตอบพร้อม citation |
| 6 | เทสต์ §9 | `pytest -q` ผ่านทั้งหมด |
| 7 | ตั้ง env บน Vercel + runbook §7.1 | deploy แล้วถามคำถามเดิมได้ผลเหมือน local |
| 8 | อัปเดตเอกสาร | `chatbot_architecture.md` (หัวข้อ "ทำไมไม่ใช้ RAG"), `CLAUDE.md`, `README.md`, `_schema_dictionary.md` |

งาน 1–6 ทำในเครื่องได้ทั้งหมด งาน 7 ต้องมี managed Postgres ก่อน ซึ่งเป็น blocker เดิมไม่ได้เกิดจากงานนี้

> งาน "ทดสอบภาษาไทยของโมเดล" ที่เคยเป็นงาน #0 ของร่างก่อน **ตัดออกแล้ว** — `multilingual-e5-large` (ฐาน XLM-RoBERTa, 100 ภาษา) รองรับภาษาไทยโดยตรง ไม่ต้องตัดสินใจเรื่องโมเดลก่อนลงมือ งาน #4.5 ที่มาแทนไม่ใช่ gate — ทำหลังมี chunk จริงแล้ว

---

## 11. ความเสี่ยง

> **ความเสี่ยงเรื่องภาษาไทยของโมเดล — ปิดแล้ว** ร่างก่อนหน้ายก "`llama-text-embed-v2` อาจไม่รองรับภาษาไทย" เป็นความเสี่ยงอันดับหนึ่งและตั้งเป็น gate ก่อนเริ่มงาน หลังเปลี่ยนมาใช้ `multilingual-e5-large` (ฐาน XLM-RoBERTa เทรนบน 100 ภาษารวมไทย) ข้อนี้ไม่ใช่ความเสี่ยงอีกต่อไป สิ่งที่เหลือจากการเปลี่ยนโมเดลคือ **ข้อจำกัดเชิงปฏิบัติ 2 ข้อที่ถูกออกแบบรองรับไว้ในแผนแล้ว** — ลิมิต 507 token (§6.3) และการ calibrate threshold (§6.1) ทั้งคู่อยู่ในตารางด้านล่าง

| ความเสี่ยง | ผล | การรับมือ |
| :--- | :--- | :--- |
| **chunk เกิน 507 token** | e5 truncate ท้าย chunk **เงียบๆ ไม่มี error** — ส่วนที่หายมักเป็นยอดรวมท้ายตาราง คำตอบจะขาดข้อมูลโดยไม่มีสัญญาณใดๆ | นับ token จริงใน `--dry-run` แล้ว **fail ถ้าเกิน** (§6.3) ไม่ใช่แค่เตือน |
| **`RAG_MIN_SCORE` ต่ำเกินไป** | e5 ให้คะแนนคู่ที่ไม่เกี่ยวกันราว 0.70–0.78 → threshold 0.55 = ไม่กรองเลย chunk มั่วไหลไปให้ Gemini ตอบ | ค่าตั้งต้น 0.82 + calibrate ด้วยงาน #4.5 (§6.1, §10) |
| **เติม prefix `query:`/`passage:` เอง** | prefix ซ้อนสองชั้น คุณภาพการค้นตกโดยไม่มี error | integrated index จัดการให้แล้ว — ห้ามเติมเอง (§6.2) |
| **record ID ผูกกับ `chunk_id`** | RAG คืนผลว่างเงียบๆ หลัง deploy (เกิดทุก deploy เพราะข้อตัดสินใจ #2) | natural key (§4.2) |
| **retrieval อ่านข้อความจาก `document_chunks`** | RAG พังทุก deploy จนกว่าจะ ingest ใหม่ | §4.3 + เทสต์แถวที่ 5 (§9) |
| ~~ingest เขียนทับ `project_documents.status`~~ | ~~risk score ของ demo เปลี่ยนเงียบๆ~~ | **ปิดไปแล้วโดยการออกแบบ** — ingest ไม่เขียนตารางนี้เลย (§4.4, §6.3) |
| **ลืม post-verify** | ข้อมูลข้ามตำบลรั่ว | เทสต์ poisoned hit (§9) |
| chunk ฉีกตาราง BOQ | ตอบตัวเลขโดยไม่มีหัวคอลัมน์ = ตอบผิด | ทำซ้ำ header row (§6.3) + `--dry-run` |
| Gemini เลือกใช้ RAG แทน structured tool | คำตอบแม่นยำน้อยลงกว่าเดิม | `description` บอกว่าเมื่อไร**ไม่**ควรใช้ (§6.5) |
| OCR ภาษาไทยอ่านตัวเลขผิด | คำตอบผิดแต่ดูน่าเชื่อ | citation บังคับให้เปิดเอกสารจริงตรวจได้ + ตรวจ markdown ด้วยตาในงาน #1 |
| reseed ลบข้อมูลผู้ใช้ | ความเห็น/งานที่มอบหมายหายกลาง demo | §7.2 — อย่า deploy ระหว่างสาธิต |

**เส้นแบ่งที่ห้ามข้าม:** ผลจาก RAG เป็น "ข้อมูลประกอบการอ่านของมนุษย์" เท่านั้น **ห้ามให้ค่าที่ OCR/LLM สกัดได้ไหลเข้า `extracted_json` หรือ `document_findings` โดยอัตโนมัติ** — หลักการนี้มีอยู่แล้วใน schema (`document_findings` v1 กำหนด mock เท่านั้น ต้องมี review gate ก่อนรับ source `ocr`/`llm`) งานนี้ไม่เปลี่ยนมัน

---

## 12. ทางถอย / ก้าวต่อไป

**ย้ายไป pgvector (ตอนขึ้น infra ในประเทศ)** — ข้อความเต็มอยู่ใน `document_chunks` แล้ว (นี่คือเหตุผลที่ §4.3 ยังเขียนสำเนาไว้ทั้งที่ retrieval ไม่ใช้) เปลี่ยน `embedding` เป็น **`vector(1024)`**, backfill, แล้วเขียน `_vector_search` ใหม่เป็น `ORDER BY embedding <=> ?` — **ชั้น 2 หายไปเลยเพราะกลายเป็น JOIN ในคำสั่งเดียวกัน** tool, router, system prompt, frontend ไม่ต้องแตะ

⚠️ ตอนย้ายมี 2 อย่างที่ integrated index เคยทำให้ฟรีแล้วต้องทำเอง: **เติม prefix `query: ` / `passage: ` ให้ถูกฝั่ง** (§6.2) และ **นับ/ตัด token ที่ 507 ก่อน embed** (§6.3) ถ้ารัน `multilingual-e5-large` เองผ่าน `sentence-transformers` โมเดลจะ normalize เวกเตอร์ให้อยู่แล้ว จึงใช้ `vector_cosine_ops` ได้ตรงๆ

**Airflow (branch แยก)** — pipeline ในโปรเจกต์นี้เป็น DAG จริง (`OCR → normalize → validate → emit → seed → risk engine → ingest RAG`) และมีเงื่อนไข retry/partial-failure ที่คุ้มกับการแยก task ถ้าเป้าหมายคือ**ได้เรียน Airflow** ก็ทำได้เลย แต่ถ้าเป้าหมายคือ**แก้ปัญหา §7.2** (reseed ลบข้อมูลผู้ใช้) สิ่งที่ต้องทำจริงคือ **แยก "สร้าง schema" ออกจาก "โหลดข้อมูล"** ใน `seed_database.py` แล้วเลิกใช้ `--force` บน production ซึ่งทำได้โดยไม่ต้องมี orchestrator ใดๆ — Airflow ไม่ได้แก้ปัญหานั้นให้เอง
