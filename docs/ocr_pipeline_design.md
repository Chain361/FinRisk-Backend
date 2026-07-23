# Design: PDF → `financial_statements` Pipeline v2 (chart-of-accounts–driven)

> สถานะ: **design only** — ยังไม่แตะโค้ด v1 (`pipeline/`)
> Input ที่ใช้ออกแบบ: `ท่าช้าง67.pdf` (สแกน 33 หน้า ไม่มี text layer),
> `ผังบัญชี.pdf` = ผังบัญชีมาตรฐาน e-LAAS (61 หน้า **มี text layer**, 1,018 รหัสบัญชี)
> อ่านคู่กับ: `pipeline/README.md` (v1), `data_model_design.md` §4.2/§9.4, `docs/ARCHITECTURE.md`
> สำหรับลงมือ implement: ใช้ `docs/ocr_pipeline_implementation_spec.md` (normative spec สำหรับ agent)

## 1. ทำไมต้อง v2 — ช่องว่างของ v1

v1 พิสูจน์แล้วว่าแนว *OCR อ่านตามที่พิมพ์ → normalize ด้วย rule/dict → validate สมการบัญชี →
evaluate กับ gold* ใช้ได้ (100% ทุก metric บน harness ท่าช้าง 2567) แต่ยังไม่พร้อมรับ
"PDF หลายตำบล format ไม่เหมือนกัน":

| จุดอ่อน v1 | ผลกระทบ | ทางแก้ v2 |
|---|---|---|
| `ACCOUNT_DICT` hardcode ~11 รายการในโค้ด | เจอชื่อรายการใหม่ต้องแก้โค้ด python | ย้ายเป็น reference data สร้างจาก **ผังบัญชี e-LAAS** (1,018 รหัส) + alias table |
| `SECTION_HEADERS` กำหนด `หมวดหมู่` จาก layout เอกสาร | format ต่างจากท่าช้าง → หมวดผิด/หาย | derive `statement_type`/`category`/`detail_level` จาก **รหัสบัญชี** — layout เป็นแค่ hint |
| ชื่อที่ไม่รู้จักหลุดออกเป็นชื่อดิบ | ข้อมูลสกปรกเข้า DB เงียบ ๆ | matching ladder + **unmatched ห้ามเข้า output** → review queue |
| evaluate วัด field-level กับ gold ตำบลเดียว ครั้งเดียว | ไม่รู้ว่าแก้ dict แล้วอะไรพัง / ผิดตรงไหน "สำคัญ" | evaluation 3 ชั้น + regression corpus (§5) |
| ไม่มี manifest/state ต่อไฟล์ | รันซ้ำ/หลายไฟล์จัดการมือ | Stage 0 ingest + manifest, idempotent ต่อ stage |

## 2. หลักการออกแบบ

1. Extraction อ่าน **"ตามที่พิมพ์"** เท่านั้น — ไม่ตีความ (คงจาก v1)
2. การตีความทั้งหมด deterministic + ตรวจสอบได้ + แก้ได้โดยไม่แตะ extractor (คงจาก v1)
3. **ผังบัญชี e-LAAS = source of truth เดียว** ของชื่อ canonical, หมวดหมู่, ประเภทงบ (ใหม่)
4. Validate เป็น **gate** — ไม่ผ่าน = human review, ห้าม auto-fix (คงจาก v1)
5. ทุกแถว traceable ถึงหน้า PDF (`source_file#pNN`) และถึง run/dictionary version (ขยายจาก v1)
6. Precision-first: ยอมส่งแถวยากไป review ดีกว่าปล่อยค่าผิดเข้า risk engine

## 3. Reference layer — สกัดผังบัญชีครั้งเดียว (แล้ว version ไว้)

### 3.1 `reference/chart_of_accounts.csv`

ผังบัญชี.pdf มี text layer → ใช้ pdfplumber + regex สกัดได้เลย **ไม่ต้อง OCR**
(ตรวจแล้ว: จับได้ 1,018 รหัส — หลัก 1: 252, หลัก 2: 124, หลัก 3: 20, หลัก 4: 320, หลัก 5: 302)

| คอลัมน์ | ที่มา |
|---|---|
| `account_code` | รหัส 10 หลัก + `.xxx` เช่น `1101010101.001` |
| `account_name`, `description` | ตามผัง |
| `level`, `parent_code` | นับจากตำแหน่ง trailing zeros ของรหัส |
| `statement_type` | **derive จากหลักแรก** (ตาราง 3.2) |
| `category` | **derive จาก 2 หลักแรก** (ตาราง 3.2) |
| `postable` | leaf node (มี `.xxx` ≠ `.000`) = บันทึกได้จริง → `detail_level='line_item'` |

### 3.2 Derivation จากโครงรหัส (นี่คือหัวใจที่ทำให้เลิกพึ่ง layout)

| prefix | ความหมายในผัง | `statement_type` | `category` (ชื่อตรง gold แล้ว) |
|---|---|---|---|
| `11` | สินทรัพย์หมุนเวียน | งบแสดงฐานะการเงิน | สินทรัพย์หมุนเวียน |
| `12` | สินทรัพย์ไม่หมุนเวียน | งบแสดงฐานะการเงิน | สินทรัพย์ไม่หมุนเวียน |
| `21` | หนี้สินหมุนเวียน | งบแสดงฐานะการเงิน | หนี้สินหมุนเวียน |
| `22` | หนี้สินไม่หมุนเวียน | งบแสดงฐานะการเงิน | หนี้สินไม่หมุนเวียน |
| `3x` | ส่วนทุน | งบแสดงฐานะการเงิน | สินทรัพย์สุทธิ_ส่วนทุน |
| `4x` | รายได้ | งบแสดงผลการดำเนินงาน | รายได้ |
| `5x` | ค่าใช้จ่าย | งบแสดงผลการดำเนินงาน | ค่าใช้จ่าย |

หมายเหตุ: ผังใช้คำ "ส่วนทุน" แต่งบพิมพ์ "สินทรัพย์สุทธิ/ส่วนทุน" → map เป็นค่าเดียว
`สินทรัพย์สุทธิ_ส่วนทุน` ตาม gold; ชื่องบ "งบแสดงผลการดำเนินงานทางการเงิน" → canonical
"งบแสดงผลการดำเนินงาน" (คง `STATEMENT_CANON` ของ v1)

### 3.3 `reference/account_aliases.csv`

ชื่อที่พิมพ์ในงบจริงมักไม่ตรงผังเป๊ะ (เว้นวรรค, "- สุทธิ", ตัดคำ) และแถว "รวม…" ไม่มีในผัง
(เป็นผลรวม ไม่ใช่บัญชี):

- columns: `alias_normalized`, `account_code`, `note`
- แถวยอดรวมให้ **pseudo-code** ผูกกลับผัง เช่น `รวมสินทรัพย์หมุนเวียน` → `TOTAL:1100000000`
  (กำหนด `detail_level` = subtotal/total จากตาราง pseudo-code นี้)
- seed เริ่มต้นจาก: `ACCOUNT_DICT` v1 + รายการบัญชีทั้งหมดใน gold 3 ตำบล
  (`financial_report_ALL_master.csv` 337 แถว) → เปิดตัวด้วย coverage 100% ของข้อมูลที่มี

### 3.4 Trim `statement_type` — ยึดผังบัญชีเป็นเกณฑ์

ผังบัญชีครอบคลุมเฉพาะบัญชีที่ประกอบ **2 งบหลัก** ดังนั้น:

- pipeline v2 ผลิตเฉพาะ `งบแสดงฐานะการเงิน` + `งบแสดงผลการดำเนินงาน` — ตรงกับที่ app
  และ annual engine (Y1–Y3) ใช้จริงอยู่แล้ว
- ประเภทอื่นที่ค้างใน DB (`งบประมาณตามหมวด` 29, `สินทรัพย์ถาวรเพิ่มระหว่างปี` 24,
  `ตัวชี้วัดความเสี่ยง` 20 แถว — มีเฉพาะปิงโค้ง จากไฟล์สรุป legacy) = **นอก scope pipeline**
  จะคงไว้ (ไม่มี consumer แต่ไม่ขวาง) หรือลบตอน migrate ก็ได้ — ถ้าลบต้องแก้ comment schema
  §4.2 + validation ที่ผูกเลข 337 ใน `seed_database.py`
- **ไม่** จำกัดค่าที่ระดับ schema (คง TEXT) — "งบประมาณตามหมวด" อาจกลับมาจาก parser
  หมายเหตุประกอบงบใน phase ถัดไป

## 4. สถาปัตยกรรม (local)

```
PDF งบการเงิน (สแกน, format ต่างกัน)      ผังบัญชี.pdf (ทำครั้งเดียว)
        │                                       │  build_reference.py
        ▼                                       ▼
 [1 extract]──► ocr cache (page_NN.md)   reference/chart_of_accounts.csv
        │                                reference/account_aliases.csv
        ▼                                       │
 [2 parse]  อ่านตามที่พิมพ์ → raw rows (ชื่อดิบ, note, values[], page)
        │                                       │
        ▼                                       ▼
 [3 normalize]  matching ladder ──unmatched──► review/queue.csv (คนเพิ่ม alias → รันซ้ำ)
        │  matched: ผูก account_code → ได้ statement_type/category/detail_level
        ▼
 [4 validate]  สมการบัญชี + coverage + cross-year ──fail/needs_review──► review/
        │  pass
        ▼
 [5 emit]  out/<sub>_<year>.csv (ตรง §9.4) + _prior_year.csv + run_report.json
                          └─ (phase ถัดไป) staging → seed_database.py
```

### Stage 0 — Ingest & manifest
- `work/<run_id>/manifest.json`: checksum PDF, จำนวนหน้า, extractor+version,
  dictionary version, สถานะต่อ stage → **idempotent**: รันซ้ำเฉพาะ stage ที่ input เปลี่ยน
  (แก้ alias แล้ว re-normalize ได้โดยไม่ต้อง OCR ใหม่)
- metadata (ตำบล/เทศบาล/ปี) มาจาก CLI/config — ไม่ parse จากชื่อไฟล์

### Stage 1 — Extract (pluggable)
- interface เดียว: `extract(pdf_path) -> list[PageMarkdown]`
- default **Typhoon OCR** (ไทย + ตารางดี, ตาม v1); ทางเลือก: Claude vision
  (layout แปลก/คุณภาพสแกนต่ำ), Tesseract (offline ล้วน — คุณภาพต่ำกว่า ใช้เป็น fallback สุดท้าย)
- เก็บ raw output ต่อหน้าเสมอ (cache + audit trail) — v1 ทำแล้ว คงไว้

### Stage 2 — Parse ("ตามที่พิมพ์")
- reuse จาก v1: pipe/HTML table parser, `money()` (วงเล็บ=ติดลบ, `-`=0, เลขไทย),
  การแยกเลขหมายเหตุ, การข้ามหน้า "หมายเหตุประกอบงบการเงิน"
- **เปลี่ยน:** section header ที่เจอเก็บเป็น `layout_hint` เท่านั้น ไม่ใช้กำหนด `หมวดหมู่` แล้ว
- output: raw rows + provenance ครบ ยังไม่มีการ map ชื่อใด ๆ

### Stage 3 — Normalize (matching ladder — deterministic ทั้งหมด)
ต่อชื่อดิบ 1 ชื่อ (หลัง normalize: ตัดช่องว่าง/`**`, เลขไทย→อารบิก):
1. **exact** — ตรงชื่อผัง/pseudo-code
2. **alias** — อยู่ใน `account_aliases.csv`
3. **fuzzy** — rapidfuzz เทียบชื่อผัง+alias ทั้งหมด รับเมื่อ score ≥ 92 **และ**
   อันดับ 1 ทิ้งอันดับ 2 ≥ 3 คะแนน → บันทึก `match_method=fuzzy` + score ลง
   `data_quality_note` (fuzzy ที่ lib+cutoff คงที่ = รันซ้ำได้ผลเดิม ต่างจากให้ LLM ตัดสิน)
4. **unmatched** — เขียน `review/queue.csv` (ชื่อดิบ, หน้า, ค่า, top-3 candidates)
   และ **ไม่หลุดเข้า output** — คนตัดสินแล้วเพิ่ม alias → re-run stage 3 (ไม่ OCR ใหม่)

จาก `account_code` ที่ match ได้ → `statement_type`, `category`, `detail_level`
ถูก derive อัตโนมัติ (ตาราง 3.2) — cross-check กับ `layout_hint`; ขัดกัน = needs_review

### Stage 4 — Validate (gate)
คงชุด v1 (Σ line_item = subtotal ต่อหมวด, สมการงบดุล 3 ข้อ, รายได้−ค่าใช้จ่าย=ดุลสุทธิ) เพิ่ม:
- **cross-year**: คอลัมน์ "ปีก่อน" ในเอกสาร vs ค่า year−1 ใน DB/ไฟล์ที่ผ่านแล้ว
  (sidecar `_prior_year.csv` ของ v1 เตรียมไว้ — v2 ใช้จริง) → จับ OCR เพี้ยนข้ามเอกสารได้
- **coverage**: %fuzzy เกิน threshold หรือมี unmatched → `needs_review`
- **sanity**: รวมยอดเฉพาะ `unit='บาท'`; ค่าติดลบยอมรับเฉพาะบัญชีที่ติดลบได้ (เช่น ดุลสุทธิ)
- ผล 3 ระดับ: `pass` / `needs_review` / `fail` → เขียน `run_report.json`

### Stage 5 — Emit
- คอลัมน์ CSV = `financial_report_ALL_master.csv` **เป๊ะ** (mapping §9.4) →
  seed ใช้ต่อได้โดยไม่แก้อะไร
- `หมายเหตุคุณภาพข้อมูล` บันทึก: ชื่อดิบ (ถ้าต่างจาก canonical), match_method, fuzzy score
- คอลัมน์ `หมายเหตุ` (note_no): use case ปัจจุบันไม่ใช้ → **ไม่เก็บลง output** (ปล่อยว่าง
  โดยคงคอลัมน์ไว้ให้ตรง §9.4) — ตอน parse ยังต้องตรวจจับเลขหมายเหตุอยู่ เพื่อกันไม่ให้ปน
  เข้าคอลัมน์เงิน; ถ้าจะตัด `note_no` ออกจาก schema จริง = schema change
  (ตาม CLAUDE.md ต้องอัปเดต `seed_database.py` + `data_model_design.md` + ERD)

### โครง module

```
ocr_pipeline/
  config.yaml              # ตำบล/ปี/extractor/threshold/paths
  build_reference.py       # ผังบัญชี.pdf → reference/*.csv (รันใหม่เมื่อผังเปลี่ยน)
  reference/               # chart_of_accounts.csv, account_aliases.csv → commit ลง git
  extractors/              # base.py, typhoon.py, claude_vision.py, tesseract.py
  parse.py / normalize.py / validate.py / emit.py
  run.py                   # CLI: python -m ocr_pipeline.run input.pdf --subdistrict … --year …
  eval/                    # evaluate.py (L1), eval_downstream.py (L2), golds/
  work/<run_id>/           # manifest, ocr cache, review/, out/  → .gitignore
```

Dependencies: `pdfplumber`, `typhoon-ocr`, `rapidfuzz` (+ poppler)
รันเป็น python ล้วนได้เลย แต่แนะนำทำ `Dockerfile` ตั้งแต่แรก (pin poppler/lib กัน drift) —
**image เดียวกันใช้ทั้ง local และ production** (§7)

## 5. Evaluation v2 — 3 ชั้น

| ชั้น | ต้องมี gold? | วัดอะไร | เครื่องมือ |
|---|---|---|---|
| **L0** self-validation | ไม่ | สมการบัญชีในเอกสาร, coverage ladder, cross-year | `validate.py` (ขยายจาก v1) — ใช้กับตำบล/ปีใหม่ได้ทันที |
| **L1** field-level vs gold | มี (bootstrap เท่านั้น) | row recall/precision, accuracy ของ มูลค่า/หมวดหมู่/detail_level + **ladder breakdown** (%exact/alias/fuzzy/unmatched) | `evaluate.py` v1 แต่เปลี่ยน key เทียบเป็น `account_code` (ทนความต่างของชื่อ) |
| **L2** downstream | มี DB (bootstrap เท่านั้น) | seed dry-run เข้า staging → `account_map` ของ Y1–Y3 resolve ครบไหม → **คะแนน Y1–Y3 ตรงกับที่คำนวณจาก gold ไหม** | `eval_downstream.py` (ใหม่) |

L2 คือตัวชี้ขาด: consumer จริงของข้อมูลคือ risk engine — แถวผิดที่ไม่กระทบ Y1–Y3
กับแถวผิดที่พลิกระดับความเสี่ยง ต้องแยกให้เห็นใน report

**บทบาทของ gold = bootstrap เท่านั้น (ไม่ scale ตามจำนวนตำบล):** L1/L2 ใช้กับ
3 ตำบลที่มี gold อยู่แล้ว เพื่อจูน parser/dictionary และเป็น regression harness
เมื่อขยายไปตำบลใหม่ **ไม่สร้าง gold เพิ่ม** — acceptance path คือ L0 + review queue
และ output ที่ผ่าน gate ก็คือ standardized data ตัวจริง (pipeline ทำหน้าที่แทน gold เดิม)
gold เดิมจึงค่อย ๆ หมดบทบาทเหลือแค่ชุด regression ป้องกัน parser/dict เสื่อม

**Regression corpus:** gold 3 ตำบล (337 แถว) + PDF ทุกไฟล์ที่มี (ท่าช้าง 67–68,
โนนกอก/โยนก 65–68, ปิงโค้ง 66–68) → ทุกครั้งที่แก้ dictionary/parser รันทั้ง corpus
ห้าม metric ตก (v1 วัดครั้งเดียวจบ — v2 วัดซ้ำเป็นนิสัย)

**Error taxonomy** ตอนวิเคราะห์ diff (วิธีแก้คนละที่ ต้องแยกก่อนแก้):
(a) OCR ตัวเลขเพี้ยน → เปลี่ยน/เพิ่ม extractor · (b) โครงตารางเพี้ยน → parse.py ·
(c) dictionary miss → เพิ่ม alias · (d) gold ผิดเอง → แก้ gold + บันทึก

**เป้า (จาก baseline v1 = 100% บน harness):** row recall ≥ 98%,
value accuracy = 100% **บนแถวที่ผ่าน validate** — precision-first ตามหลักการข้อ 6

## 6. การเชื่อมกับ `seed_database.py` (phase ถัดไป — ยังไม่ทำตอนนี้)

- ผลลัพธ์ที่ผ่าน gate → `standardized_data/staging/` → คน approve (หรือ auto เมื่อ L0
  pass ครบ) → append เข้า `financial_report_ALL_master.csv` → `python seed_database.py --force`
  ตามปกติ — **ไม่แตะ risk logic ใน API** (ตาม CLAUDE.md)
- ⚠️ validation ของ seed ผูกจำนวนแถวตายตัว (337) → เมื่อข้อมูลเริ่มมาจาก pipeline
  ต้องเปลี่ยนเป็น invariant เชิงโครงสร้าง (สมการบัญชี/FK/uniqueness) แทนเลขคงที่
- `account_map` ใน `params_json` ของ Y1–Y3 ปัจจุบันผูกชื่อรายการต่อตำบล — เมื่อทุกแถว
  เป็นชื่อ canonical จากผังแล้ว map จะสั้นลง และในอนาคตอ้าง `account_code` แทนชื่อได้
  (ต้องเพิ่มคอลัมน์ `account_code` nullable ใน `financial_statements` — เป็น schema change
  → ตาม CLAUDE.md ต้องอัปเดต `seed_database.py` + `data_model_design.md` + ERD พร้อมกัน)

## 7. Local vs Production — ต่างกันตรงไหน

หลัก: **logic ทุก stage เหมือนกัน 100%** (Docker image เดียว) — ที่ต่างคือตัวห่อรอบนอก

| ด้าน | Local (ตอนนี้) | Production |
|---|---|---|
| Orchestration | CLI ต่อไฟล์ + manifest | upload จาก Web App → job queue → worker pool; retry + dead-letter; (Prefect/Airflow เมื่อ batch ใหญ่จริง) |
| Deployment | venv หรือ docker run | image เดิม deploy เป็น worker — เปลี่ยนแค่ตัวเรียก |
| Storage | โฟลเดอร์ `work/` | object storage (PDF + OCR cache) + ตาราง staging ใน DB + retention policy |
| Reference data | CSV ใน git | ตาราง DB + UI ให้ auditor เพิ่ม alias จาก review queue + **version ทุกการแก้** (ทุก run บันทึก dict version ที่ใช้ → reproduce ได้) |
| Human review | ไฟล์ `review/queue.csv` | คิวใน Web App ผูก role `project_auditor` (โครง `roles.md`/`require_roles` มีแล้ว) — approve → auto-append alias → re-run normalize (ไม่ OCR ซ้ำ) |
| OCR | key เดียว, sequential | rate limit/quota, batch, fallback extractor อัตโนมัติ, cost monitor ต่อหน้า |
| Evaluate | รันมือทั้ง corpus | CI: PR ที่แตะ parser/dict ต้องผ่าน corpus + L2; dashboard drift — %fuzzy/unmatched ต่อเดือนพุ่ง = มี format ใหม่โผล่ |
| DB | SQLite, API อ่านอย่างเดียว | pipeline เขียนพร้อม API อ่าน → ย้าย Postgres หรือคง SQLite แบบ single-writer + staging swap |
| Security | ไฟล์ local | PDF ราชการมีลายเซ็น/ชื่อบุคคล → access control ที่ storage; พิจารณา OCR self-host ถ้านโยบายห้ามส่งเอกสารออก external API |

Scaling model: งานต่อไฟล์ independent 100% → horizontal scale ตรงไปตรงมา
คอขวดเดียวคือจุด append master CSV/seed → production แก้ด้วย DB staging + transaction

## 8. ลำดับงานเมื่อเริ่ม implement

1. `build_reference.py` + ตรวจ 1,018 รหัสกับตัวอย่างจริง
2. seed `account_aliases.csv` จาก gold 3 ตำบล + `ACCOUNT_DICT` v1 → วัด coverage บน gold = 100%
3. refactor เป็น stages + manifest (parse/validate v1 ใช้ต่อได้ ~70%)
4. evaluate v2 (key = account_code + ladder breakdown) → รันกับ `ocr_output/thachang67`
   ที่มีอยู่ → ต้องไม่แพ้ baseline v1
5. `eval_downstream.py` (L2) + ดึง PDF ที่เหลือเข้า corpus
6. staging + ขั้นตอน append → จบ local phase, พร้อมคุยเรื่องเชื่อม Web App

## 9. Open questions

- **ปิงโค้ง** (เอกสารสรุป ไม่มีงบเต็ม): v2 จะได้แถว subtotal-only — พอสำหรับ Y1–Y3
  แต่ validate ได้ไม่ครบทุกสมการ → ตั้ง default เป็น `needs_review` เลยไหม
- backfill `account_code` เข้า `financial_statements` ตอนไหน (schema change — ดู §6)
- `งบประมาณตามหมวด` / `สินทรัพย์ถาวรเพิ่มระหว่างปี` อยู่ในหมายเหตุประกอบงบซึ่งตอนนี้
  ข้ามทั้งหน้า — ทำ parser หมายเหตุ phase ไหน (ต้องมี consumer ก่อนค่อยทำ)
