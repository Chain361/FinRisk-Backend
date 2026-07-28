# Local Budget Fraud Risk & Document Intelligence Assistant — Backend

ระบบช่วยประเมิน **ความเสี่ยงทุจริตงบประมาณ** ขององค์กรปกครองส่วนท้องถิ่น (เทศบาลตำบล)
จากข้อมูลจัดซื้อจัดจ้าง (e-GP) และงบการเงิน โดยรัน "risk engine" ให้คะแนนความเสี่ยง
รายโครงการและรายปีงบประมาณ แล้วเปิดให้ผู้ใช้แต่ละบทบาทเข้ามาตรวจสอบ/มอบหมายงานต่อ

> Repository นี้เป็น **backend** (Python + FastAPI + PostgreSQL) — คู่มือนี้สำหรับ dev ที่เพิ่งเข้ามาทำงาน

---

## 🚀 How to Run for Demo & Pipeline CLI

### ⚙️ 1. Master Pipeline ([run_pipeline.py](run_pipeline.py))
สำหรับผู้รัน demo หรือประมวลผลข้อมูลตั้งแต่ต้นจนจบ — Pipeline ทั้งหมด (OCR → ตรวจคุณภาพ/Validation → Promote ข้อมูลลง Master CSV → ลงฐานข้อมูล → คำนวณความเสี่ยง) รวมอยู่ในคำสั่งเดียว:

```bash
pip install -r requirements.txt
python run_pipeline.py
```

ถ้าต้องการ OCR สดจาก PDF ให้สร้างไฟล์ `.env` ที่ root ของ repo (ไม่มีก็รันได้ — ระบบจะใช้ OCR cache เดิมอัตโนมัติ):
```env
TYPHOON_OCR_API_KEY=<คีย์ของคุณ>   # สมัครฟรีที่ opentyphoon.ai
```

#### Flag และ Options ของ `run_pipeline.py`:
* **`python run_pipeline.py`** : รันกระบวนการแบบครบวงจร (Batch OCR → Validate → Promote ลง Master CSV → Seed DB)
* **`python run_pipeline.py --dry-run`** : ทดลองรัน OCR + Validate เท่านั้น **โดยไม่เขียน/แก้ไข** DB หรือ Master CSV
* **`python run_pipeline.py --include-needs-review`** : Promote เอกสารที่มีสถานะ `needs_review` ลง DB/CSV ด้วย (หลังผ่านการตรวจสอบใน `ocr_pipeline/work/<run_id>/review/queue.csv` แล้ว)
* **`python run_pipeline.py --include-fails`** : Promote ข้อมูลทั้งหมดรวมถึงเอกสารที่ไม่ผ่าน Validation (ใช้เพื่อการทดสอบ/Debugging)
* **`python run_pipeline.py --input-dir <folder>`** : ระบุโฟลเดอร์เก็บไฟล์ PDF + `batch.csv` (default: `raw_financial_statements/`)
* **`python run_pipeline.py --skip-backup`** : ข้ามการสร้างไฟล์สำรอง (`.bak`) ของ Master CSV
* **`python run_pipeline.py --enable-rag`** : รัน Law RAG plugin (ปัจจุบันเป็น stub)

> 💡 **ระบบความปลอดภัยข้อมูล (Auto-Backup & Rollback):** `run_pipeline.py` จะสร้างไฟล์สำรองแบบติดประทับเวลา (`.bak.YYYYMMDD_HHMMSS`) ของ Master CSV ก่อนเริ่มเขียนเสมอ หากขั้นตอนใดล้มเหลว ระบบจะทำ **Auto-Rollback** คืนค่า Master CSV ทันที — **DB เป็น PostgreSQL แล้ว ยังไม่มี auto-backup/rollback** (`seed_database.py --force` ทำ `DROP SCHEMA` ก่อนสร้างใหม่เสมอ กู้คืนเองผ่าน `pg_dump`/`pg_restore` ถ้าจำเป็น)

#### 🛠️ Troubleshooting `run_pipeline.py`

| อาการ | สาเหตุ/ทางแก้ |
|---|---|
| ขึ้นว่าไม่มี poppler / pdftoppm | ไม่ต้องแก้ถ้ามี OCR cache (ระบบ fallback ให้เอง) — ถ้าต้อง OCR สดบน Windows: ดาวน์โหลด [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases) แล้วเพิ่ม `Library\bin` ลง PATH หรือแค่เปิด Docker Desktop ไว้ ระบบจะสลับไปรันใน container ให้ |
| `circuit breaker: ไม่มีเอกสารใดผ่าน gate` | ทุกไฟล์ fail/needs_review — เปิด `ocr_pipeline/work/<run_id>/review/queue.csv` ตรวจแล้วรันใหม่ด้วย `--include-needs-review` หรือ `--include-fails` |
| pipeline ล้มกลางทาง | ระบบ rollback master CSV ให้อัตโนมัติ (DB ยังไม่มี auto-rollback — ดู PostgreSQL note ด้านบน) — ดูสาเหตุใน `pipeline_run.log` |
| อยากดูผลรันย้อนหลัง | เปิด `pipeline_run.log` (สรุปทุกครั้งที่รัน) |

---

### 🗄️ 2. Standalone Database Seeding ([seed_database.py](seed_database.py))
สามารถรัน `seed_database.py` แยกต่างหากได้ตามปกติโดยไม่ต้องรัน `run_pipeline.py` (ใช้กรณีที่มีไฟล์ Master CSV ใน `standardized_data/` เรียบร้อยแล้ว และต้องการสร้าง/Re-build ฐานข้อมูล PostgreSQL + รัน Risk Engine เท่านั้น)

```bash
# สร้าง schema + seed ข้อมูล + รัน risk engine ครั้งแรก
python seed_database.py

# ลบตารางเดิมทั้งหมดแล้วสร้างใหม่จาก Master CSV
python seed_database.py --force
```

#### Flag และ Options ของ `seed_database.py`:
* **`python seed_database.py`** : อ่านไฟล์ Master CSV จาก `standardized_data/` เพื่อสร้าง schema, seed ข้อมูล, รัน risk engine และทำการ validation
* **`python seed_database.py --force`** : ลบตารางเดิมทั้งหมด (`DROP SCHEMA public CASCADE`) ก่อนสร้างใหม่

> 📌 DB target อ่านจาก env var `DATABASE_URL` (default: `postgresql://localhost/finrisk_dev`) — ดู `src/config.py`

---

## 1. อ่านอะไรก่อน (5 นาทีแรก)

| อยากรู้เรื่อง | เปิดไฟล์ |
|---|---|
| สถาปัตยกรรม backend + integration กับ frontend repo | `docs/ARCHITECTURE.md` |
| โจทย์/ภาพรวมทั้งระบบ | `Mission 3_ Local Budget Fraud Risk & Document Intelligence Assistant.pdf` |
| โครงสร้างฐานข้อมูล (ตาราง + เหตุผล) | `data_model_design.md`, `data_model_erd.mermaid` |
| นิยามคอลัมน์ CSV ต้นทาง | `_schema_dictionary.md` |
| ตรรกะให้คะแนนความเสี่ยง | `Risk Factor Design ระดับโครงการ.md`, `Risk Factor Design ระดับงบรายปี.md` |
| บทบาทผู้ใช้ (roles) + สิทธิ์ | `roles.md` (source of truth), README §5 |
| กติกา/คอนเวนชันสำหรับเขียนโค้ด | `CLAUDE.md` |

---

## 2. Quick start

ต้องมี **Python 3.10+** และ **PostgreSQL** รันอยู่ (local: `brew install postgresql@18` หรือเทียบเท่า)

```bash
# 1) สร้าง database เปล่าไว้ก่อน (ครั้งแรกเท่านั้น)
createdb finrisk_dev

# 2) (แนะนำ) สร้าง virtual env
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3) ติดตั้ง dependency (รวม psycopg driver)
pip install -r requirements.txt

# 4) สร้าง schema + seed ข้อมูล + รัน risk engine ครั้งแรก
python seed_database.py

# 5) รัน API
uvicorn src.main:app --reload
```

เปิดเอกสาร API อัตโนมัติที่ **http://127.0.0.1:8000/docs**
ตรวจสุขภาพระบบที่ **http://127.0.0.1:8000/health**

> DB connection อ่านจาก env var `DATABASE_URL` (default: `postgresql://localhost/finrisk_dev`)
> ตั้งค่าต่างออกไปได้ถ้า database ชื่ออื่น/อยู่เครื่องอื่น — ดู `src/config.py`

### Log retention scheduled job

Access/security audit logs use the 90/365 day policy in `app_config`:
`log_retention_hot_days = 90` and `log_retention_archive_days = 365`.
Error/debug logs use `error_debug_log_hot_days = 30`; the app stores only masked,
truncated error metadata in `error_debug_log` and does not archive it.

Existing DB migration order:

```bash
psql "$DATABASE_URL" -f migrations/20260728_log_retention.sql
psql "$DATABASE_URL" -f migrations/20260728_error_debug_log_retention.sql
```

Manual run:

```bash
python scripts/run_log_retention.py --triggered-by manual
```

Automatic run:

- `.github/workflows/log-retention.yml` runs daily at 18:30 UTC / 01:30 Asia/Bangkok.
- Set repository secret `DATABASE_URL` to the target DB connection string.
- GitHub scheduled workflows run from the default branch after this workflow is merged.
- The workflow also supports `workflow_dispatch` for manual runs from GitHub Actions.
### 2.1 Ingest เอกสาร ปร. ขึ้น Pinecone (ทางเลือก — สำหรับค้นเนื้อหาเอกสารเต็ม)

ชั้น RAG แยกจากระบบหลักทั้งหมด **ข้ามขั้นนี้ได้ ระบบเดิมทำงานครบ** (ดู `docs/rag_pinecone_plan.md`)

```bash
pip install pinecone transformers        # transformers ใช้แค่ตอนนับ token ก่อน upsert
# ใส่ใน .env ที่ repo root: TYPHOON_OCR_API_KEY=... และ PINECONE_API_KEY=...

python -m scripts.ingest_documents --project MOCK-CON-001 --dry-run --show-chunks   # ดู chunk ก่อน
python -m scripts.ingest_documents --project MOCK-CON-001                           # upsert จริง
```

* **`--dry-run`** : OCR + chunk + นับ token แล้วพิมพ์ออกมาเฉยๆ ไม่แตะ Pinecone และไม่เขียน DB
* **`--table-format markdown\|html`** : Typhoon คืนตารางเป็น HTML — default แปลงเป็นตาราง `|` ก่อน chunk
* **`--max-chars`** (default 600) : เพดานจริงคือ 480 token/chunk — เกินแล้ว **สคริปต์ fail** ไม่ใช่แค่เตือน
  เพราะโมเดล `multilingual-e5-large` ตัดส่วนเกินทิ้งเงียบๆ โดยไม่มี error
* **`--force-ocr`** : OCR ใหม่ (ปกติใช้ cache ใน `ocr_pipeline/work/rag-ingest/ocr/` ไม่เสียโควตาซ้ำ)

> ⚠️ สคริปต์นี้ **ไม่เขียน `project_documents` เลย** — `status`/`extracted_json`/`file_path` เป็นของ
> `seed_database.py` ผู้เดียว risk factor L1/L3 ที่อ่าน `status` จึงไม่มีทางถูกกระทบ
> ส่วน `document_chunks` ถูก **เขียนทับ** ด้วย chunk จาก OCR (ของเดิมที่ seed ใส่คือ `summary_text`)

### 2.2 ใช้งานชั้นค้นเอกสาร (retrieval)

หลัง ingest แล้ว `PINECONE_API_KEY` ใน `.env` เปิดสองอย่างพร้อมกัน: endpoint ค้นเอกสาร และ tool ตัวที่ 6
ของ chatbot (`search_document_text`) — **คีย์ว่าง = ปิดทั้งคู่ ระบบเดิมทำงานครบเหมือนเดิม**

```bash
uvicorn src.main:app --reload
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
        -d '{"username":"auditor3","password":"password123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# min_score=0 → เห็นคะแนนดิบทุก hit (ใช้ตอน calibrate)
curl -H "Authorization: Bearer $TOKEN" \
  "localhost:8000/projects/MOCK-CON-001/documents/search?q=Factor%20F&min_score=0"

python -m scripts.calibrate_rag        # ยิงชุดคำถามที่รู้คำตอบ → เสนอค่า RAG_MIN_SCORE
```

* ใช้ **`auditor3`/`analyst3`/`admin`** เท่านั้น — MOCK-CON-001 อยู่ตำบลโยนก `auditor1` (ท่าช้าง)
  จะได้ 403 ซึ่ง**ถูกต้องตาม scope guard** ไม่ใช่ RAG พัง
* คำตอบของ chatbot ที่อ้างเนื้อความเอกสารจะมี `citations`
  (`doc_type_code`, `doc_no`, `page_no`, `chunk_no`) ติดมาใน response เสมอ
* `RAG_MIN_SCORE` default 0.82 **ยังเป็นค่าเดา** — e5 ให้คะแนนคู่ที่ไม่เกี่ยวกันเลยราว 0.70–0.78
  ตั้งต่ำไป = chunk มั่วไหลเข้าไปให้ LLM ตอบ, สูงไป = ผู้ใช้เห็น "ไม่พบข้อมูล" ทั้งที่มี

---

## 3. โครงสร้างโฟลเดอร์

```
data_modelling/
├─ src/                         # โค้ด backend (FastAPI)
│  ├─ main.py                   # entry point — รวม router + CORS + /health
│  ├─ config.py                 # path DB, CORS origin, ค่าคงที่
│  ├─ database.py               # ตัวช่วยต่อ PostgreSQL (dependency get_db)
│  ├─ auth.py                   # login (bcrypt + JWT) + role/scope guard
│  ├─ schemas.py                # Pydantic models
│  ├─ notify.py                 # create_notification() — helper insert-only ใช้โดย audit.py/admin.py
│  ├─ services/                 # service function (contract ที่ router + chatbot ใช้ร่วมกัน)
│  │  ├─ common.py              # scope guard + latest_run_id + domain error (ServiceError/NotFoundError/ForbiddenError)
│  │  ├─ projects.py            # list_projects_view / project_summary_view
│  │  ├─ legal.py               # ชั้นกฎหมาย (laws/sections/factor_legal_map)
│  │  ├─ documents.py           # ชั้นเอกสาร (doc types/status/missing/findings)
│  │  ├─ users.py               # get_users / update_user (user-management)
│  │  ├─ retrieval.py           # ค้นเนื้อหาเอกสารเต็มบน Pinecone + post-verify กับ Postgres (ดู §2.2)
│  │  └─ chatbot.py             # orchestration Gemini function-calling (tool 6 ตัว — ดู docs/chatbot_architecture.md)
│  └─ routers/                  # endpoint แยกตามโดเมน
│     ├─ auth.py                # /auth/login, /auth/me
│     ├─ subdistricts.py        # /subdistricts
│     ├─ projects.py            # /projects (+ risk score ล่าสุด)
│     ├─ risk.py                # /risk/factors, /risk/annual, /risk/summary
│     ├─ audit.py               # /audit/assignments (approval chain), /audit/feedback, /audit/access-log
│     ├─ financials.py          # /financial-statements, /financials
│     ├─ admin.py               # /admin/data/upload, /admin/risk-engine/run (admin เท่านั้น)
│     ├─ users.py               # /users — admin จัดการ role/subdistrict/allowed_features
│     ├─ notifications.py       # /notifications — unread count, mark-as-read
│     ├─ public.py              # /public/projects/export — open data (CSV/JSON)
│     ├─ legal.py               # /legal/laws, /risk/projects/{id}/legal
│     ├─ documents.py           # /documents/types, /projects/{id}/documents(/search)
│     └─ chatbot.py             # /chatbot — Gemini function-calling (admin/project_auditor/risk_analyst)
├─ tests/
│  ├─ test_smoke.py             # smoke test (pytest)
│  ├─ test_legal_documents.py   # เทสต์ชั้นกฎหมาย + ชั้นเอกสาร
│  ├─ test_chatbot.py           # เทสต์ orchestration + scope guard ของ chatbot
│  └─ test_retrieval.py         # เทสต์ชั้น RAG (scope guard สองชั้น + citations)
├─ scripts/
│  ├─ ingest_documents.py       # offline: OCR เอกสาร ปร. → chunk → upsert Pinecone (ดู §2.1)
│  └─ calibrate_rag.py          # offline: หาค่า RAG_MIN_SCORE จาก chunk จริง (ดู §2.2)
├─ legal_refs/                  # CSV กฎหมายที่ curate แล้ว (laws, law_sections, factor_legal_map)
├─ mock_documents/              # CSV ชั้นเอกสาร mock (doc types, documents, findings, finding map)
├─ raw_documents/               # ไฟล์ภาพเอกสาร ปร.4/5/6 ของโครงการเดโม (ต้นทางของ RAG)
├─ seed_database.py             # สร้าง schema บน PostgreSQL + seed + รัน risk engine + validate
├─ standardized_data/           # CSV กลางที่ seed อ่านเข้า
│  ├─ projects_ALL_master.csv          (98 แถว → 97 โครงการหลัง dedup)
│  └─ financial_report_ALL_master.csv  (337 แถว)
├─ ตำบลท่าช้าง/ ตำบลปิงโค้ง/ ตำบลโยนก/   # ข้อมูลดิบต้นทางรายตำบล
├─ requirements.txt
├─ README.md                    # ← ไฟล์นี้
└─ CLAUDE.md                    # แนวทางสำหรับ AI coding agent
```

---

## 4. Data model โดยย่อ

ฐานข้อมูล PostgreSQL เดียว (ตาม `DATABASE_URL`) 27 ตาราง แบ่งเป็น 5 กลุ่ม:

**Master data** — `subdistricts` (3 ตำบล), `vendors` (57 ราย), `projects` (97 โครงการ),
`financial_statements` (337 บรรทัดงบการเงิน), `roles` (6 บทบาท ตาม `roles.md`), `users` (8 mock users
+ คอลัมน์ `allowed_features TEXT[]` — ดู §5)

**Risk engine config** — `risk_factors` (8 ตัวชี้วัด), `app_config` (เกณฑ์แบ่งระดับความเสี่ยง)

**Risk results** (เขียนโดย engine ทุก run) — `assessment_runs`, `project_risk_results`,
`project_risk_scores`, `annual_risk_results`

**Audit workflow + notifications** — `assignments` (approval chain: `waiting_acceptance` →
`accepted`/`in_progress` → `ready_for_review` → `under_review` → `pending_approval` → `completed`,
อนุมัติขั้นสุดท้ายโดย `regional_supervisor`), `assignment_status_history`, `auditor_feedback`
(CRUD + resolve workflow ใช้งานจริงแล้ว), `notifications` (bell icon ฝั่ง frontend),
`access_log` (accountability trail, admin ดูได้ที่ `GET /audit/access-log`)
และ log retention tables (`access_log_archive`, `access_log_holds`, `log_retention_runs`,
`error_debug_log`)
สำหรับ archive/delete ตาม policy 90/365 วัน
> `audit_reports` มีอยู่ใน schema แต่ไม่มีโค้ดใดอ้างอิงถึงแล้ว — ถูกแทนที่ด้วย `auditor_feedback`
> เก็บไว้เป็น legacy ยังไม่ได้ลบ

ดู ERD เต็มได้ที่ `data_model_erd.mermaid` และคำอธิบายทุกตาราง/คอลัมน์ที่ `data_model_design.md`

**Legal linkage + document layer** (ดู `docs/legal_linkage_plan.md`) — `laws`, `law_sections`,
`factor_legal_map`, `project_compliance`, `document_types`, `project_documents`,
`document_findings`, `finding_legal_map`, `document_chunks` (คอลัมน์ `embedding` เผื่อไว้สำหรับ RAG
ในอนาคต ปัจจุบัน chatbot ใช้ structured tool-calling ไม่ใช่ RAG — ดู `docs/chatbot_architecture.md`)

### Risk factors (11 ตัว)

| Code | ระดับ | ชื่อ |
|---|---|---|
| A1 | project | ส่วนลดผิดปกติ |
| A2 | project | ส่วนลดน้อยผิดปกติ |
| A3 | project | ราคากลางชนงบพอดี |
| D1 | project | วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง |
| F1 | project | จัดจ้างกระจุกตัวท้ายปีงบ |
| L1 | project | ขาดเอกสารราคากลาง (ปร.4/ปร.5/ปร.6) — เฉพาะ `จ้างก่อสร้าง` |
| L2 | project | พื้นที่ดำเนินการนอกกรอบอำนาจหน้าที่ — เฉพาะ `จ้างก่อสร้าง` |
| L3 | project | เนื้อหาเอกสารราคากลางมีพิรุธ — เฉพาะ `จ้างก่อสร้าง` |
| Y1 | annual | อัตราการพึ่งพาตนเองทางการคลัง |
| Y2 | annual | ดุลการดำเนินงานประจำปี |
| Y3 | annual | Cash Coverage Ratio |

`project_risk_scores.risk_level` แบ่งตาม `app_config`: `medium` เมื่อ score ≥ 30, `high` เมื่อ > 60

---

## 5. บทบาทผู้ใช้ (roles) และ scope

นิยาม role และสิทธิ์ทั้งหมดอยู่ใน **`roles.md`** (source of truth) — DB เก็บชื่อ/คำอธิบาย role
ในตาราง `roles` ส่วนการบังคับสิทธิ์ทำที่ app layer (`require_roles(...)` ใน `src/auth.py`)

mock users ทั้งหมดรหัสผ่านเดียวกัน: **`password123`**

| username | role | เห็นอะไร |
|---|---|---|
| `admin` | admin | ทุกตำบล + ตั้งค่าระบบ (risk_factors, app_config, users) |
| `supervisor1` | regional_supervisor | ทุกตำบล เปรียบเทียบข้ามตำบลได้ |
| `thachang_user` / `pingkhong_user` / `yonok_user` | local_executive | **เฉพาะตำบลของตัวเอง** |
| `auditor1` / `auditor2` / `auditor3` | project_auditor | เฉพาะตำบลของตัวเอง + มอบหมายงานตรวจสอบ |
| `analyst1` / `analyst2` / `analyst3` | risk_analyst | เฉพาะตำบลของตัวเอง + รับงานที่ได้รับมอบหมาย + ส่งรายงานผลตรวจ |
| `public1` | public_user | ทุกตำบล (read-only, **ไม่เห็นข้อมูลที่ถูกปิดไว้** เช่น `/audit/*`) |

การจำกัด scope อยู่ที่ `src/auth.py` → `scope_subdistrict_ids()` ทุก endpoint ที่คืนข้อมูลตำบล
ต้องเรียกใช้ฟังก์ชันนี้เสมอ

**`allowed_features`** — permission layer เสริมเหนือ role (คอลัมน์ `users.allowed_features TEXT[]`,
แก้ได้ที่ `PUT /users/{user_id}` โดย admin เท่านั้น) จำกัด/เปิดความสามารถแบบ per-user ละเอียดกว่า role
เดี่ยวๆ เช่น เปิด `chatbot` หรือ `audit_feedback` ให้ user บางคนเฉพาะ — ดู flag ทั้งหมดที่
`src/schemas.py::ALLOWED_FEATURES` ไม่ได้แทนที่ role/scope guard ข้างต้น เป็นชั้นเสริมคนละแกน

---

## 6. ทดลองยิง API

```bash
# login — รหัสผ่าน bcrypt hash แล้ว, ได้ JWT access token กลับมา (อายุ 8 ชม.)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')

# ทุก endpoint ที่ต้อง auth ให้แนบ header Authorization: Bearer <token>
curl http://127.0.0.1:8000/projects?risk_level=high -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/risk/summary            -H "X-Username: thachang_user"  # legacy fallback ก็ยังใช้ได้ระหว่างเปลี่ยนผ่าน
curl http://127.0.0.1:8000/subdistricts            -H "X-Username: public1"        # ประชาชน: เห็นทุกตำบล

# ชั้นกฎหมาย + ชั้นเอกสาร (legal linkage) — โครงการเดโม MOCK-CON-001/002 อยู่ตำบลโยนก
curl http://127.0.0.1:8000/legal/laws                              -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/risk/projects/MOCK-CON-002/legal        -H "Authorization: Bearer $TOKEN"
curl "http://127.0.0.1:8000/risk/projects/MOCK-CON-002/legal?only_triggered=true" -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/projects/MOCK-CON-001/documents         -H "Authorization: Bearer $TOKEN"

# ค้นเนื้อความในตัวเอกสาร (ต้องมี PINECONE_API_KEY + ingest แล้ว — ดู §2.1/§2.2 ไม่งั้นตอบ 503)
curl "http://127.0.0.1:8000/projects/MOCK-CON-001/documents/search?q=Factor%20F" -H "Authorization: Bearer $TOKEN"
```

`/risk/projects/{id}/legal` คืน risk factor ล่าสุดของโครงการพร้อม `computable`,
`action_suggestion` และ `legal_refs` — ถ้า factor นั้น `triggered=1` แต่ยังไม่ได้ curate มาตรา
จะได้ `legal_refs: []` + `legal_ref_note` เป็นข้อความตายตัวจาก backend (ห้าม LLM แต่งมาตราเอง)

> ⚠️ ตั้ง env var **`JWT_SECRET`** เป็นค่าสุ่มยาวๆ ก่อนขึ้น production (ไม่งั้นจะมี warning log
> ตอน startup) — ดู `CLAUDE.md` หัวข้อ Auth

```bash
# admin: สั่งคำนวณ risk score ใหม่จากข้อมูลปัจจุบัน (ไม่อ่าน CSV ใหม่)
curl -X POST http://127.0.0.1:8000/admin/risk-engine/run -H "Authorization: Bearer $TOKEN"

# admin: นำเข้าโครงการ/งบการเงินรอบใหม่ของตำบลที่มีอยู่แล้ว (ฟอร์แมตตาม _schema_dictionary.md)
curl -X POST http://127.0.0.1:8000/admin/data/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "subdistrict_id=1" \
  -F "projects_csv=@new_projects.csv;type=text/csv"
# → รัน /admin/risk-engine/run ต่อเพื่อให้ dashboard เห็นผลข้อมูลใหม่
```

```bash
# แจ้งเตือน — unread count + list
curl http://127.0.0.1:8000/notifications?unread=true -H "Authorization: Bearer $TOKEN"

# มอบหมายงาน/อนุมัติ (approval chain) — เปลี่ยนสถานะ assignment
curl -X PATCH http://127.0.0.1:8000/audit/assignments/1/status \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"accepted"}'

# open data export — ไม่ต้อง scope guard ตำบล แต่ role-gate เฉพาะ admin/regional_supervisor/public_user
curl "http://127.0.0.1:8000/public/projects/export?format=csv" -H "Authorization: Bearer $TOKEN"

# chatbot — admin/project_auditor/risk_analyst เท่านั้น รายละเอียด orchestration/guardrail ดู
# docs/chatbot_architecture.md (ต้องตั้ง env var GEMINI_API_KEY ก่อน ไม่งั้นได้ 503)
curl -X POST http://127.0.0.1:8000/chatbot \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"โครงการ MOCK-CON-002 ขาดเอกสารอะไรบ้าง","history":[]}'
```

---

## 7. เทสต์

```bash
python -m pytest -q                       # ทั้ง tests/ และ ocr_pipeline/tests/ (ต้องมี postgres รันอยู่ + seed แล้ว)
python -m pytest tests/ -q                # เฉพาะ API (smoke + auth + admin + ชั้นกฎหมาย/เอกสาร)
python -m pytest ocr_pipeline/tests -q    # เฉพาะ OCR pipeline
```

`pytest.ini` กำหนด `testpaths` ไว้แล้ว และกัน `ocr_pipeline/work/` (ผลลัพธ์ต่อ run, gitignored)
ไม่ให้ถูก collect

### OCR fixture สำหรับ integration test

`ocr_pipeline/tests/test_ocr_pipeline_integration.py` ต้องใช้ OCR markdown ของงบ **ท่าช้าง 2567**
2 ชุด ซึ่ง **ไม่ได้ commit เข้า repo** (เป็นผลลัพธ์ที่สร้างใหม่ได้ และผูกกับ OCR engine):

| path | คืออะไร |
|---|---|
| `pipeline/ocr_output/thachang67` | OCR ชุดเต็ม 33 หน้าจาก `raw_financial_statements/ท่าช้าง67.pdf` |
| `pipeline/ocr_output/thachang67_standin` | ชุด "stand-in" — เฉพาะหน้างบแสดงฐานะการเงิน/งบแสดงผลการดำเนินงาน ที่ตรวจแก้จนตรงกับ master CSV แล้ว (ใช้เป็นฐานเทียบ cross-run) |

**ถ้าไม่พบทั้งสองโฟลเดอร์ เทสต์กลุ่มนี้จะถูก `skip` ไม่ใช่ fail** — `pytest -q` ที่ clone ใหม่จึงผ่านเสมอ

สร้างชุดเต็มใหม่ได้ด้วย (ต้องมี env `TYPHOON_OCR_API_KEY` เพราะเป็นการเรียก OCR จริง):

```bash
python -m ocr_pipeline.run --pdf raw_financial_statements/ท่าช้าง67.pdf \
  --subdistrict ท่าช้าง --municipality เทศบาลตำบลท่าช้าง --year 2567 \
  --source ท่าช้าง67.pdf --run-id t67
cp -r ocr_pipeline/work/t67/ocr pipeline/ocr_output/thachang67
```

ส่วนชุด `thachang67_standin` ต้องตรวจแก้ด้วยคนต่อจากชุดเต็ม (คัดเฉพาะ 2 หน้างบหลัก แล้วแก้ตัวเลข
ที่ OCR อ่านพลาดให้ตรง `standardized_data/financial_report_ALL_master.csv`) — เก็บไว้นอก repo

---

## 8. ข้อควรระวังเรื่องข้อมูล (สำคัญก่อนแก้ risk logic)

- **ตำบลปิงโค้ง** เป็นข้อมูลสรุป: ไม่มีวันที่/พิกัด/TIN/เลขสัญญา → ตัวชี้วัดที่ใช้วันที่ (เช่น F1)
  คำนวณได้เฉพาะท่าช้างกับโยนก ผลจะถูก mark `computable = 0` ไม่ใช่ triggered
- ไฟล์ต้นฉบับ 2 ไฟล์ถูกตัดท้าย (ท่าช้าง66, โยนก66) — flag ไว้ใน `data_quality_note`
- `fraud_risk_flag` ว่าง ≠ FALSE (ยังไม่เคย label)
- `winner_tin` บางแถวถูกปกปิด (`xxxx`) → จับคู่ vendor ซ้ำให้ใช้ `winner_name` ประกอบ

รายละเอียดทั้งหมดอยู่ใน `_schema_dictionary.md`

---

## 9. งานที่ยังต้องทำต่อ (สำหรับ dev ใหม่)

- `/audit/feedback`: filter สถานะ `draft` ให้เห็นเฉพาะเจ้าของ และเพิ่ม scope guard ให้
  `GET /audit/feedback/{project_id}` (ตอนนี้ยังไม่กรองตำบล — ดู `src/routers/audit.py`,
  issue backend #30) `audit.py` ยังไม่มี service layer เลย (SQL ตรงในราวเตอร์ทั้งไฟล์)
  ควร extract ตาม pattern ของ `services/projects.py`/`services/legal.py` ไปพร้อมกัน
- `JWT_SECRET` default (`dev-only-insecure-secret-change-before-production`) แค่ warn ตอน
  startup ไม่ fail-fast — ถ้าลืมตั้ง env var ตอน deploy production จะรันต่อได้ปกติ (issue #31)
- ต่อ OCR จริงเข้าชั้นเอกสาร (ตอนนี้ `project_documents`/`document_findings` เป็น `source='mock'`
  ทั้งหมด) — ก่อนให้ finding จาก OCR/LLM ขยับ risk score ต้องเพิ่ม review gate ให้คนยืนยันก่อน
- curate mapping กฎหมายของ A2/A3 (ตอนนี้ยังไม่มี → chatbot ตอบ "ยังไม่มีการเชื่อมโยงข้อกฎหมาย")
- `POST /chatbot` ยังไม่มี rate limit ต่อ user — เสี่ยง cost บานถ้ามีคนยิงรัว (issue #32)
- PDPA/privacy workflow: vendor/project personal-data inventory and public project-detail masking
  are documented/implemented (`docs/PDPA_DATA_INVENTORY.md`, `src/privacy.py`); privacy notice
  and data-subject request process remain backlog items (issue #28).
- log retention policy (archive/delete ตามอายุ `access_log`) ยังไม่มีโค้ด/migration ใดๆ ในนี้เลย
  (backlog, issue #28)
- RAG: ต่อครบแล้ว (ingest → retrieval → endpoint → tool ตัวที่ 6 → citations + เทสต์) เหลือ
  **calibrate `RAG_MIN_SCORE`** ด้วย `python -m scripts.calibrate_rag` แล้วตั้งค่าใน `.env`
  (ค่า 0.82 ที่ใช้อยู่ยังเป็นค่าเดา) และตั้ง env บน Vercel — ดู `docs/rag_pinecone_plan.md` §0.1
- RAG: ยังไม่มีขั้นตอนลบ record ส่วนเกินบน Pinecone ถ้า ingest รอบใหม่ได้ chunk น้อยลงกว่ารอบก่อน
  (เอกสารชุด demo คงที่จึงยังไม่กระทบ)
