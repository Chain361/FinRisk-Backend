# แผนฟีเจอร์ Legal Linkage + Document Intelligence (นำร่องด้วยโครงการก่อสร้าง)

> ตอบ 2 คำถามหลัก: (1) ต้องแก้ risk factor เดิมไหม → **ไม่ต้องแก้ logic เดิมเลย** (2) จัด data modeling ยังไงให้กระทบ app layer น้อยสุด → **เพิ่มเป็น "ชั้น mapping" ใหม่ผูกกับ `factor_code` ไม่แตะตาราง/endpoint เดิม**
>
> **อัปเดต 2026-07-25**: รวม Part 1 (ชั้นกฎหมาย) + Part 2 (ชั้นเอกสาร) เป็นแผนเดียว implement รอบเดียว — เดิมแยกตามลำดับการเขียนเอกสาร ไม่ใช่ phase การทำงานจริง
> การตัดสินใจสะสมจากรีวิว: mock อยู่ตำบลโยนก, exclude MOCK จาก A3, L1 derive จาก `project_documents` (ไม่ใช้ boolean), weight L1/L2/L3 = 1 เท่ากันไปก่อน, `project_type IS NULL` ให้ gate skip (จงใจ), v1 coverage กฎหมายเน้นเดโม mock 2 โครงการ — factor ที่ยังไม่ map chatbot ตอบ "ยังไม่มีการเชื่อมโยงข้อกฎหมาย", v1 ยังไม่มี OCR (findings เป็น mock/manual เท่านั้น), chatbot orchestration นอก scope แผนนี้

---

## 1. Mapping ข้อบ่งชี้ในไฟล์ case ↔ risk factor

| ข้อบ่งชี้จาก case | Factor | ต้องทำอะไร |
| :---- | :---- | :---- |
| เสนอราคาต่างจากราคากลางเกิน 15% | **A1 (เดิม)** — สูตรตรงกัน ไม่แก้ | ผูก action suggestion ("แจ้งรายละเอียด ปร. ให้ สตง.") — case นี้ไม่มีกฎหมายอ้างอิง |
| ข้อเสนอโครงการไม่เกิน 500,000 | **D1 (เดิม)** — band 450,000–499,999 ครอบพฤติกรรมเสี่ยงจริงอยู่แล้ว **อย่าขยายเป็น ≤500,000** ไม่งั้นโครงการเล็กปกติ trigger หมด กลายเป็น noise | ผูกกฎหมาย 3 ฉบับ: พรบ.วินัยการเงินการคลัง 2561 **ม.48**, **ระเบียบกระทรวงการคลังฯ 2560 ข้อ 20** (ตัวบทห้ามแบ่งซื้อแบ่งจ้างอยู่ในระเบียบ ไม่ใช่ พรบ.), พรบ.ว่าด้วยความผิดเกี่ยวกับการเสนอราคาต่อหน่วยงานของรัฐ **2542** (พรบ.ฮั้ว) **ม.11 + ม.12** |
| ขาดเอกสาร ปร.4/ปร.5/ปร.6 | **L1 (ใหม่)** เฉพาะก่อสร้าง | derive จาก `project_documents` (ดู §3) + ผูกประกาศคณะกรรมการราคากลางฯ ข้อ 20 |
| พื้นที่นอกกรอบอำนาจหน้าที่ | **L2 (ใหม่)** เฉพาะก่อสร้าง | ต้องมีข้อมูลใหม่ (`in_jurisdiction`) + ผูก **พรบ.ป่าไม้ 2484 + พรบ.ป่าสงวนแห่งชาติ 2507** (ไฟล์ case ไม่ระบุมาตรา → ใช้ `section_no='ทั้งฉบับ'`; **ไม่ใช้ ม.65** เพราะไม่มีในไฟล์ case) |
| เนื้อหาเอกสารราคากลางมีพิรุธ *(ทางเลือกเสริม แนะนำ)* | **L3 (ใหม่)** เฉพาะก่อสร้าง | triggered เมื่อโครงการมี `document_findings` ≥ 1 (computable เมื่อมีเอกสาร present) → risk score สะท้อนปัญหาเอกสาร และคำตอบ "เสี่ยงด้านใด" ออกช่องทางเดียวกับ factor อื่น |

สรุป: **A1–F1 คงเดิม 100%** — legal linkage เป็น metadata ที่ "แขวน" กับ factor_code ส่วนข้อบ่งชี้ใหม่เพิ่มเป็น factor L1–L3 ที่ gate ด้วย `project_type = 'จ้างก่อสร้าง'`

---

## 2. Data Model (ตารางใหม่ 9 + คอลัมน์ใหม่ 2)

หลักการ: mapping กฎหมายทำที่ **ระดับ factor** ไม่ใช่ระดับผลรัน และชั้นเอกสารเป็นตารางใหม่ทั้งหมด → `project_risk_results` / `project_risk_scores` / `projects` ไม่ถูกแตะ
**reuse ชั้นกฎหมาย (`laws`/`law_sections`) เป็น source เดียว** ทั้งฝั่ง factor (`factor_legal_map`) และฝั่ง finding (`finding_legal_map`)

### 2.1 ชั้นกฎหมาย (3 ตาราง)

```sql
-- กฎหมายแม่ (1 พรบ./ประกาศ = 1 แถว)
CREATE TABLE laws (
    law_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    law_code    TEXT UNIQUE,          -- 'FDA2561','MOF-REG2560','BID2542','RP-ANNOUNCE','FOREST2484','FOREST2507'
    law_name_th TEXT NOT NULL,
    law_type    TEXT CHECK (law_type IN ('พรบ.','ประกาศ','ระเบียบ','กฎกระทรวง','หลักเกณฑ์')),
    year_be     INTEGER,
    source_file TEXT                  -- ชี้ไฟล์ พรบ. ต้นฉบับที่แนบเข้ามา
);

-- มาตรา/ข้อ (1 พรบ. มีหลายมาตรา — เก็บเฉพาะมาตราที่ curate แล้ว)
CREATE TABLE law_sections (
    section_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    law_id          INTEGER NOT NULL REFERENCES laws(law_id),
    section_no      TEXT NOT NULL,    -- 'มาตรา 48', 'ข้อ 20', 'ทั้งฉบับ' (กรณี case ไม่ระบุมาตรา)
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
```

### 2.2 ชั้น compliance (1 ตาราง — สำหรับ L2)

```sql
-- ข้อมูลเขตอำนาจรายโครงการ (ไม่ ALTER projects)
-- ข้อมูลเอกสาร (L1) อยู่ที่ project_documents ที่เดียว — ไม่มี boolean has_pr4/5/6
CREATE TABLE project_compliance (
    project_id      TEXT PRIMARY KEY REFERENCES projects(project_id),
    in_jurisdiction INTEGER,          -- 0/1/NULL (NULL = ไม่ทราบ → computable=0)
    note            TEXT
);
```

### 2.3 ชั้นเอกสาร (5 ตาราง)

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

เหตุผลที่ v1 ไม่ต้อง embed: คำถามเดโมทั้ง 5 ข้อตอบได้จาก structured data ทั้งหมด (ดู §5.3) — mock summary + findings ที่เตรียมไว้เพียงพอ และเมื่อ OCR/LLM จริงมา ก็เขียนลงตารางเดิมด้วย `source='ocr'` โดยไม่แก้ schema (แนวเดียวกับหลัก traceability/review-gate ของ ocr_pipeline v2)

**ขอบเขต v1 (ยังไม่มี OCR จริง)**: seed ใช้ `source='mock'` เท่านั้น ค่า `'ocr'`/`'llm'` ใน CHECK เป็นการเผื่อ schema ไว้ — **เมื่อไรที่เริ่มเขียน findings จาก OCR/LLM จริง ต้องเพิ่ม review gate ก่อน** (เช่นคอลัมน์ `review_status` ให้ L3 นับเฉพาะที่ผู้ตรวจสอบ confirm) เพื่อไม่ให้ finding ที่ AI สร้างขยับ risk score โดยไม่ผ่านคน (Mission §9)

### 2.4 คอลัมน์ใหม่ใน `risk_factors` (DB สร้างใหม่จาก seed ได้ ไม่ต้อง migrate)

- `applies_to_project_type TEXT NULL` — NULL = ทุกประเภท (A1–F1, Y1–Y3 เป็น NULL → พฤติกรรมเดิมเป๊ะ), L1–L3 = `'จ้างก่อสร้าง'`
- `action_suggestion TEXT NULL` — ข้อเสนอแนะรายข้อบ่งชี้ตามตาราง case

**weight ของ L1/L2/L3: ตั้ง `weight = 1` เท่ากันไปก่อน** — ยังไม่มีหลักฐานเชิงประจักษ์ให้ถ่วงน้ำหนักต่างกัน ปรับทีหลังได้ที่ `risk_factors` โดยไม่แตะโค้ด

**Edge case `project_type IS NULL`**: มีโครงการจริง 1 แถว (`66099599752` ขุดลอกหนอง — เนื้องานเชิงก่อสร้างแต่ type เป็น NULL) → gate ของ L1–L3 **skip ตามเกณฑ์ปกติ (จงใจ)** ไม่ทำ special case; ถ้าอนาคตแก้ `project_type` ที่ต้นทาง โครงการนี้จะเข้า L-factor เองโดยไม่ต้องแก้ engine

### 2.5 ทำไมกระทบ app layer น้อยสุด

- ไม่แก้ schema ตารางเดิมสักตาราง ไม่แก้ query ใน endpoint เดิมสักตัว
- L1/L2 ใช้ pattern `computable = 0` ที่ engine มีอยู่แล้ว (แบบ F1 ของปิงโค้ง) → โครงการจริง 96 โครงการไม่มีข้อมูล compliance/เอกสาร → computable=0 ไม่ใช่ triggered=0 → **risk score เดิมไม่เพี้ยน**
- ฝั่ง API เพิ่ม 2 ไฟล์: `src/routers/legal.py` + `src/routers/documents.py`

---

## 3. Engine (แก้เฉพาะ `seed_database.py` ตาม convention)

1. Seed `laws` / `law_sections` / `factor_legal_map` จากไฟล์ curate ใหม่ `legal_refs/` (laws.csv, law_sections.csv, factor_legal_map.csv) และชั้นเอกสารจาก `mock_documents/` (document_types.csv, project_documents.csv มี summary_text, document_findings.csv, finding_legal_map.csv) — **v1 เก็บเฉพาะมาตราที่ใช้ + summary** ไม่ยัด full text พรบ.ทั้งฉบับ (อันนั้นเป็นงาน RAG phase ถัดไป)
2. เพิ่ม evaluator ใน `run_project_engine`:
   - gate: `applies_to_project_type` ไม่ตรง (รวมกรณี `project_type IS NULL`) → **ไม่เขียนแถวผล** (skip ไปเลย สะอาดกว่านับเป็น not-computable)
   - **L1 (นิยาม final — derive จาก `project_documents`)**:
     - `computable = 1` ⇔ **ทุก** required doc_type ของโครงการ (ตาม `document_types.required_for_project_type`) มีแถวใน `project_documents` แบบ explicit (status ใดก็ได้: present/missing/pending_review)
     - โครงการที่**ไม่มีแถวเลย** = ไม่เคยเก็บข้อมูลเอกสาร → `computable = 0` (ห้ามตีความว่า "ขาดเอกสาร" — หลักเดียวกับ `fraud_risk_flag` ว่าง ≠ FALSE) → โครงการก่อสร้างจริงทั้งหมดเข้าเคสนี้ risk score เดิมไม่เพี้ยน
     - `triggered = 1` ⇔ computable และมี required doc อย่างน้อย 1 แถวที่ `status='missing'`
     - ดังนั้น MOCK-CON-002 ต้อง seed แถว ปร.4/5/6 ด้วย `status='missing'` ตรงๆ ไม่ใช่ปล่อยไม่มีแถว
     - severity `medium`
   - **L2**: computable เมื่อ `in_jurisdiction IS NOT NULL`; triggered เมื่อ `= 0`; severity `high`
   - **L3 (ถ้าทำ)**: computable เมื่อมีเอกสาร `status='present'` ≥ 1; triggered เมื่อมี `document_findings` ≥ 1
   - **กัน mock ปนเปื้อน A3**: การนับ `group_hits` ของ A3 ต้อง **exclude `project_id LIKE 'MOCK-%'`** — A3 ใช้ fallback key "ตำบล:ชื่อตำบล" เมื่อ `dept_name` ว่าง (โครงการจริง 31 แถวไม่มี dept_name) ถ้าไม่ exclude mock ที่ราคากลางชนงบอาจเพิ่ม count จนพลิก A3 ของโครงการจริง
3. Seed mock 2 โครงการก่อสร้าง (§4) + แถว `project_compliance` + เอกสาร + findings ของมัน

---

## 4. Mock scenario (2 โครงการ ครบทุกข้อบ่งชี้)

| | MOCK-CON-001 **อาคารอเนกประสงค์** | MOCK-CON-002 รางระบายน้ำ คสล. |
| :---- | :---- | :---- |
| ตำบล | **โยนก (subdistrict_id=3)** | **โยนก (subdistrict_id=3)** |
| วิธี | e-bidding | เฉพาะเจาะจง |
| ตัวเลข | ref 5,200,000 / contract 4,100,000 (ลด ~21%) | budget 498,000 |
| เอกสาร | **ครบ ปร.4/5/6 แต่มี findings 3 จุด** | **ขาด ปร.4/5/6 (seed แถว status='missing') → L1** |
| เขตอำนาจ | in_jurisdiction = 1 | in_jurisdiction = 0 (พื้นที่ป่าสงวน) → L2 |
| trigger | **A1 + L3(ถ้าทำ)** | **D1 + L1 + L2** |
| เดโมคำถาม | "เอกสารใดระบุราคากลาง", "เสี่ยงด้านใด" (risk factor + doc findings), "ข้อกฎหมาย" | "เอกสารใดยังขาด", D1+L1+L2 พร้อมกฎหมาย |

### ข้อผิดพลาดที่ฝังไว้ 3 จุด → `document_findings` (ทั้งหมดผูกกับเอกสารของ MOCK-CON-001)

| doc | finding (ย่อ) | observed / expected | มาตราที่ผูก (เพิ่มใน `law_sections`) | risk_category |
| :---- | :---- | :---- | :---- | :---- |
| ปร.4 | ปริมาณงานพื้น คสล. สูงกว่าแบบก่อสร้างจริง ~15.6% | 1,850 / 1,600 ตร.ม. | พรบ.วินัยการเงินการคลัง 2561 **ม.6** | ปริมาณงาน/ราคากลางเกินจริง |
| ปร.5 | Factor F สูงกว่าเกณฑ์ช่วงมูลค่างาน ไม่มีตารางอ้างอิงแนบ | 1.3061 / — | พรบ.วินัยการเงินการคลัง 2561 **ม.6** | การคำนวณราคากลางคลาดเคลื่อน |
| ปร.6 | ราคากลางที่ประกาศไม่ตรงผลคำนวณ ปร.4–ปร.5 ไม่มีบันทึกเหตุผลปรับแก้ | — | พรบ.วินัยการเงินการคลัง 2561 **ม.68** | เอกสารไม่ครบถ้วน/ตรวจสอบย้อนกลับไม่ได้ |

> **หมายเหตุ**: ไฟล์ case ระบุ finding แถวที่ 3 ว่ามาจาก "ปร.5" (น่าจะพิมพ์ผิด เพราะซ้ำแถวบน) — seed ผูกไว้ที่ **ปร.6** ซึ่งเป็นแบบสรุปราคากลางที่นำไปประกาศจริง
> **ทำไม CON-001 เป็นงานอาคารไม่ใช่ถนน**: ประกาศฯ ข้อ 20 (1) กำหนดให้ **งานอาคาร** ใช้ ปร.4/ปร.5/ปร.6 ส่วน (2) งานทาง/สะพาน/ท่อเหลี่ยม ใช้แบบฟอร์มสรุปราคากลางงานทาง — ถ้า mock เป็นถนน การ trigger L1 ว่า "ขาด ปร.4/5/6" จะอ้างผิดแบบฟอร์ม

### การอยู่ร่วมกับข้อมูลจริงในตำบลโยนก

- `project_id` ขึ้นต้น `MOCK-`, `source_file='mock_legal_linkage.csv'`, `data_quality_note='MOCK สำหรับเดโม legal linkage'` → กรองออกทีหลังได้ด้วย query เดียว
- ตั้ง `dept_name='กองช่าง (เดโม)'` ให้ต่างจากหน่วยงานจริง — กันชนกลุ่ม A3 อีกชั้นนอกเหนือจาก exclude ใน engine (§3)
- **trade-off ที่ยอมรับ**: mock 2 โครงการจะโผล่ใน dashboard/summary ของโยนก (`/projects`, `/risk/summary`) เพราะ endpoint เดิมไม่กรอง mock — ยอมรับได้ในระดับ prototype แต่ frontend ควรแสดง badge "MOCK" จาก `data_quality_note` ให้ผู้ใช้แยกออกตามข้อกำหนด Mission §6.1

---

## 5. API + Chatbot

### 5.1 Endpoint ใหม่ (ทุกตัวผ่าน `scope_subdistrict_ids` + `require_roles` ตามมาตรฐานเดิม; endpoint เดิมไม่ถูกแตะ)

- `GET /legal/laws` — รายการกฎหมาย+มาตราทั้งหมด (`src/routers/legal.py`)
- `GET /risk/projects/{project_id}/legal` — payload เดียวจบสำหรับ chatbot (ถ้าทำ L3 ผล findings จะโผล่ในนี้เองผ่าน factor):

```json
[{
  "factor_code": "D1", "factor_name": "...", "triggered": 1, "computable": 1,
  "evidence_text": "...",
  "action_suggestion": "ตรวจสอบว่าไม่มีการแยกโครงการ...",
  "legal_refs": [
    {"law": "ระเบียบกระทรวงการคลังฯ 2560", "section_no": "ข้อ 20",
     "summary": "ห้ามแบ่งซื้อแบ่งจ้างโดยเจตนา...", "reason": "วงเงินหวุดหวิดใต้เพดาน..."}
  ]
}]
```

- `GET /projects/{project_id}/documents` — เอกสารทั้งหมด + สถานะ + **missing list** + findings (พร้อม legal refs inline) (`src/routers/documents.py`)

**ต้องมี `computable` ใน payload** — Mission Feature 4 บังคับให้ chatbot "ระบุความไม่แน่ใจถ้าข้อมูลไม่พอ" ถ้าไม่มีฟิลด์นี้ chatbot แยกไม่ออกระหว่าง "ไม่เสี่ยง" (`triggered=0, computable=1`) กับ "ไม่มีข้อมูลให้ประเมิน" (`computable=0` — evidence_text บอกเหตุผล เช่น "ไม่มีข้อมูล compliance") ซึ่งต้องตอบต่างกัน

> **Note (2026-07-25): service function เป็น contract หลัก** — ตรรกะ query + scope guard + payload (รวม `computable`) เขียนเป็น service function ที่เทสต์ได้ แล้ว expose 2 ทาง: (1) FastAPI router สำหรับ frontend/dashboard (2) agent tools สำหรับ chatbot multi-agent (LLM-as-judge / guardrail อยู่ชั้น orchestration เหนือ tools) — agent ไม่เขียน SQL เอง เพราะ access control ต้อง deterministic ไม่พึ่ง guardrail; รายละเอียดโครง multi-agent ค่อยลงทีหลัง แผนนี้ทำ data modeling ก่อน

### 5.2 กติกา chatbot

- case สรุปโครงการ → `GET /projects/{id}` เดิม ไม่แตะ | case ความเสี่ยง/กฎหมาย → endpoint ใหม่; โครงการประเภทอื่น `legal_refs` คืน list ว่าง → chatbot ใช้ endpoint เดียว ไม่ต้องแยก logic ตามประเภท
- **ขอบเขต coverage กฎหมาย v1 + การ handle `legal_refs` ว่าง**: v1 curate mapping เฉพาะที่ใช้เดโม mock 2 โครงการ (D1, L1, L2 + findings) — ข้อมูลจริง trigger A2 75/96 และ A3 65/96 โครงการซึ่ง**ยังไม่มี** mapping ดังนั้น chatbot ต้องมีกติกาตายตัว: factor ที่ `triggered=1` แต่ `legal_refs=[]` ให้ตอบว่า *"ข้อบ่งชี้นี้ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ (อยู่ระหว่างจัดทำ)"* — ห้ามให้ LLM เดา/แต่งมาตราเอง; การ curate A2 (พรบ.ฮั้ว 2542) และ A3 (หลักเกณฑ์ราคากลางฯ) เป็นงาน phase ถัดไป
- chatbot orchestration (ตัวแอป/LLM ที่เรียก API) อยู่นอก scope แผนนี้

### 5.3 คำถาม chatbot → แหล่งข้อมูล (ทุกข้อเป็น query ตรง ไม่ต้องใช้ vector)

| คำถาม | ตอบจาก |
| :---- | :---- |
| โครงการนี้ใช้งบประมาณเท่าไร | `projects` (endpoint เดิม) |
| เอกสารใดระบุราคากลาง | `document_types.provides_json` ∋ "ราคากลาง" join `project_documents` → "ปร.5, ปร.6 (มีในโครงการนี้/ขาด)" |
| โครงการนี้มีความเสี่ยงด้านใด | `project_risk_results` + `document_findings` (หรือรวมผ่าน L3) |
| ข้อกฎหมายที่เกี่ยวข้องคืออะไร | `factor_legal_map` + `finding_legal_map` → `law_sections` (source เดียว) |
| มีเอกสารใดที่ยังขาดอยู่ | `document_types.required_for_project_type` − `project_documents.status='present'` |

---

## 6. ลำดับงาน + Definition of Done

> **สถานะ (2026-07-25): ข้อ 1–5 เสร็จครบแล้ว**
>
> ข้อ 4 (router/service layer) — `src/services/{common,legal,documents}.py` เป็น contract หลัก
> (scope guard + payload อยู่ในนี้ที่เดียว agent tool เรียกซ้ำได้ ไม่ต้องเขียน SQL),
> router บาง 2 ไฟล์ `src/routers/legal.py` (`GET /legal/laws`, `GET /risk/projects/{id}/legal?only_triggered=`)
> + `src/routers/documents.py` (`GET /documents/types`, `GET /projects/{id}/documents`),
> เทสต์ใหม่ `tests/test_legal_documents.py` 14 เคส → `pytest -q` **28 passed**
> เพิ่มเติมจากแผน: ฟิลด์ `legal_ref_note` (ข้อความตายตัวเมื่อ `legal_refs=[]` — กัน LLM แต่งมาตรา),
> `provides_index` / `missing_doc_types[].reason` (`no_record` ≠ `missing`) สำหรับคำถามเดโม §5.3
>
> **รอบแก้ล่าสุด: sync citation ให้ตรงไฟล์ `สรุป case.md` (ไฟล์ case เป็น source of truth)** — เปลี่ยน ม.67→**ม.48**, พรบ.จัดซื้อจัดจ้างฯ ม.25 → **ระเบียบ กค. 2560 ข้อ 20** (`law_type='ระเบียบ'`), หมวด 4→**ม.68**, BID ม.4→**ม.11+ม.12** (`law_code` = `BID2542`), ตัด ม.65 และ `COST-CRIT` ทิ้ง, แยก **FOREST2484/FOREST2507** เป็น 2 แถว, เติม `section_text` ตัวบทเต็มจาก case ครบทุกมาตรา, เปลี่ยน MOCK-CON-001 เป็น**งานอาคาร**
> นับใหม่: laws=6, sections=9, **factor_map=8**, findings=3, **finding_map=3** (validation check ข้อ 11 อัปเดตแล้ว)
> regression ผ่าน: โครงการจริง 96 แถว score/level/triggered **diff = 0**, validation 13 ข้อ PASS, `pytest tests/ -q` 14 passed
>
> ⚠️ **AI ที่มา execute ต่อ: CSV ใน `legal_refs/` + `mock_documents/` คือของจริงที่ seed แล้ว อย่า regenerate จากตารางในเอกสารนี้** — ถ้าจะแก้ citation ให้แก้ CSV แล้วรัน seed ใหม่

1. Curate `legal_refs/` 3 ไฟล์จากไฟล์ `สรุป case.md` (มาตราที่ใช้จริง: **ม.6, ม.48, ม.68** ของ พรบ.วินัยการเงินการคลัง 2561, **ข้อ 20** ของระเบียบ กค. 2560, **ม.11 + ม.12** ของ พรบ.ฮั้ว 2542, **ข้อ 20** ของประกาศคณะกรรมการราคากลางฯ ฉบับที่ 5, และ **'ทั้งฉบับ'** ของ พรบ.ป่าไม้ 2484 / ป่าสงวนแห่งชาติ 2507) + `mock_documents/` 4 ไฟล์ — **ทำเสร็จแล้ว**
2. `seed_database.py`: ตารางใหม่ 9 + 2 คอลัมน์ + seed + evaluator L1/L2/L3(optional) + mock 2 โครงการ + เอกสาร + findings → `python seed_database.py --force`
3. อัปเดต `data_model_design.md`, ERD, `_schema_dictionary.md`, `Risk Factor Design ระดับโครงการ.md` (เพิ่ม L1–L3)
4. Router `legal.py` + `documents.py` + `include_router` ใน `main.py` + เทสต์ใน `tests/`
5. **Regression check** (เทียบเฉพาะคอลัมน์ที่ต้องนิ่ง): dump `project_risk_scores` ของโครงการจริง 96 โครงการก่อน/หลัง seed ใหม่ — `risk_score`, `risk_level`, `factors_triggered` ต้องเท่าเดิมทุก project_id
   ⚠️ `factors_not_computable` และ `summary_text` **จะเปลี่ยนโดยตั้งใจ**: โครงการก่อสร้างจริง 60 แถวได้ L-factor เป็น computable=0 → n_nc เพิ่มขึ้นเท่าจำนวน L-factor พอดี และ summary ต่อท้าย "(ประเมินไม่ได้ n factor)" — assert: n_nc ของโครงการก่อสร้างจริงเพิ่มเท่าจำนวน L-factor, โครงการประเภทอื่น (รวมแถว `project_type IS NULL`) ไม่เปลี่ยนเลย + `pytest -q` ผ่าน
