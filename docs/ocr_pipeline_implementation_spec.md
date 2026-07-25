# Implementation Spec: `ocr_pipeline` — สำหรับ agent execute แบบ zero-shot

> เอกสารนี้เป็น **normative**: ถ้าขัดกับ `docs/ocr_pipeline_design.md` (rationale) ให้ยึดเอกสารนี้
> ทุกตัวเลข acceptance ในนี้ **วัดจริงจาก repo แล้ว** เมื่อ 2026-07-20 — ห้ามแก้เกณฑ์เพื่อให้ผ่าน

## 0. Mission

สร้าง module `ocr_pipeline/` แปลง PDF งบการเงินสแกน → CSV ตาม schema `financial_statements`
(mapping `data_model_design.md` §9.4) โดยใช้ผังบัญชี e-LAAS เป็น source of truth
ตามสถาปัตยกรรมใน `docs/ocr_pipeline_design.md` §4 ทำตามลำดับ S1→S6 (§7)
แต่ละ step มี Definition of Done ที่รันตรวจได้ — **ห้ามข้าม step ถัดไปก่อน DoD ผ่าน**

## 1. Environment & ข้อจำกัด

- Python 3.10+, รันทุกคำสั่งจาก repo root
- deps ใหม่ที่ติดตั้งได้: `pdfplumber`, `rapidfuzz` (เขียนลง `ocr_pipeline/requirements.txt`)
- **ไม่มี network / ไม่มี Typhoon API key** — ห้าม implement แล้วทดสอบด้วยการยิง OCR จริง
  ใช้ fixture ที่มีอยู่: `pipeline/ocr_output/thachang67_standin/` (หน้า 08–10 = 2 งบหลัก)
  และ `pipeline/ocr_output/thachang67/` (ครบ 33 หน้า มี noise หน้าอื่นปน)
- ผังบัญชี: `ผังบัญชี.pdf` ที่ repo root (61 หน้า มี text layer — ห้าม OCR ใช้ pdfplumber)
- gold: `standardized_data/financial_report_ALL_master.csv` (ใช้ไฟล์นี้ไฟล์เดียวเป็น gold)

## 2. Scope / ห้ามแตะ

**สร้างใหม่ได้เฉพาะ:** `ocr_pipeline/**` และแก้ `.gitignore` (เพิ่ม `ocr_pipeline/work/`)

**ห้ามแก้:** `src/**`, `seed_database.py`, `standardized_data/**`, `pipeline/**` (v1 = reference),
`fraud_risk.db`, `tests/**` เดิม, gold ทุกไฟล์, เอกสาร design ทุกไฟล์
**ห้ามทำใน phase นี้:** schema change ใด ๆ, backfill `account_code` ลง DB, parser หน้าหมายเหตุ
ประกอบงบ, การเชื่อม `seed_database.py`, Web App integration

## 3. การตัดสินใจที่ปิดแล้ว (อย่าเปิดใหม่)

| # | เรื่อง | คำตัดสิน |
|---|---|---|
| D1 | statement_type | ผลิตเฉพาะ `งบแสดงฐานะการเงิน`, `งบแสดงผลการดำเนินงาน` เท่านั้น |
| D2 | คอลัมน์ `หมายเหตุ` (note_no) | ตอน parse ต้องตรวจจับเลข 1–2 หลักเพื่อกันปนคอลัมน์เงิน แต่ **เขียนลง output เป็นค่าว่างเสมอ** |
| D3 | gold | ใช้เป็น bootstrap/regression เท่านั้น — ห้ามแก้ gold ทุกกรณี |
| D4 | เอกสารแบบสรุป (สไตล์ปิงโค้ง) | ถ้า validate ครบทุกสมการไม่ได้เพราะมีแต่ subtotal → สถานะ `needs_review` (ไม่ใช่ fail) |
| D5 | unmatched | ห้ามหลุดเข้า output CSV — ไปที่ `review/queue.csv` เท่านั้น |
| D6 | fuzzy | `rapidfuzz.fuzz.ratio` บนชื่อที่ normalize แล้ว, รับเมื่อ score ≥ 92 และ (top1 − top2) ≥ 3 |
| D7 | extractor | โครง pluggable ต้องมี (`extractors/base.py`, `typhoon.py` เขียนตาม v1 แต่ไม่ต้องทดสอบจริง) + mode `--from-ocr <dir>` อ่าน markdown ที่มีอยู่ = ทางเดียวที่ใช้ทดสอบ |
| D8 | Dockerfile | เขียนไว้ (python-slim + poppler + requirements) แต่การ build image **ไม่อยู่ใน DoD** |

## 4. Deliverables

```
ocr_pipeline/
  requirements.txt        Dockerfile        config.yaml
  build_reference.py      run.py            (CLI — §5.9)
  extractors/base.py      extractors/typhoon.py
  parse.py  normalize.py  validate.py  emit.py
  reference/chart_of_accounts.csv           (ผลจาก S1 — commit)
  reference/account_aliases.csv             (ผลจาก S2 — commit)
  eval/evaluate.py  eval/coverage.py  eval/eval_downstream.py
  tests/  (pytest — S6)
  work/   (.gitignore — manifest, review/, out/ ต่อ run)
```

## 5. Contracts

### 5.1 `normalize_name(s)` — ใช้ทุกจุดที่เทียบชื่อ (ทั้ง build reference และ runtime)

1. ลบ `**` และ tag HTML
2. เลขไทย `๐-๙` → อารบิก
3. ลบ whitespace **ทั้งหมด** (สำคัญ: text layer ผังบัญชีมี glyph แตกแบบ `สินทรัพย ์` —
   การลบ space ทั้งหมดทำให้ combining mark กลับมาติดคำ)
4. ลบอักขระ: `.`, `,`, `*` ท้ายชื่อ
ผลลัพธ์ใช้เป็น key เทียบเท่านั้น — ชื่อที่เขียนออก output ใช้ชื่อ canonical จาก reference

### 5.2 `reference/chart_of_accounts.csv` (ผล S1)

คอลัมน์: `account_code, account_name, level, parent_code, statement_type, category, postable`
(ไม่เก็บ description — ยาวและไม่ได้ใช้ runtime)

- `account_code`: regex `^\d{10}\.\d{3}$` จาก text layer; ชื่อ = ข้อความหลังรหัสจนถึงคำว่า
  "หมายถึง" หรือจบบรรทัด (คำอธิบายพันหลายบรรทัด — ตัดทิ้งได้); ข้าม header หน้า (`- N -`)
- `postable` = 1 เมื่อส่วนท้าย `.xxx` ≠ `000`
- `level`/`parent_code`: จากตำแหน่ง trailing zeros ของรหัส 10 หลัก
- `statement_type`/`category`: derive ตามตาราง §3.2 ของ design doc (prefix หลัก 1–2 ตัว)

### 5.3 `reference/account_aliases.csv` (ผล S2)

คอลัมน์: `alias_normalized, target_code, note`
`target_code` = `account_code` จริง หรือ pseudo-code จากตารางนี้ (**ตารางนี้ปิดแล้ว ใช้ตามนี้**):

| pseudo_code | canonical_name (ใช้เขียน output) | category ที่ emit | detail_level |
|---|---|---|---|
| `TOTAL:1100000000` | รวมสินทรัพย์หมุนเวียน | สินทรัพย์หมุนเวียน | subtotal |
| `TOTAL:1200000000` | รวมสินทรัพย์ไม่หมุนเวียน | สินทรัพย์ไม่หมุนเวียน | subtotal |
| `TOTAL:1000000000` | รวมสินทรัพย์ | สินทรัพย์รวม | total |
| `TOTAL:2100000000` | รวมหนี้สินหมุนเวียน | หนี้สินหมุนเวียน | subtotal |
| `TOTAL:2200000000` | รวมหนี้สินไม่หมุนเวียน | หนี้สินไม่หมุนเวียน | subtotal |
| `TOTAL:2000000000` | รวมหนี้สิน | หนี้สินรวม | total |
| `TOTAL:3000000000` | รวมสินทรัพย์สุทธิ/ส่วนทุน | สินทรัพย์สุทธิ_ส่วนทุน | subtotal |
| `TOTAL:LIAB_EQUITY` | รวมหนี้สินและสินทรัพย์สุทธิ/ส่วนทุน | หนี้สินและส่วนทุนรวม | total |
| `TOTAL:4000000000` | รวมรายได้ | รายได้รวม | total |
| `TOTAL:5000000000` | รวมค่าใช้จ่าย | ค่าใช้จ่ายรวม | total |
| `NET:SURPLUS` | รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ | สรุปผล | total |
| `SUBTOTAL:PERSONNEL` | รวมค่าใช้จ่ายบุคลากร (เงินเดือน+บำนาญ+ค่าตอบแทน) | ค่าใช้จ่าย | subtotal |

การ seed (S2): ไล่ชื่อ distinct ใน gold (เฉพาะ 2 งบหลัก) — ชื่อที่ exact match ผังไม่ต้องมี alias;
ที่เหลือ author alias เอง (ตัดสินจากชื่อ+หมวด+ระดับใน gold, แถว subtotal/total → pseudo-code
ตามหมวด) การ author เป็น curation ครั้งเดียว — ความ deterministic อยู่ที่ไฟล์ CSV ที่ commit

### 5.4 Matching ladder (runtime, ใน `normalize.py`)

```
k = normalize_name(raw)
1 exact : k ตรง normalize_name(ชื่อผัง postable) หรือ canonical_name ของ pseudo-code
2 alias : k อยู่ใน account_aliases.csv
3 fuzzy : rapidfuzz.fuzz.ratio(k, ทุก candidate จาก 1+2) — รับเมื่อ ≥92 และ top1−top2 ≥ 3
4 unmatched → review/queue.csv: raw, page, values, top-3 candidates+score — ไม่เข้า output
```
match แล้ว: `statement_type/category/detail_level` มาจาก reference (5.2/5.3) เท่านั้น
ห้ามใช้ section header ของเอกสารกำหนด (เก็บเป็น `layout_hint` ใน review/report เฉย ๆ)

### 5.5 Output CSV (จาก `emit.py`) — คอลัมน์ต้องตรงนี้เป๊ะ ตามลำดับ

`ตำบล, เทศบาล, ปีงบประมาณ, ประเภทงบ, หมวดหมู่, รายการบัญชี, หมายเหตุ, มูลค่า, หน่วย, ระดับรายละเอียด, หมายเหตุคุณภาพข้อมูล, ไฟล์ต้นฉบับ`

- encoding `utf-8-sig`; `หมายเหตุ` = ว่างเสมอ (D2); `หน่วย` = `บาท`
- `หมายเหตุคุณภาพข้อมูล`: ว่างเมื่อ exact/alias และชื่อดิบ=canonical; ไม่งั้น
  `match=<method>(<score>); ชื่อในเอกสาร: <raw>`
- `ไฟล์ต้นฉบับ` = `<source>#p<page>`; sidecar `_prior_year.csv` ตามรูปแบบ v1

### 5.6 `manifest.json` (ต่อ run ใน `work/<run_id>/`)

```json
{"run_id": "thachang_2567_r1", "pdf_sha256": "…หรือ null เมื่อ --from-ocr",
 "ocr_source": "pipeline/ocr_output/thachang67_standin", "pages": 3,
 "extractor": {"name": "from-ocr", "version": null},
 "reference": {"coa_sha256": "…", "aliases_sha256": "…"},
 "meta": {"subdistrict": "ท่าช้าง", "municipality": "เทศบาลตำบลท่าช้าง", "year": 2567,
          "source": "ท่าช้าง67.pdf"},
 "stages": {"extract": "skipped", "parse": "done", "normalize": "done",
            "validate": "pass", "emit": "done"}}
```

### 5.7 `run_report.json`

```json
{"run_id": "…", "status": "pass | needs_review | fail",
 "ladder": {"exact": 30, "alias": 13, "fuzzy": 0, "unmatched": 0},
 "rows_emitted": 43, "rows_to_review": 0,
 "validation": [{"check": "สมการบัญชี: รวมสินทรัพย์ = หนี้สิน+ทุน", "result": "pass",
                 "expected": 532450592.85, "got": 532450592.85}],
 "cross_year": {"checked": 41, "mismatch": 0}}
```

### 5.8 `config.yaml` (ค่า default — CLI override ได้)

```yaml
fuzzy: {threshold: 92, margin: 3}
gate:  {max_fuzzy_pct: 10, max_unmatched: 0, money_tol: 0.01}
paths: {reference: ocr_pipeline/reference, work: ocr_pipeline/work}
```

### 5.9 CLI

```bash
python -m ocr_pipeline.build_reference ผังบัญชี.pdf --out ocr_pipeline/reference/
python -m ocr_pipeline.run --from-ocr <dir> --subdistrict … --municipality … --year … \
       --source … --run-id …          # (--pdf <file> --extractor typhoon = โหมด production)
python -m ocr_pipeline.eval.coverage   # เทียบ aliases+ผัง กับ gold ทั้งไฟล์
python -m ocr_pipeline.eval.evaluate <out.csv> --year <ปี> --subdistrict <ตำบล>
python -m ocr_pipeline.eval.eval_downstream <out.csv> --year <ปี> --subdistrict <ตำบล>
```

## 6. Validation rules (ใน `validate.py`, tolerance = `money_tol`)

1. Σ line_item ต่อ (งบ, category) = ค่า subtotal ของ category นั้น (เมื่อมี line_item)
2. `TOTAL:1100000000` + `TOTAL:1200000000` = `TOTAL:1000000000`
3. `TOTAL:2000000000` + `TOTAL:3000000000` = `TOTAL:LIAB_EQUITY`
4. `TOTAL:1000000000` = `TOTAL:LIAB_EQUITY`
5. `TOTAL:4000000000` − `TOTAL:5000000000` = `NET:SURPLUS`
6. cross-year: ค่าใน sidecar ปีก่อน vs ไฟล์ out ของปี year−1 (ถ้ามีใน `work/`) ต่างเกิน tol → นับ mismatch

สถานะ: ทุกข้อผ่าน + unmatched=0 + fuzzy_pct ≤ เกณฑ์ → `pass`
สมการที่ขาดแถว (เอกสารสรุป) หรือ fuzzy/coverage เกินเกณฑ์ → `needs_review`
สมการที่ **มีครบแต่ไม่ลงตัว** → `fail` · needs_review/fail → exit code ≠ 0

## 7. Build steps + Definition of Done (ตัวเลขวัดจริงแล้ว — ต้อง reproduce ได้)

### S1 `build_reference.py`
```bash
python -m ocr_pipeline.build_reference ผังบัญชี.pdf --out ocr_pipeline/reference/
```
DoD: ได้ 1,018 รหัส; แบ่งตามหลักแรก `1:252, 2:124, 3:20, 4:320, 5:302`;
spot check (เทียบแบบ normalize แล้ว): `1101010101.001`=เงินสดในมือ, `1000000000.000`=สินทรัพย์,
`2100000000.000`=หนี้สินหมุนเวียน; ทุกแถว derive `statement_type`+`category` ได้ไม่มี null

### S2 seed `account_aliases.csv` + `eval/coverage.py`
```bash
python -m ocr_pipeline.eval.coverage
```
DoD: ชื่อ distinct (ประเภทงบ, รายการบัญชี) ใน gold 2 งบหลัก = **72 คู่ (264 แถว)** —
resolve ผ่าน exact/alias ครบ **72/72 (100%)**, fuzzy = 0, unmatched = 0
(หน่วยใน gold เป็น `บาท` ทั้ง 264 แถว; detail: line_item 184 / subtotal 38 / total 42 —
ใช้ cross-check ว่า derive จาก reference แล้วตรง gold)

### S3 stages `parse → normalize → emit` (โหมด `--from-ocr`)
```bash
python -m ocr_pipeline.run --from-ocr pipeline/ocr_output/thachang67_standin \
  --subdistrict ท่าช้าง --municipality เทศบาลตำบลท่าช้าง --year 2567 \
  --source ท่าช้าง67.pdf --run-id t67_standin
python -m ocr_pipeline.eval.evaluate ocr_pipeline/work/t67_standin/out.csv --year 2567 --subdistrict ท่าช้าง
```
DoD (fixture standin — baseline v1 = 100% ทุกตัว ต้องไม่แพ้):
rows_emitted = 43, row recall = precision = 100%, accuracy มูลค่า/หมวดหมู่/ระดับรายละเอียด = 100%

จากนั้นรันชุดเต็ม 33 หน้า (`--from-ocr pipeline/ocr_output/thachang67 --run-id t67_full`)
DoD (baseline v1: 51 แถว, recall 97.7%, precision 82.4%, มูลค่า 97.6% — v2 ต้องชนะด้วย gate):
**precision ของแถวที่ emit = 100%** (แถวเกิน 9 แถวของ v1 ต้องไป `review/queue.csv` ไม่ใช่ out.csv),
recall ≥ 97.7%, มูลค่า accuracy = 100% บนแถวที่ emit; ผล ladder + review ปรากฏใน `run_report.json`

### S4 `validate.py` + gate
DoD: (a) run standin → ทุกสมการ pass, status `pass`
(b) test ปลอมค่า: copy out.csv แก้เลข 1 หลักในแถว line_item ใดก็ได้ → validate ต้อง `fail`
(c) ลบแถว line_item ทั้งหมดของ 1 category (จำลองเอกสารสรุป) → ต้อง `needs_review` ไม่ใช่ fail

### S5 `eval/eval_downstream.py` (L2 — ไม่ใช้ DB)
คำนวณจาก out.csv vs gold (ปี+ตำบลเดียวกัน): ค่า 5 ตัวที่ Y2/Y3 ใช้ —
`TOTAL:4000000000`, `TOTAL:5000000000`, `NET:SURPLUS`, เงินสดและรายการเทียบเท่าเงินสด (`1101…`),
`TOTAL:2100000000` — ต้องเท่ากันภายใน ±0.01 ทั้ง 5 · DoD: ผ่านบน t67_standin

### S6 tests
`ocr_pipeline/tests/`: unit (normalize_name, money, ladder รวม tie-break, derive จากรหัส) +
integration (S3 standin ต้อง 100%) — ห้ามใช้ network
DoD: `pytest -q` จาก repo root **เขียวทั้ง repo** (ของเดิมต้องไม่พัง)

## 8. Failure protocol

- acceptance ไม่ผ่าน → ห้ามลด threshold / ห้ามแก้ gold / ห้ามแก้เกณฑ์ในเอกสารนี้
- วิเคราะห์ตาม error taxonomy (design doc §5): parse bug → แก้ `parse.py`,
  dictionary miss → เพิ่ม alias (บันทึก note), OCR เพี้ยนใน fixture → **บันทึกใน BLOCKERS.md ห้ามแก้ fixture**
- ติดเกิน 3 รอบใน step เดียว → เขียน `ocr_pipeline/BLOCKERS.md` (อาการ, สิ่งที่ลอง, สมมติฐาน) แล้วหยุด

## 9. นอก scope (อย่าเผลอทำ)

เชื่อม `seed_database.py` / staging, แก้ account_map ใน `params_json`, parser หมายเหตุประกอบงบ,
UI review, การ deploy จริง — ทั้งหมดรอ phase ถัดไป (design doc §6–§7)
