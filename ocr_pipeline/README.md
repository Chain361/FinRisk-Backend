# ocr_pipeline — PDF งบการเงิน → `financial_statements` (chart-of-accounts-driven)

Implement ตาม `docs/ocr_pipeline_implementation_spec.md` (normative) + `docs/ocr_pipeline_design.md`
ผังบัญชี e-LAAS = source of truth ของชื่อ canonical / statement_type / category / detail_level

## วิธีใช้

```bash
pip install -r ocr_pipeline/requirements.txt

# S1 — สร้าง reference จากผังบัญชี (ทำใหม่เมื่อผังเปลี่ยนเท่านั้น — ผลลัพธ์ commit ไว้แล้ว)
python -m ocr_pipeline.build_reference ผังบัญชี.pdf --out ocr_pipeline/reference/

# รัน 1 เอกสาร (โหมดทดสอบ: --from-ocr | โหมด production: --pdf + TYPHOON_OCR_API_KEY)
python -m ocr_pipeline.run --from-ocr pipeline/ocr_output/thachang67_standin \
    --subdistrict ท่าช้าง --municipality เทศบาลตำบลท่าช้าง --year 2567 \
    --source ท่าช้าง67.pdf --run-id t67_standin
# → ocr_pipeline/work/t67_standin/{out.csv, out_prior_year.csv, review/queue.csv,
#                                 run_report.json, manifest.json}
# exit code: pass=0, fail=1, needs_review=2

# โหมด batch: PDF หลายตำบล/หลายปีกองในโฟลเดอร์เดียว + batch.csv (mapping metadata)
#   batch.csv: pdf, ตำบล, เทศบาล, ปีงบประมาณ [, run_id, ocr_dir]
python -m ocr_pipeline.batch <folder>          # [--include-needs-review หลังคนตรวจ review/ แล้ว]
# → work/batch/financial_report_batch_master.csv (คอลัมน์ตรง ALL_master เป๊ะ) + batch_report.json
#   รวมเฉพาะ run ที่ผ่าน gate

# Promote ผลลัพธ์ batch ไปยัง standardized_data/ (อัปเดตตาม ตำบล+ปีงบประมาณ พร้อมสำรองข้อมูลเดิม)
python -m ocr_pipeline.promote                                # Promote batch master CSV
python -m ocr_pipeline.promote --seed                         # Promote + รัน seed_database.py --force

# ตรวจ/วัดผล
python -m ocr_pipeline.validate ocr_pipeline/work/t67_standin/out.csv       # สมการบัญชี (L0)
python -m ocr_pipeline.eval.coverage                                       # aliases+ผัง vs gold
python -m ocr_pipeline.eval.evaluate <out.csv> --year 2567 --subdistrict ท่าช้าง        # L1
python -m ocr_pipeline.eval.eval_downstream <out.csv> --year 2567 --subdistrict ท่าช้าง # L2
pytest -q ocr_pipeline/tests                                               # DoD ทั้งหมด

```

## หลักการสำคัญ

- **Matching ladder** (`normalize.py`): exact (ชื่อผัง postable + pseudo-code) → alias
  (`reference/account_aliases.csv`) → fuzzy (rapidfuzz ≥ 92, margin ≥ 3) → unmatched
  ไป `review/queue.csv` เท่านั้น — **ไม่มีวันหลุดเข้า out.csv**
- `statement_type/category/detail_level` derive จาก **รหัสบัญชี** — section header ของเอกสาร
  เป็นแค่ `layout_hint`; งบนอก scope (เช่น งบแสดงการเปลี่ยนแปลงฯ) ทั้งหน้าไป review
- **Cross-run gate**: ถ้าใน `work/` มี run อื่นของ (ตำบล, ปี) เดียวกัน ค่าที่ขัดกันเกิน
  `money_tol` = สองการสกัดอิสระไม่ตรงกัน → กักแถวนั้นไป review (ห้าม auto-fix) —
  กลไกนี้จับค่า OCR เพี้ยน 1 หลักใน fixture ชุดเต็ม (`รายได้ภาษีจัดสรร` 555 vs 565) ได้
- Validate 3 ระดับ: `pass` / `needs_review` (สมการขาดแถว — เอกสารสรุปสไตล์ปิงโค้ง, D4) /
  `fail` (สมการครบแต่ไม่ลงตัว)

## ผลวัดกับ fixture (reproduce ได้ด้วย pytest)

| ชุด | แถว out | recall | precision | มูลค่า/หมวด/ระดับ |
|---|---|---|---|---|
| standin (หน้า 08–10) | 43 | 100% | 100% | 100% |
| เต็ม 33 หน้า (v1: 51 แถว, P 82.4%, มูลค่า 97.6%) | 42 | 97.7% | **100%** | **100%** |

## นอก scope phase นี้ (spec §9)

เชื่อม `seed_database.py`/staging, parser หมายเหตุประกอบงบ, UI review, deploy จริง
