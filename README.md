# Local Budget Fraud Risk & Document Intelligence Assistant — Backend

ระบบช่วยประเมิน **ความเสี่ยงทุจริตงบประมาณ** ขององค์กรปกครองส่วนท้องถิ่น (เทศบาลตำบล)
จากข้อมูลจัดซื้อจัดจ้าง (e-GP) และงบการเงิน โดยรัน "risk engine" ให้คะแนนความเสี่ยง
รายโครงการและรายปีงบประมาณ แล้วเปิดให้ผู้ใช้แต่ละบทบาทเข้ามาตรวจสอบ/มอบหมายงานต่อ

> Repository นี้เป็น **backend** (Python + FastAPI + SQLite) — คู่มือนี้สำหรับ dev ที่เพิ่งเข้ามาทำงาน

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

ต้องมี **Python 3.10+**

```bash
# 1) (แนะนำ) สร้าง virtual env
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2) ติดตั้ง dependency ของ API
pip install -r requirements.txt

# 3) สร้างฐานข้อมูล + seed ข้อมูล + รัน risk engine ครั้งแรก
python seed_database.py            # ได้ไฟล์ fraud_risk.db

# 4) รัน API
uvicorn src.main:app --reload
```

เปิดเอกสาร API อัตโนมัติที่ **http://127.0.0.1:8000/docs**
ตรวจสุขภาพระบบที่ **http://127.0.0.1:8000/health**

> `seed_database.py` ใช้ **Python stdlib ล้วน** (ไม่ต้อง `pip install`) — ตัว API เท่านั้นที่ต้องใช้ `requirements.txt`

---

## 3. โครงสร้างโฟลเดอร์

```
data_modelling/
├─ src/                         # โค้ด backend (FastAPI)
│  ├─ main.py                   # entry point — รวม router + CORS + /health
│  ├─ config.py                 # path DB, CORS origin, ค่าคงที่
│  ├─ database.py               # ตัวช่วยต่อ SQLite (dependency get_db)
│  ├─ auth.py                   # mock login + role/scope guard
│  ├─ schemas.py                # Pydantic models
│  └─ routers/                  # endpoint แยกตามโดเมน
│     ├─ auth.py                # /auth/login, /auth/me
│     ├─ subdistricts.py        # /subdistricts
│     ├─ projects.py            # /projects (+ risk score ล่าสุด)
│     ├─ risk.py                # /risk/factors, /risk/annual, /risk/summary
│     └─ audit.py               # /audit/assignments, /audit/feedback
├─ tests/test_smoke.py          # smoke test (pytest)
├─ seed_database.py             # สร้าง DB + seed + รัน risk engine + validate
├─ fraud_risk.db                # SQLite (สร้างจาก seed — ไม่ commit ตาม .gitignore)
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

ฐานข้อมูล SQLite เดียว (`fraud_risk.db`) 15 ตาราง แบ่งเป็น 4 กลุ่ม:

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
| `auditor1` | project_auditor | เฉพาะตำบลของตัวเอง + มอบหมายงานตรวจสอบ |
| `analyst1` | risk_analyst | เฉพาะตำบลของตัวเอง + รับงานที่ได้รับมอบหมาย + ส่งรายงานผลตรวจ |
| `public1` | public_user | ทุกตำบล (read-only, **ไม่เห็นข้อมูลที่ถูกปิดไว้** เช่น `/audit/*`) |

การจำกัด scope อยู่ที่ `src/auth.py` → `scope_subdistrict_ids()` ทุก endpoint ที่คืนข้อมูลตำบล
ต้องเรียกใช้ฟังก์ชันนี้เสมอ

---

## 6. ทดลองยิง API

```bash
# login (mock) — ได้ token = username กลับมา
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password123"}'

# ทุก endpoint ที่ต้อง auth ให้แนบ header X-Username (mock)
curl http://127.0.0.1:8000/projects?risk_level=high -H "X-Username: admin"
curl http://127.0.0.1:8000/risk/summary            -H "X-Username: thachang_user"
curl http://127.0.0.1:8000/subdistricts            -H "X-Username: public1"   # ประชาชน: เห็นทุกตำบล
```

> ⚠️ **Auth เป็น mock** (token = username, sha256 ไม่มี salt) เหมาะกับ demo เท่านั้น
> ก่อนขึ้น production ต้องเปลี่ยนเป็น bcrypt/argon2 + JWT — ดู `CLAUDE.md`

---

## 7. เทสต์

```bash
pytest -q                # รัน smoke test (ต้องมี fraud_risk.db แล้ว)
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

- เติม business logic ของ `/audit/*` (สร้าง assignment, ส่ง audit_report) — ตอนนี้เป็นโครง read-only
- เปลี่ยน mock auth เป็น JWT + password hashing จริง
- เพิ่ม endpoint สำหรับ "รัน risk engine ใหม่" (ตอนนี้รันผ่าน `seed_database.py` เท่านั้น)
- ส่วน "Document Intelligence" (อ่านเอกสาร/OCR) ตามชื่อ Mission ยังไม่ได้เริ่ม
