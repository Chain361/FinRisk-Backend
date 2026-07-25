# Local Budget Fraud Risk & Document Intelligence Assistant — Backend

ระบบช่วยประเมิน **ความเสี่ยงทุจริตงบประมาณ** ขององค์กรปกครองส่วนท้องถิ่น (เทศบาลตำบล)
จากข้อมูลจัดซื้อจัดจ้าง (e-GP) และงบการเงิน โดยรัน "risk engine" ให้คะแนนความเสี่ยง
รายโครงการและรายปีงบประมาณ แล้วเปิดให้ผู้ใช้แต่ละบทบาทเข้ามาตรวจสอบ/มอบหมายงานต่อ

> Repository นี้เป็น **backend** (Python + FastAPI + PostgreSQL) — คู่มือนี้สำหรับ dev ที่เพิ่งเข้ามาทำงาน

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
│  └─ routers/                  # endpoint แยกตามโดเมน
│     ├─ auth.py                # /auth/login, /auth/me
│     ├─ subdistricts.py        # /subdistricts
│     ├─ projects.py            # /projects (+ risk score ล่าสุด)
│     ├─ risk.py                # /risk/factors, /risk/annual, /risk/summary
│     ├─ audit.py               # /audit/assignments, /audit/feedback
│     └─ admin.py               # /admin/data/upload, /admin/risk-engine/run (admin เท่านั้น)
├─ tests/test_smoke.py          # smoke test (pytest)
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

ฐานข้อมูล PostgreSQL เดียว (ตาม `DATABASE_URL`) 15+ ตาราง แบ่งเป็น 4 กลุ่ม:

**Master data** — `subdistricts` (3 ตำบล), `vendors` (57 ราย), `projects` (97 โครงการ),
`financial_statements` (337 บรรทัดงบการเงิน), `roles` (6 บทบาท ตาม `roles.md`), `users` (8 mock users)

**Risk engine config** — `risk_factors` (8 ตัวชี้วัด), `app_config` (เกณฑ์แบ่งระดับความเสี่ยง)

**Risk results** (เขียนโดย engine ทุก run) — `assessment_runs`, `project_risk_results`,
`project_risk_scores`, `annual_risk_results`

**Audit workflow** — `audit_assignments`, `audit_reports`, `auditor_feedback` (ยังว่าง รอ business logic)

ดู ERD เต็มได้ที่ `data_model_erd.mermaid` และคำอธิบายทุกตาราง/คอลัมน์ที่ `data_model_design.md`

### Risk factors (8 ตัว)

| Code | ระดับ | ชื่อ |
|---|---|---|
| A1 | project | ส่วนลดผิดปกติ |
| A2 | project | ส่วนลดน้อยผิดปกติ |
| A3 | project | ราคากลางชนงบพอดี |
| D1 | project | วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง |
| F1 | project | จัดจ้างกระจุกตัวท้ายปีงบ |
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
```

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

---

## 7. เทสต์

```bash
pytest -q                # รัน smoke test (ต้องมี postgres รันอยู่ + seed แล้ว)
```

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

- ส่วน "Document Intelligence" (อ่านเอกสาร/OCR) ตามชื่อ Mission ยังไม่ได้เริ่ม
- deploy จริง: ต้อง provision PostgreSQL แบบ persistent (เช่น Neon/Supabase/RDS) แล้วตั้ง
  `DATABASE_URL` บน Vercel — ยังไม่ได้ provision
