# CLAUDE.md

แนวทางสำหรับ AI coding agent (และ dev) ที่ทำงานใน repo นี้ อ่านคู่กับ `README.md`

## ภาพรวม

Backend ของ **Local Budget Fraud Risk & Document Intelligence Assistant** —
ประเมินความเสี่ยงทุจริตงบประมาณของเทศบาลตำบล จากข้อมูลจัดซื้อจัดจ้าง + งบการเงิน
Stack: **Python 3.10+ / FastAPI / PostgreSQL (psycopg 3)** ไม่มี ORM

## คำสั่งที่ใช้บ่อย

```bash
createdb finrisk_dev                   # ครั้งแรกเท่านั้น (ต้องมี postgres รันอยู่)
pip install -r requirements.txt        # ติดตั้ง dependency ของ API (รวม psycopg)
python seed_database.py                # สร้าง schema + seed + risk engine + validate
python seed_database.py --force        # ลบตารางเดิมทั้งหมดแล้วสร้างใหม่
uvicorn src.main:app --reload          # รัน API dev server → /docs
pytest -q                              # smoke test
```

ตั้ง `DATABASE_URL` ถ้าไม่ใช้ default (`postgresql://localhost/finrisk_dev`) — ทั้ง API และ
`seed_database.py` อ่านค่าเดียวกันจาก `src/config.py`

## สถาปัตยกรรม

- `src/main.py` — สร้าง `app`, ผูก CORS, include router ทั้งหมด, `/health` + `/`
- `src/config.py` — `DATABASE_URL` (env, มี default local dev), CORS origin อ่านจาก env มี default
- `src/database.py` — `get_db()` เป็น FastAPI dependency คืน psycopg connection;
  `Connection`/`Cursor` แปลง `?` placeholder (สไตล์เดิมของทั้ง repo) เป็น `%s` ให้อัตโนมัติ;
  `SqliteLikeRow` เลียนแบบ `sqlite3.Row` (index ตัวเลข + key ชื่อคอลัมน์ + iterate เป็นค่า)
  เพื่อให้ query เดิมทั่ว repo ใช้ต่อได้โดยไม่ต้องแก้ทีละจุด; helper `rows_to_dicts()`
- `src/auth.py` — JWT login (bcrypt + PyJWT) + `get_current_user`, `require_roles(...)`, `scope_subdistrict_ids(...)`
- `src/schemas.py` — Pydantic model (request/response)
- `src/routers/*.py` — endpoint แยกตามโดเมน (auth, subdistricts, projects, risk, audit, admin)

**Data flow:** CSV (`standardized_data/`) → `seed_database.py` เขียนลง PostgreSQL (ตาม `DATABASE_URL`)
→ risk engine ใน seed คำนวณและเขียนตาราง `*_risk_results` / `project_risk_scores`
→ FastAPI ส่วนใหญ่ **อ่านอย่างเดียว** จาก DB ยกเว้น `src/routers/admin.py`
(`POST /admin/data/upload` นำเข้า CSV โครงการ/งบการเงินของตำบลที่มีอยู่แล้ว,
`POST /admin/risk-engine/run` สั่งคำนวณ risk score ใหม่) — ทั้งสอง endpoint เรียก
`seed_vendors`/`seed_projects`/`seed_financial`/`run_project_engine`/`run_annual_engine`
จาก `seed_database.py` ตรงๆ (import เป็น top-level module จาก repo root) **ห้ามก็อปโค้ด
มาเขียนซ้ำใน router** เพราะ logic ต้องอยู่ที่เดียวตามกติกาด้านล่าง

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
  จะมี warning log ตอน startup (`src/main.py`)
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

## สิ่งที่ยังไม่ทำ

- ส่วน "Document Intelligence" (OCR/อ่านเอกสาร) ตามชื่อ Mission
- deploy จริง (Vercel serverless) ยังต้องชี้ `DATABASE_URL` ไป managed Postgres ที่ persistent
  (เช่น Neon/Supabase/RDS) — ยังไม่ได้ provision
