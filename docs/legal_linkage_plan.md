# แผนฟีเจอร์ Legal Linkage (นำร่องด้วยโครงการก่อสร้าง)

> ตอบ 2 คำถามหลัก: (1) ต้องแก้ risk factor เดิมไหม → **ไม่ต้องแก้ logic เดิมเลย** (2) จัด data modeling ยังไงให้กระทบ app layer น้อยสุด → **เพิ่มเป็น "ชั้น mapping" ใหม่ผูกกับ `factor_code` ไม่แตะตาราง/endpoint เดิม**
>
> **อัปเดต 2026-07-24 ตามผลรีวิว** (`legal_linkage_plan_review.md`): mock อยู่ตำบลโยนก, exclude MOCK จาก A3, นิยาม L1 computable ชัดเจน, regression criteria แคบลง, เพิ่ม `computable` ใน payload, v1 ยังไม่มี OCR (findings เป็น mock/manual เท่านั้น), chatbot orchestration นอก scope แผนนี้
>
> **อัปเดต 2026-07-24 (รอบ 2)**: แก้ §2 ให้ตรงกับ §7 (ตัด `has_pr4/5/6`), กำหนด weight L1/L2/L3 = 1 เท่ากันไปก่อน, โครงการ `project_type IS NULL` ให้ gate skip ตามเดิม (มี 1 โครงการจริง — จงใจ skip), v1 coverage กฎหมายเน้นเดโม mock 2 โครงการ — factor ที่ยังไม่ map chatbot ต้องตอบว่า "ยังไม่มีการเชื่อมโยงข้อกฎหมาย"

---

## 1. Mapping ข้อบ่งชี้ในไฟล์ case ↔ risk factor

| ข้อบ่งชี้จาก case | Factor | ต้องทำอะไร |
| :---- | :---- | :---- |
| เสนอราคาต่างจากราคากลางเกิน 15% | **A1 (เดิม)** — สูตรตรงกัน ไม่แก้ | ผูก action suggestion ("แจ้งรายละเอียด ปร. ให้ สตง.") — case นี้ไม่มีกฎหมายอ้างอิง |
| ข้อเสนอโครงการไม่เกิน 500,000 | **D1 (เดิม)** — band 450,000–499,999 ครอบพฤติกรรมเสี่ยงจริงอยู่แล้ว **อย่าขยายเป็น ≤500,000** ไม่งั้นโครงการเล็กปกติ trigger หมด กลายเป็น noise | ผูกกฎหมาย 3 ฉบับ: พรบ.วินัยการเงินการคลัง 2561 ม.67, พรบ.จัดซื้อจัดจ้างฯ 2560 ม.25, พรบ.ว่าด้วยความผิดเกี่ยวกับการเสนอราคาต่อหน่วยงานของรัฐ 2542 (พรบ.ฮั้ว) |
| ขาดเอกสาร ปร.4/ปร.5/ปร.6 | **L1 (ใหม่)** เฉพาะก่อสร้าง | ต้องมีข้อมูลใหม่ (checklist เอกสาร) + ผูกประกาศคณะกรรมการราคากลางฯ ข้อ 20 |
| พื้นที่นอกกรอบอำนาจหน้าที่ | **L2 (ใหม่)** เฉพาะก่อสร้าง | ต้องมีข้อมูลใหม่ (in_jurisdiction) + ผูก พรบ.วินัยการเงินการคลัง ม.65, พรบ.ป่าไม้/ป่าสงวนแห่งชาติ |

สรุป: **A1–F1 คงเดิม 100%** — legal linkage เป็น metadata ที่ "แขวน" กับ factor_code ส่วนข้อบ่งชี้ใหม่เพิ่มเป็น factor L1/L2 ที่ gate ด้วย `project_type = 'จ้างก่อสร้าง'`

---

## 2. Data Model (ตารางใหม่ 4 + คอลัมน์ใหม่ 2)

หลักการ: mapping กฎหมายทำที่ **ระดับ factor** ไม่ใช่ระดับผลรัน → `project_risk_results` / `project_risk_scores` / `projects` ไม่ถูกแตะ

```sql
-- กฎหมายแม่ (1 พรบ./ประกาศ = 1 แถว)
CREATE TABLE laws (
    law_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    law_code    TEXT UNIQUE,          -- เช่น 'FDA2561', 'PPA2560', 'BID1999', 'RP-ANNOUNCE', 'FOREST'
    law_name_th TEXT NOT NULL,
    law_type    TEXT CHECK (law_type IN ('พรบ.','ประกาศ','ระเบียบ','กฎกระทรวง')),
    year_be     INTEGER,
    source_file TEXT                  -- ชี้ไฟล์ พรบ. ต้นฉบับที่แนบเข้ามา
);

-- มาตรา/ข้อ (1 พรบ. มีหลายมาตรา — เก็บเฉพาะมาตราที่ curate แล้ว)
CREATE TABLE law_sections (
    section_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    law_id          INTEGER NOT NULL REFERENCES laws(law_id),
    section_no      TEXT NOT NULL,    -- 'มาตรา 67', 'ข้อ 20'
    section_title   TEXT,
    section_summary TEXT NOT NULL,    -- สรุปสั้นให้ chatbot ใช้ตอบ
    section_text    TEXT,             -- ตัวบทเต็ม (NULL ได้ใน v1)
    UNIQUE(law_id, section_no)
);

-- ตัวเชื่อม factor ↔ มาตรา (many-to-many) + เหตุผล
CREATE TABLE factor_legal_map (
    map_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_code TEXT NOT NULL REFERENCES risk_factors(factor_code),
    section_id  INTEGER NOT NULL REFERENCES law_sections(section_id),
    reason_text TEXT NOT NULL,        -- "ทำไมข้อบ่งชี้นี้เข้าข่ายมาตรานี้"
    UNIQUE(factor_code, section_id)
);

-- ข้อมูล compliance รายโครงการ (สำหรับ L2 — ไม่ ALTER projects)
-- หมายเหตุ: เวอร์ชันแรกมี has_pr4/5/6 แต่ถูกตัดออกแล้วตาม §7 —
-- ข้อมูลเอกสาร (L1) derive จาก project_documents (Part 2) ที่เดียว
CREATE TABLE project_compliance (
    project_id      TEXT PRIMARY KEY REFERENCES projects(project_id),
    in_jurisdiction INTEGER,          -- 0/1/NULL (NULL = ไม่ทราบ → computable=0)
    note            TEXT
);
```

คอลัมน์ใหม่ใน `risk_factors` (DB สร้างใหม่จาก seed ได้ ไม่ต้อง migrate):

- `applies_to_project_type TEXT NULL` — NULL = ทุกประเภท (A1–F1, Y1–Y3 เป็น NULL → พฤติกรรมเดิมเป๊ะ), L1/L2 = `'จ้างก่อสร้าง'`
- `action_suggestion TEXT NULL` — ข้อเสนอแนะรายข้อบ่งชี้ตามตาราง case

**weight ของ L1/L2 (และ L3 ถ้าทำ): ตั้ง `weight = 1` เท่ากันไปก่อน** — ยังไม่มีหลักฐานเชิงประจักษ์ให้ถ่วงน้ำหนักต่างกัน ปรับทีหลังได้ที่ `risk_factors` โดยไม่แตะโค้ด

**Edge case `project_type IS NULL`**: มีโครงการจริง 1 แถว (`66099599752` ขุดลอกหนอง — เนื้องานเชิงก่อสร้างแต่ type เป็น NULL) → gate ของ L1/L2 **skip ตามเกณฑ์ปกติ (จงใจ)** ไม่ทำ special case; ถ้าอนาคตแก้ `project_type` ที่ต้นทาง โครงการนี้จะเข้า L1/L2 เองโดยไม่ต้องแก้ engine

### ทำไมกระทบ app layer น้อยสุด

- ไม่แก้ schema ตารางเดิมสักตาราง ไม่แก้ query ใน endpoint เดิมสักตัว
- L1/L2 ใช้ pattern `computable = 0` ที่ engine มีอยู่แล้ว (แบบ F1 ของปิงโค้ง) → โครงการจริง 96 โครงการไม่มีข้อมูล compliance → computable=0 ไม่ใช่ triggered=0 → **risk score เดิมไม่เพี้ยน**
- ฝั่ง API เพิ่มไฟล์เดียว: `src/routers/legal.py`

---

## 3. Engine (แก้เฉพาะ `seed_database.py` ตาม convention)

1. Seed `laws` / `law_sections` / `factor_legal_map` จากไฟล์ curate ใหม่ `legal_refs/` (laws.csv, law_sections.csv, factor_legal_map.csv) — **v1 เก็บเฉพาะมาตราที่ใช้ + summary** ไม่ยัด full text พรบ.ทั้งฉบับ (อันนั้นเป็นงาน Document Intelligence/RAG phase ถัดไป)
2. เพิ่ม evaluator ใน `run_project_engine`:
   - gate: `applies_to_project_type` ไม่ตรง → **ไม่เขียนแถวผล** (skip ไปเลย สะอาดกว่านับเป็น not-computable)
   - **L1**: ดูนิยาม computable ใน §7 (แหล่งข้อมูล = `project_documents` ตาม Part 2); severity `medium`
   - **L2**: computable เมื่อ `in_jurisdiction IS NOT NULL`; triggered เมื่อ `= 0`; severity `high`
   - **กัน mock ปนเปื้อน A3**: การนับ `group_hits` ของ A3 ต้อง **exclude `project_id LIKE 'MOCK-%'`** — A3 ใช้ fallback key "ตำบล:ชื่อตำบล" เมื่อ `dept_name` ว่าง (โครงการจริง 31 แถวไม่มี dept_name) ถ้าไม่ exclude mock ที่ราคากลางชนงบอาจเพิ่ม count จนพลิก A3 ของโครงการจริง
3. Seed mock 2 โครงการก่อสร้าง (ข้อ 4) + แถว `project_compliance` ของมัน

## 4. Mock โครงการ (ครบทั้ง 4 ข้อบ่งชี้ใน 2 โครงการ)

| | MOCK-CON-001 | MOCK-CON-002 |
| :---- | :---- | :---- |
| ชื่อ | ก่อสร้างถนน คสล. สายตัวอย่าง | ก่อสร้างรางระบายน้ำ คสล. |
| ตำบล | **โยนก (subdistrict_id=3)** | **โยนก (subdistrict_id=3)** |
| วิธี | e-bidding | เฉพาะเจาะจง |
| ตัวเลข | ref 5,200,000 / contract 4,100,000 (ลด ~21%) | budget 498,000 |
| compliance | ขาด ปร.4/5/6, in_jurisdiction=1 | เอกสารครบ, in_jurisdiction=0 (พื้นที่ป่าสงวน) |
| trigger | **A1 + L1** | **D1 + L2** |

การอยู่ร่วมกับข้อมูลจริงในตำบลโยนก:

- `project_id` ขึ้นต้น `MOCK-`, `source_file='mock_legal_linkage.csv'`, `data_quality_note='MOCK สำหรับเดโม legal linkage'` → กรองออกทีหลังได้ด้วย query เดียว
- ตั้ง `dept_name='กองช่าง (เดโม)'` ให้ต่างจากหน่วยงานจริง — กันชนกลุ่ม A3 อีกชั้นนอกเหนือจาก exclude ใน engine (§3)
- **trade-off ที่ยอมรับ**: mock 2 โครงการจะโผล่ใน dashboard/summary ของโยนก (`/projects`, `/risk/summary`) เพราะ endpoint เดิมไม่กรอง mock — ยอมรับได้ในระดับ prototype แต่ frontend ควรแสดง badge "MOCK" จาก `data_quality_note` ให้ผู้ใช้แยกออกตามข้อกำหนด Mission §6.1

## 5. API + Chatbot flow

Endpoint ใหม่ (ผ่าน `scope_subdistrict_ids` + `require_roles` ตามมาตรฐานเดิม):

- `GET /legal/laws` — รายการกฎหมาย+มาตราทั้งหมด
- `GET /risk/projects/{project_id}/legal` — payload เดียวจบสำหรับ chatbot:

```json
[{
  "factor_code": "D1", "factor_name": "...", "triggered": 1, "computable": 1,
  "evidence_text": "...",
  "action_suggestion": "ตรวจสอบว่าไม่มีการแยกโครงการ...",
  "legal_refs": [
    {"law": "พรบ.จัดซื้อจัดจ้างฯ 2560", "section_no": "มาตรา 25",
     "summary": "ห้ามแบ่งซื้อแบ่งจ้างโดยเจตนา...", "reason": "วงเงินหวุดหวิดใต้เพดาน..."}
  ]
}]
```

**ต้องมี `computable` ใน payload** — Mission Feature 4 บังคับให้ chatbot "ระบุความไม่แน่ใจถ้าข้อมูลไม่พอ" ถ้าไม่มีฟิลด์นี้ chatbot แยกไม่ออกระหว่าง "ไม่เสี่ยง" (`triggered=0, computable=1`) กับ "ไม่มีข้อมูลให้ประเมิน" (`computable=0` — evidence_text บอกเหตุผล เช่น "ไม่มีข้อมูล compliance") ซึ่งต้องตอบต่างกัน

Chatbot: case 1 (สรุปโครงการ) → `GET /projects/{id}` เดิม ไม่แตะ | case 2 (ความเสี่ยง) → endpoint ใหม่; โครงการประเภทอื่น `legal_refs` คืน list ว่าง → chatbot ใช้ endpoint เดียว ไม่ต้องแยก logic ตามประเภท

**ขอบเขต coverage กฎหมาย v1 + การ handle `legal_refs` ว่าง**: v1 curate mapping เฉพาะที่ใช้เดโม mock 2 โครงการ (D1, L1, L2 + findings) — ข้อมูลจริง trigger A2 75/96 และ A3 65/96 โครงการซึ่ง**ยังไม่มี** mapping ดังนั้น chatbot ต้องมีกติกาตายตัว: factor ที่ `triggered=1` แต่ `legal_refs=[]` ให้ตอบว่า *"ข้อบ่งชี้นี้ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ (อยู่ระหว่างจัดทำ)"* — ห้ามให้ LLM เดา/แต่งมาตราเอง; การ curate A2 (พรบ.ฮั้ว 2542) และ A3 (หลักเกณฑ์ราคากลางฯ) เป็นงาน phase ถัดไป

## 6. ลำดับงาน + Definition of Done

1. Curate `legal_refs/` 3 ไฟล์จาก พรบ. ที่แนบมา (งาน content ~ครึ่งวัน ทำก่อนได้เลย)
2. `seed_database.py`: ตารางใหม่ + 2 คอลัมน์ + seed + evaluator L1/L2 + mock → `python seed_database.py --force`
3. อัปเดต `data_model_design.md`, ERD, `_schema_dictionary.md`, `Risk Factor Design ระดับโครงการ.md` (เพิ่ม L1/L2)
4. `src/routers/legal.py` + `include_router` ใน `main.py` + เทสต์ใน `tests/`
5. **Regression check** (เทียบเฉพาะคอลัมน์ที่ต้องนิ่ง): dump `project_risk_scores` ของโครงการจริงก่อน/หลัง seed ใหม่ — `risk_score`, `risk_level`, `factors_triggered` ต้องเท่าเดิมทุก project_id
   ⚠️ `factors_not_computable` และ `summary_text` **จะเปลี่ยนโดยตั้งใจ**: โครงการก่อสร้างจริง 60 แถวได้ L1/L2 เป็น computable=0 → n_nc +2 และ summary ต่อท้าย "(ประเมินไม่ได้ n factor)" — ใช้เป็น sanity check แทน: assert ว่า n_nc ของโครงการก่อสร้างจริงเพิ่มขึ้นเท่าจำนวน L-factor พอดี และโครงการประเภทอื่นไม่เปลี่ยนเลย + `pytest -q` ผ่าน

---
---

# Part 2 — ชั้นเอกสาร (Document Intelligence สำหรับ ปร.4/ปร.5/ปร.6)

> รองรับคำถาม chatbot: "ใช้งบเท่าไร" / "เอกสารใดระบุราคากลาง" / "เสี่ยงด้านใด" / "ข้อกฎหมายที่เกี่ยวข้อง" / "เอกสารใดยังขาด"
> หลักการเดียวกับ Part 1: เพิ่มเป็นชั้นใหม่ ตารางเดิม/endpoint เดิมไม่ถูกแตะ และ **reuse ชั้นกฎหมาย (`laws`/`law_sections`) เป็น source เดียว** ทั้ง factor และ finding

## 7. การแก้ไขจาก Part 1 (สำคัญ)

- **L1 เปลี่ยนแหล่งข้อมูล**: ไม่ใช้ boolean `has_pr4/5/6` — `project_compliance` เหลือ `in_jurisdiction` สำหรับ L2 (SQL ใน §2 อัปเดตแล้ว) และให้ L1 derive จากตาราง `project_documents` แทน — ข้อมูลเอกสารจึงมีที่เก็บที่เดียว
- **นิยาม L1 (final)**:
  - `computable = 1` ⇔ **ทุก** required doc_type ของโครงการ (ตาม `document_types.required_for_project_type`) มีแถวใน `project_documents` แบบ explicit (status ใดก็ได้: present/missing/pending_review)
  - โครงการที่**ไม่มีแถวเลย** = ไม่เคยเก็บข้อมูลเอกสาร → `computable = 0` (ห้ามตีความว่า "ขาดเอกสาร" — หลักเดียวกับ `fraud_risk_flag` ว่าง ≠ FALSE) → โครงการก่อสร้างจริงทั้งหมดเข้าเคสนี้ risk score เดิมไม่เพี้ยน
  - `triggered = 1` ⇔ computable และมี required doc อย่างน้อย 1 แถวที่ `status='missing'`
  - ดังนั้น MOCK-CON-002 ต้อง seed แถว ปร.4/5/6 ด้วย `status='missing'` ตรงๆ ไม่ใช่ปล่อยไม่มีแถว
- **สลับ scenario mock**: เอกสาร ปร. ที่ mock ไว้ (มีข้อผิดพลาดฝัง 3 จุด) เป็นของโครงการถนน คสล. → MOCK-CON-001 ต้อง "มีเอกสารครบแต่เนื้อหามีพิรุธ" ส่วน MOCK-CON-002 เป็นตัว "ขาดเอกสาร" (L1)
- `laws.law_type` เพิ่มค่า `'หลักเกณฑ์'` ใน CHECK (รองรับหลักเกณฑ์การคำนวณราคากลางฯ กรมบัญชีกลาง)

## 8. ตารางใหม่ 4 ตาราง (+1 เผื่ออนาคต)

```sql
-- ประเภทเอกสาร (reference) — ขับทั้ง L1 และคำถาม "เอกสารใดระบุ X"
CREATE TABLE document_types (
    doc_type_code TEXT PRIMARY KEY,      -- 'PR4','PR5','PR6','ANNOUNCE','CONTRACT',...
    name_th       TEXT NOT NULL,         -- 'ปร.4 แบบแสดงรายการปริมาณงานและราคา (BOQ)'
    description   TEXT,
    required_for_project_type TEXT,      -- 'จ้างก่อสร้าง' → ใช้คำนวณ "เอกสารที่ขาด" + L1
    provides_json TEXT DEFAULT '[]'      -- สิ่งที่เอกสารระบุ เช่น PR5/PR6 → ["ราคากลาง","Factor F"]
);

-- เอกสารรายโครงการ (mock ตอนนี้ / OCR ภายหลัง — โครงเดียวกัน)
CREATE TABLE project_documents (
    doc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    doc_type_code TEXT NOT NULL REFERENCES document_types(doc_type_code),
    status        TEXT NOT NULL CHECK (status IN ('present','missing','pending_review')),
    doc_no        TEXT, doc_date TEXT,
    summary_text  TEXT,                  -- สรุปเนื้อหาเอกสาร (mock summary ที่เตรียมไว้)
    extracted_json TEXT DEFAULT '{}',    -- ค่าที่สกัดเชิงโครงสร้าง เช่น {"ราคากลาง": 5200000, "factor_f": 1.3061, "qty_road_sqm": 1850}
    file_path     TEXT,                  -- path ไฟล์ mock/สแกน (traceability แบบ ocr_pipeline)
    source        TEXT NOT NULL CHECK (source IN ('mock','ocr','manual')),
    UNIQUE(project_id, doc_type_code)
);

-- ข้อสังเกต/ข้อผิดพลาดที่พบในเอกสาร — ตารางข้อผิดพลาดที่ตั้งใจฝังไว้ map ลงตรงนี้ตรงๆ
CREATE TABLE document_findings (
    finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        INTEGER NOT NULL REFERENCES project_documents(doc_id),
    finding_text  TEXT NOT NULL,         -- ลักษณะข้อผิดพลาด
    risk_category TEXT NOT NULL,         -- 'ปริมาณงาน/ราคากลางเกินจริง', 'การคำนวณราคากลางคลาดเคลื่อน', 'เอกสารไม่ครบถ้วน/ตรวจสอบย้อนกลับไม่ได้'
    observed_value TEXT, expected_value TEXT,  -- '1,850 ตร.ม.' vs '1,600 ตร.ม.'
    severity      TEXT DEFAULT 'medium' CHECK (severity IN ('low','medium','high')),
    source        TEXT NOT NULL CHECK (source IN ('mock','ocr','llm','manual'))
);

-- finding ↔ มาตรา (reuse law_sections เดียวกับ factor_legal_map — finding หนึ่งอ้างได้หลายมาตรา)
CREATE TABLE finding_legal_map (
    finding_id  INTEGER NOT NULL REFERENCES document_findings(finding_id),
    section_id  INTEGER NOT NULL REFERENCES law_sections(section_id),
    reason_text TEXT,
    PRIMARY KEY (finding_id, section_id)
);

-- เผื่อ RAG/embedding ภายหลัง — v1 ใส่ summary เป็น 1 chunk, embedding เว้น NULL
CREATE TABLE document_chunks (
    chunk_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id    INTEGER NOT NULL REFERENCES project_documents(doc_id),
    chunk_no  INTEGER NOT NULL, page_no INTEGER,
    content_text TEXT NOT NULL,
    embedding BLOB                       -- NULL จนกว่าจะทำ embedding จริง
);
```

เหตุผลที่ v1 ไม่ต้อง embed: คำถามเดโมทั้ง 5 ข้อตอบได้จาก structured data ทั้งหมด (ดู §11) — mock summary + findings ที่เตรียมไว้เพียงพอ และเมื่อ OCR/LLM จริงมา ก็เขียนลงตารางเดิมด้วย `source='ocr'` โดยไม่แก้ schema (แนวเดียวกับหลัก traceability/review-gate ของ ocr_pipeline v2)

**ขอบเขต v1 (ยังไม่มี OCR จริง)**: seed ใช้ `source='mock'` เท่านั้น ค่า `'ocr'`/`'llm'` ใน CHECK เป็นการเผื่อ schema ไว้ — **เมื่อไรที่เริ่มเขียน findings จาก OCR/LLM จริง ต้องเพิ่ม review gate ก่อน** (เช่นคอลัมน์ `review_status` ให้ L3 นับเฉพาะที่ผู้ตรวจสอบ confirm) เพื่อไม่ให้ finding ที่ AI สร้างขยับ risk score โดยไม่ผ่านคน (Mission §9)

## 9. Seed ข้อผิดพลาดที่ฝังไว้ 3 จุด → `document_findings`

ทั้ง 3 แถวผูกกับเอกสารของ **MOCK-CON-001** (ถนน คสล.):

| doc | finding (ย่อ) | observed / expected | มาตราที่ผูก (เพิ่มใน `law_sections`) | risk_category |
| :---- | :---- | :---- | :---- | :---- |
| ปร.4 | ปริมาณผิวจราจร คสล. สูงกว่าแบบจริง ~15.6% | 1,850 / 1,600 ตร.ม. | พรบ.วินัยการเงินการคลัง 2561 **ม.6** | ปริมาณงาน/ราคากลางเกินจริง |
| ปร.5 | Factor F สูงกว่าเกณฑ์ช่วงมูลค่างาน ไม่มีตารางอ้างอิงแนบ | — | หลักเกณฑ์ราคากลางงานก่อสร้างฯ (กรมบัญชีกลาง) + ม.6 | การคำนวณราคากลางคลาดเคลื่อน |
| ปร.6 | ราคากลางที่ประกาศไม่ตรงผลคำนวณ ปร.4–ปร.5 ไม่มีบันทึกเหตุผลปรับแก้ | — | พรบ.วินัยการเงินการคลัง 2561 **หมวด 4** | เอกสารไม่ครบถ้วน/ตรวจสอบย้อนกลับไม่ได้ |

Seed จากไฟล์ curate ชุดใหม่ `mock_documents/`: `document_types.csv`, `project_documents.csv` (มี summary_text), `document_findings.csv`, `finding_legal_map.csv`

## 10. Mock scenario (ปรับจาก Part 1)

| | MOCK-CON-001 ถนน คสล. | MOCK-CON-002 รางระบายน้ำ |
| :---- | :---- | :---- |
| ตัวเลข | ref 5,200,000 / contract 4,100,000 (A1) | budget 498,000 เฉพาะเจาะจง (D1) |
| เอกสาร | **ครบ ปร.4/5/6 แต่มี findings 3 จุด** | **ขาด ปร.4/5/6 → L1** |
| เขตอำนาจ | in_jurisdiction = 1 | in_jurisdiction = 0 (ป่าสงวน) → L2 |
| เดโมคำถาม | "เอกสารใดระบุราคากลาง", "เสี่ยงด้านใด" (risk factor + doc findings), "ข้อกฎหมาย" | "เอกสารใดยังขาด", D1+L2 พร้อมกฎหมาย |

ทางเลือกเสริม (แนะนำ): เพิ่ม factor **L3 "เนื้อหาเอกสารราคากลางมีพิรุธ"** — triggered เมื่อโครงการมี `document_findings` ≥ 1 (computable เมื่อมีเอกสาร present) → risk score สะท้อนปัญหาเอกสารด้วย และคำตอบ "เสี่ยงด้านใด" ออกมาจากช่องทางเดียวกับ factor อื่น

## 11. คำถาม chatbot → แหล่งข้อมูล (ทุกข้อเป็น query ตรง ไม่ต้องใช้ vector)

| คำถาม | ตอบจาก |
| :---- | :---- |
| โครงการนี้ใช้งบประมาณเท่าไร | `projects` (endpoint เดิม) |
| เอกสารใดระบุราคากลาง | `document_types.provides_json` ∋ "ราคากลาง" join `project_documents` → "ปร.5, ปร.6 (มีในโครงการนี้/ขาด)" |
| โครงการนี้มีความเสี่ยงด้านใด | `project_risk_results` + `document_findings` (หรือรวมผ่าน L3) |
| ข้อกฎหมายที่เกี่ยวข้องคืออะไร | `factor_legal_map` + `finding_legal_map` → `law_sections` (source เดียว) |
| มีเอกสารใดที่ยังขาดอยู่ | `document_types.required_for_project_type` − `project_documents.status='present'` |

## 12. API เพิ่ม (router ใหม่ 1 ไฟล์ `src/routers/documents.py`)

- `GET /projects/{project_id}/documents` — เอกสารทั้งหมด + สถานะ + **missing list** + findings (พร้อม legal refs inline)
- `/risk/projects/{id}/legal` จาก Part 1 คงเดิม (ถ้าทำ L3 ผล findings จะโผล่ในนี้เองผ่าน factor)
- ผ่าน scope guard + `require_roles` ตามมาตรฐาน; endpoint เดิมทุกตัวไม่ถูกแตะ

## 13. ลำดับงานรวม (Part 1 + 2)

1. Curate `legal_refs/` (เพิ่มมาตรา: ม.6, หมวด 4, หลักเกณฑ์ราคากลางฯ) + `mock_documents/` 4 ไฟล์
2. `seed_database.py`: ตาราง Part 1 (4) + Part 2 (5) + evaluator L1 (จาก project_documents) / L2 / L3(optional) + seed mock 2 โครงการ + เอกสาร + findings
3. อัปเดต `data_model_design.md`, ERD, `_schema_dictionary.md`, Risk Factor Design (L1–L3)
4. Router `legal.py` + `documents.py` + เทสต์
5. Regression: `risk_score`/`risk_level`/`factors_triggered` ของโครงการจริง 96 โครงการต้องเท่าเดิมทุก project_id (รายละเอียด/ข้อยกเว้น n_nc ดู §6 ข้อ 5) + `pytest -q` ผ่าน
