# CLAUDE.md

แนวทางสำหรับ AI coding agent (และ dev) ที่ทำงานใน repo นี้ อ่านคู่กับ `README.md`

## ภาพรวม

Backend ของ **Local Budget Fraud Risk & Document Intelligence Assistant** —
ประเมินความเสี่ยงทุจริตงบประมาณของเทศบาลตำบล จากข้อมูลจัดซื้อจัดจ้าง + งบการเงิน
Stack: **Python 3.10+ / FastAPI / PostgreSQL (psycopg 3)** ไม่มี ORM

## คำสั่งที่ใช้บ่อย

ทีมใช้ **shared dev Postgres ตัวเดียวกัน** (ไม่ใช่ localhost ของแต่ละคน) เพื่อให้ข้อมูลที่แก้ผ่าน
API (เช่น เพิ่ม/ลบผู้ใช้ใน User Management) sync กันเห็นตรงกันทุกเครื่อง — ขอ connection string
จากทีมแล้วคัดลอก `.env.example` เป็น `.env` (ไม่ commit) ใส่ `DATABASE_URL=<connection string>`
**ห้าม** ใช้ตัวเดียวกับ backend production บน Vercel เพราะ deploy จะรัน `seed_database.py --force`
ลบข้อมูลทิ้งทุกครั้ง

```bash
cp .env.example .env                   # ครั้งแรกเท่านั้น แล้วใส่ DATABASE_URL ของ shared dev DB
pip install -r requirements.txt        # ติดตั้ง dependency ของ API (รวม psycopg, python-dotenv)
python seed_database.py                # ครั้งแรกเท่านั้น (คนแรกที่ตั้ง shared DB) — สร้าง schema + seed + risk engine + validate
python seed_database.py --force        # ลบตารางเดิมทั้งหมดแล้วสร้างใหม่ (ระวัง — กระทบทุกคนที่ใช้ DB เดียวกัน)
uvicorn src.main:app --reload          # รัน API dev server → /docs
pytest -q                              # smoke test

# ชั้น RAG (บังคับตั้งค่า PINECONE_API_KEY ใน .env) ต้องมี TYPHOON_OCR_API_KEY + PINECONE_API_KEY ใน .env
python -m scripts.ingest_documents --project MOCK-CON-001 --dry-run   # OCR+chunk+นับ token ไม่เขียนอะไร
python -m scripts.ingest_documents --project MOCK-CON-001             # upsert Pinecone + document_chunks
python -m scripts.calibrate_rag                                       # หาค่า RAG_MIN_SCORE จาก chunk จริง
curl -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:8000/projects/MOCK-CON-001/documents/search?q=Factor%20F&min_score=0"  # smoke test RAG

# ชั้น observability/eval (LangSmith) — ไม่บังคับ ไม่ตั้ง LANGSMITH_TRACING = ปิดสนิท ระบบทำงานปกติ
python -m evals.datasets_io                          # sync evals/datasets/*.jsonl ขึ้น LangSmith (idempotent)
python -m evals.run_chatbot_eval --suite security    # ชุดสำคัญสุด — scope guard + prompt injection
python -m evals.run_chatbot_eval --local             # debug evaluator โดยไม่ส่งขึ้น cloud
python -m evals.run_retrieval_eval --dump            # พิมพ์ chunk ให้คน label qrels
python -m evals.run_retrieval_eval --sweep           # หา RAG_MIN_SCORE ด้วยข้อมูลจริง (แทนค่าเดา)
```

ไม่มี `.env` หรือไม่ได้ตั้ง `DATABASE_URL` → fallback เป็น postgres ในเครื่องตัวเอง
(`postgresql://localhost/finrisk_dev`) ใช้ทดสอบคนเดียวได้ แต่ข้อมูลจะไม่ sync กับคนอื่น
ทั้ง API และ `seed_database.py` อ่านค่าเดียวกันจาก `src/config.py` (โหลด `.env` ผ่าน
`python-dotenv` อัตโนมัติ)

**env vars:** `src/config.py` โหลด `.env` ที่ repo root ให้อัตโนมัติตอน import (`load_dotenv()`)
ลำดับความสำคัญ: **env จาก shell/Vercel ชนะ `.env` เสมอ** (ใช้ `os.environ.setdefault`)
ใส่คีย์ใหม่ที่ `.env` ได้เลย ไม่ต้อง export เอง — `.env` อยู่ใน `.gitignore` ห้าม commit
คีย์ที่ใช้: `DATABASE_URL`, `JWT_SECRET`, `GEMINI_API_KEY`, `PINECONE_API_KEY`, `TYPHOON_OCR_API_KEY`,
`RAG_TOP_K`, `RAG_MIN_SCORE`, `RAG_MAX_CHUNK_TOKENS`,
`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`

⚠️ **`LANGSMITH_TRACING=true` = prompt, ผล tool (ชื่อโครงการ/ผู้ชนะ/งบประมาณ) และเนื้อความเอกสาร
ปร.4/5/6 ถูกส่งขึ้น LangSmith cloud** — ตอนนี้เปิดได้เพราะยังใช้ข้อมูล mock
(`docs/langsmith_eval_plan.md` §7 ทางเลือก A) **ก่อนใช้กับข้อมูลจริงต้องทบทวนใหม่**
(ปิด flag / `LANGSMITH_HIDE_INPUTS` / self-hosted) มี warning log ตอน startup ให้เห็นเสมอว่าเปิดอยู่

## สถาปัตยกรรม

- `src/main.py` — สร้าง `app`, ผูก CORS, include router ทั้งหมด, `/health` + `/`
- `src/config.py` — `DATABASE_URL` (env, มี default local dev), CORS origin อ่านจาก env มี default
- `src/database.py` — `get_db()` เป็น FastAPI dependency คืน psycopg connection;
  `Connection`/`Cursor` แปลง `?` placeholder (สไตล์เดิมของทั้ง repo) เป็น `%s` ให้อัตโนมัติ;
  `SqliteLikeRow` เลียนแบบ `sqlite3.Row` (index ตัวเลข + key ชื่อคอลัมน์ + iterate เป็นค่า)
  เพื่อให้ query เดิมทั่ว repo ใช้ต่อได้โดยไม่ต้องแก้ทีละจุด; helper `rows_to_dicts()`
- `src/auth.py` — JWT login (bcrypt + PyJWT) + `get_current_user`, `require_roles(...)`, `scope_subdistrict_ids(...)`
- `src/schemas.py` — Pydantic model (request/response) + `ALLOWED_FEATURES` (14 flags ของ user-management)
- `src/notify.py` — `create_notification()` helper insert-only ใช้โดย `audit.py`/`admin.py`
- `src/services/*.py` — **"agent tool contract"**: logic + scope guard เขียนเป็น service function
  ที่ raise domain error (`NotFoundError`/`ForbiddenError`/`ValidationError` จาก `services/common.py`)
  แทนที่จะ raise `HTTPException` ตรงๆ เพื่อให้ทั้ง router (HTTP) และ chatbot tool (non-HTTP)
  เรียก logic เดียวกันได้ — มี `common.py`, `projects.py`, `legal.py`, `documents.py`, `users.py`,
  `chatbot.py` (orchestration เอง ไม่ใช่ tool ที่ถูกเรียก)
  ⚠️ **ข้อยกเว้น**: `src/routers/audit.py` ยังไม่มี service layer เลย — เขียน SQL ตรงในราวเตอร์
  ทั้งไฟล์ ไม่ตาม pattern นี้ (ผลคือ `/audit/feedback` มีช่องโหว่ scope guard ที่ยังไม่ได้แก้ ดู
  หัวข้อ "สิ่งที่ยังไม่ทำ" ด้านล่าง) — ถ้าเพิ่มฟีเจอร์ใหม่ในไฟล์นี้ พิจารณา extract เป็น
  `services/audit.py` ไปพร้อมกัน
- `src/routers/*.py` — endpoint แยกตามโดเมน: `auth, subdistricts, projects, risk, audit, financials,
  admin, users, notifications, public, legal (2 routers), documents (2 routers), chatbot`
  (ครบตามที่ include ใน `main.py`)

- `scripts/ingest_documents.py` — offline CLI: OCR เอกสาร ปร.4/5/6 จาก `raw_documents/` → chunk →
  upsert ขึ้น Pinecone (+ สำเนาลง `document_chunks`) **ไม่อยู่ใน request path และไม่เขียน
  `project_documents` เลย** (§4.4 ของ `docs/rag_pinecone_plan.md`) — สถานะรวมของงาน RAG อยู่ที่ §0.1
  ของเอกสารนั้น
- `src/services/retrieval.py` — ชั้น query ของ RAG: ค้น Pinecone (integrated inference — **ไม่เรียก
  embedding API เอง และห้ามเติม prefix `query:`/`passage:` เอง**) แล้ว **post-verify กับ Postgres เสมอ**
  ก่อนคืนผล ใช้โดย `GET /projects/{id}/documents/search` และ tool ตัวที่ 6 ของ chatbot
  `PINECONE_API_KEY` จำเป็นต้องระบุ หากไม่มีจะ raise RuntimeError ตอนเริ่มระบบ (`src/main.py`)
- `scripts/calibrate_rag.py` — offline CLI หาค่า `RAG_MIN_SCORE` (อ่านอย่างเดียว ไม่แก้ไฟล์ใด)
- `src/observability.py` — ชั้นห่อ LangSmith **แบบ optional**: ไม่ลง `langsmith` หรือไม่ตั้ง
  `LANGSMITH_TRACING=true` → `traceable()` คืนฟังก์ชันเดิมตรงๆ และ `wrap_gemini()` คืน client เดิม
  (pattern เดียวกับ `retrieval.rag_enabled()` — feature flag ต้องปิดได้จริง)
  **ห้าม `import langsmith` ที่อื่นนอกจากไฟล์นี้กับ `evals/`** ไม่งั้น optional dependency
  จะกลายเป็น dependency บังคับโดยไม่ตั้งใจ
  ⚠️ ทุกจุดที่ห่อฟังก์ชันซึ่งรับ `conn`/`user` **ต้องส่ง `process_inputs=`** เสมอ —
  `conn` (psycopg Connection) serialize ไม่ได้ และ `user` มี `username`/`display_name`
  ของเจ้าหน้าที่ซึ่งห้ามออกนอกระบบ (ใช้ `redact_*` ที่มีให้แล้ว)
- `evals/` — ชุดวัดคุณภาพชั้น AI (dataset jsonl + evaluator + runner) **ไม่ถูก collect โดย
  `pytest -q`** เพราะยิง Gemini/Pinecone จริง — ส่วนที่เป็น logic ล้วนมีเทสต์อยู่ที่
  `tests/test_observability_evals.py` ตามปกติ ดู `evals/README.md`

**Data flow:** CSV (`standardized_data/`) → `seed_database.py` เขียนลง PostgreSQL (ตาม `DATABASE_URL`)
→ risk engine ใน seed คำนวณและเขียนตาราง `*_risk_results` / `project_risk_scores`
→ FastAPI ส่วนใหญ่ **อ่านอย่างเดียว** จาก DB ยกเว้น `src/routers/admin.py`
(`POST /admin/data/upload` นำเข้า CSV โครงการ/งบการเงินของตำบลที่มีอยู่แล้ว,
`POST /admin/risk-engine/run` สั่งคำนวณ risk score ใหม่) — ทั้งสอง endpoint เรียก
`seed_vendors`/`seed_projects`/`seed_financial`/`run_project_engine`/`run_annual_engine`
จาก `seed_database.py` ตรงๆ (import เป็น top-level module จาก repo root) **ห้ามก็อปโค้ด
มาเขียนซ้ำใน router** เพราะ logic ต้องอยู่ที่เดียวตามกติกาด้านล่าง

**Chatbot (`POST /chatbot`, PR #26):** ไม่มีตรรกะ query ของตัวเอง — `src/services/chatbot.py`
เรียก service function เดิม (`projects.py`/`legal.py`/`documents.py`) เป็น "tool" ให้ Gemini
function-calling เท่านั้น การ์ดสิทธิ์จึงเป็น deterministic ผ่าน `scope_subdistrict_ids` เดิม
ไม่ใช่ prompt guardrail รายละเอียดโมเดล/ทำไมไม่ใช้ RAG ดู `docs/chatbot_architecture.md`

**เขียน SQL ใหม่:** ใช้ `?` placeholder แบบเดิมได้เลย (แปลงเป็น `%s` อัตโนมัติที่ `src/database.py`)
แต่ต้องรู้ 3 จุดต่างจาก SQLite เดิม: (1) ไม่มี `.lastrowid` — ใช้ `INSERT ... RETURNING <pk>` แล้ว
`.fetchone()["<pk>"]` (2) เวลาให้ใช้ SQL function `now_text()` แทน `datetime('now')` (นิยามไว้ใน DDL
ของ `seed_database.py`) (3) ไม่มี `INSERT OR IGNORE`/`OR REPLACE` — ใช้ `ON CONFLICT (...) DO NOTHING`

## คอนเวนชันการเขียนโค้ด

- **ภาษาในโค้ด/คอมเมนต์: ไทยได้** (โดเมนเป็นภาษาไทย) — คงสไตล์เดิมของ repo ไว้
- ชื่อคอลัมน์ DB/CSV เป็น **snake_case อังกฤษ** เสมอ (ดู `_schema_dictionary.md`)
- **ทุก query ที่คืนข้อมูลระดับตำบลต้องผ่าน scope guard** — เรียก
  `scope_subdistrict_ids(conn, user)` แล้ว filter `subdistrict_id`
  role ตาม `roles.md` (seed ลงตาราง `roles`): `local_executive/project_auditor/risk_analyst`
  เห็นเฉพาะตำบลตัวเอง; `admin/regional_supervisor/public_user` เห็นทุกตำบล
  สิทธิ์ราย endpoint บังคับที่ app layer ด้วย `require_roles(...)`
- **ข้อมูลที่มาจากนอก Postgres (เช่น Pinecone) ต้อง post-verify กับ Postgres ก่อนคืนผู้ใช้เสมอ** —
  metadata ที่ copy ไว้ตอน ingest ไม่ใช่หลักฐานสิทธิ์ ดูตัวอย่างที่ `src/services/retrieval.py`
  (`_verify_and_enrich`) และเทสต์ `test_search_post_verify_blocks_poisoned_hit`
- ใช้ **parameterized query** เท่านั้น (`?` placeholder) ห้าม f-string ค่าที่มาจาก user
  (การ interpolate ที่มีตอนนี้เป็นแค่จำนวน placeholder `?` ไม่ใช่ค่า)
- router ใหม่: สร้างใน `src/routers/`, ตั้ง `APIRouter(prefix=..., tags=[...])`,
  แล้ว `include_router` ใน `main.py`
- อย่าแก้ตรรกะ risk ในโค้ด API — logic ทั้งหมดอยู่ใน `seed_database.py`
  (`run_project_engine`, `run_annual_engine`) แก้ที่นั่นแล้วรัน seed ใหม่

## Auth (JWT)

- รหัสผ่านเก็บเป็น **bcrypt hash** (มี salt ในตัว) — mock user ทุกคนยังใช้ `password123` เหมือนเดิม
- `/auth/login` ออก **JWT access token** (HS256, อายุ `JWT_EXPIRE_MINUTES` ค่า default 480 นาที)
  endpoint ที่ต้อง auth อ่าน token จาก header `Authorization: Bearer <token>`
- ⚠️ **`JWT_SECRET`**: ต้องตั้ง env var เป็นค่าสุ่มยาวๆ ก่อนขึ้น production — ถ้ายังใช้ default
  จะมี warning log ตอน startup (`src/main.py`); ถ้า `VERCEL_ENV=production` ด้วย จะ **fail-fast**
  (raise `RuntimeError` ตอน import) แทนที่จะรันเงียบๆ ด้วย secret ที่รู้กันอยู่แล้ว
- ⚠️ **ช่วงเปลี่ยนผ่าน**: `get_current_user` ยังรับ header `X-Username` แบบเดิม (ไม่ verify ลายเซ็น)
  เป็น fallback เพราะ frontend ที่ deploy อยู่ยังส่ง header นี้อยู่ — ลบ fallback นี้ทิ้งได้เมื่อ
  frontend เปลี่ยนไปส่ง `Authorization: Bearer` ครบแล้ว (ดู FinRisk-Frontend issue #28)
  ทุกครั้งที่ path นี้ถูกใช้จะมี warning log ให้เห็น

## ข้อควรระวังเรื่องข้อมูล (มีผลต่อ logic)

- **ปิงโค้ง** = ข้อมูลสรุป ไม่มีวันที่/พิกัด/TIN/เลขสัญญา → ตัวชี้วัดที่ใช้วันที่คำนวณไม่ได้
  ให้ mark `computable = 0` (อย่านับเป็น `triggered = 1`)
- `fraud_risk_flag` ว่าง ≠ FALSE — ยังไม่เคย label
- `winner_tin` บางแถวมี `xxxx` (ปกปิด) — dedup vendor ให้ใช้ `winner_name` ประกอบ
- ปิงโค้ง project `68039298502`: budget/contract = 0 ตามต้นฉบับ (ถูก flag ไว้แล้ว)
- ราคา/ตัวเลขใน 2 ไฟล์ต้นฉบับ (ท่าช้าง66, โยนก66) ถูกตัดท้าย — ดู `data_quality_note`

## Definition of done

- โค้ดใหม่ที่แตะข้อมูลตำบล **ผ่าน scope guard**
- `pytest -q` ผ่าน (เพิ่มเทสต์ใน `tests/` เมื่อเพิ่ม endpoint) — ต้องมี postgres รันอยู่ + สร้าง
  `finrisk_dev` แล้ว seed ไว้ก่อน
- ถ้าแก้ schema DB ต้องอัปเดตทั้ง `seed_database.py`, `data_model_design.md`, และ ERD
- ถ้าแตะชั้น AI (chatbot/retrieval): `pytest -q` ต้องผ่าน **ทั้งตอนที่ลง `langsmith` แล้วและยังไม่ลง**
  และปิด `LANGSMITH_TRACING` แล้วพฤติกรรมต้องเหมือนเดิม 100%

## สิ่งที่ยังไม่ทำ

- ต่อ `ocr_pipeline/` เข้าชั้นเอกสาร — ตอนนี้ `project_documents`/`document_findings`
  เป็น `source='mock'` ทั้งหมด ยังไม่มีแถว `source='ocr'`
  (`scripts/ingest_documents.py` ใช้ OCR แต่ผลลงแค่ Pinecone/`document_chunks` **ไม่แตะ provenance
  ของแถวเอกสาร** — ค่าที่ OCR/LLM สกัดได้ห้ามไหลเข้า `extracted_json`/`document_findings` อัตโนมัติ
  ต้องมี review gate ก่อน)
- ชั้น RAG ต่อครบแล้ว (ingest → retrieval → endpoint → tool ตัวที่ 6 → citations + เทสต์)
  **เหลือ 2 อย่าง**: (1) calibrate `RAG_MIN_SCORE` — ค่า 0.82 ที่ใช้อยู่ยังเป็นค่าเดา
  ต้องรัน `python -m scripts.calibrate_rag` ในเครื่องที่ต่อ Pinecone ได้แล้วตั้งค่าใน `.env`
  (ทางเลือกที่ให้หลักฐานดีกว่า: `python -m evals.run_retrieval_eval --sweep` ซึ่งเทียบ
  recall/precision ที่ threshold หลายค่าบน qrels — แต่ต้อง label `relevant_chunk_ids`
  ใน `evals/datasets/retrieval_qrels.jsonl` ก่อน ตอนนี้ยังว่างทั้งหมด)
  (2) ตั้ง env บน Vercel ซึ่งติด blocker ข้อแรกอยู่ — ดู `docs/rag_pinecone_plan.md` §0.1
- ถ้า ingest รอบใหม่ได้ chunk **น้อยลง**กว่ารอบก่อน record เบอร์ท้ายๆ ของรอบเก่าจะค้างบน Pinecone
  (post-verify กรองไม่ออกเพราะ `project_id`/`doc_type_code` ยังถูกต้อง — จะโผล่มาเป็น chunk เก่า)
  ยังไม่มีขั้นตอนลบส่วนเกิน เอกสารชุด demo คงที่จึงยังไม่กระทบ
- `GET /audit/feedback` + `GET /audit/feedback/{project_id}` คืน feedback สถานะ `draft`
  ของ auditor คนอื่นให้ทุก role ใน scope เห็น (รวม `local_executive` ซึ่งเป็นฝ่ายถูกตรวจ)
  — ควร filter ให้ draft เห็นเฉพาะเจ้าของ (issue #30)
- `GET /audit/feedback/{project_id}` ยังไม่ผ่าน scope guard (ส่ง project_id ของตำบลอื่นก็เห็นได้ —
  issue #30 เดียวกัน เกิดจาก `audit.py` ไม่มี service layer ตามที่ระบุด้านบน)
- `JWT_SECRET` default (`dev-only-insecure-secret-change-before-production`) แค่ warn ตอน startup
  ไม่ fail-fast — ควร raise/exit ตอน import ถ้ายังเป็นค่า default และ env เป็น production (issue #31)
- `POST /chatbot` ไม่มี rate limit ต่อ user เลย — 1 ข้อความอาจ trigger tool-calling ได้ถึง
  `MAX_TOOL_TURNS=5` รอบ เสี่ยง cost ของ Gemini API บานถ้ามีคนยิงรัว (issue #32)
- log retention (archive/delete `access_log` ตามอายุ) — ยังไม่มีโค้ด/migration ใดๆ บน `main`
  เลย เป็น backlog ล้วนๆ (issue #28)
- ชั้น LangSmith: ทำแล้วเฉพาะ **tracing + metric ที่เป็น deterministic (M1–M4)**
  เหลือ (1) label `relevant_chunk_ids` ใน `evals/datasets/retrieval_qrels.jsonl` (ยังว่างทั้งหมด
  → metric ชั้น retrieval ยังไม่มีความหมายจนกว่าจะ label) (2) evaluator ที่ใช้ LLM-as-judge
  M5–M7 (computable=0 wording / groundedness / empty-result honesty) (3) ต่อ eval เข้า CI
  ดู `docs/langsmith_eval_plan.md` §0 ตารางสถานะ
- ยังไม่มี `langchain` ใน repo โดยตั้งใจ — LangSmith ไม่ต้องใช้ LangChain ถ้าจะเพิ่มภายหลัง
  ต้องอ่านข้อห้ามในแผน §5 ก่อน (โดยเฉพาะ: **ห้ามใช้ agent executor ที่ execute tool เอง**
  เพราะ `_execute_tool` ต้องเป็นทางผ่านเดียวที่มี scope guard)
