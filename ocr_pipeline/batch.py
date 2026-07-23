# -*- coding: utf-8 -*-
"""Batch runner: โฟลเดอร์ PDF หลายตำบล/หลายปี → รันต่อไฟล์ → รวมเป็น CSV เดียว
(คอลัมน์ตรง standardized_data/financial_report_ALL_master.csv — พร้อมให้คนตรวจ
แล้ว copy ไปแทน/append เอง ก่อนเรียก seed_database.py)

    python -m ocr_pipeline.batch <folder>            # ต้องมี <folder>/batch.csv

batch.csv (utf-8-sig): pdf, ตำบล, เทศบาล, ปีงบประมาณ [, run_id, ocr_dir]
- metadata มาจากไฟล์ mapping — ไม่ parse จากชื่อไฟล์ (design doc Stage 0)
- ocr_dir: ระบุเมื่อมี OCR cache แล้ว (โหมดทดสอบ/ไม่มี API key) — ไม่งั้นใช้ --extractor กับ pdf
- เรียงรัน (ตำบล, ปีเก่า→ใหม่) อัตโนมัติ เพื่อให้ cross-year check มีผลปีก่อนไว้เทียบ

การรวม (gate — precision-first):
- status `pass`            → รวมเข้า merged CSV
- status `needs_review`    → ไม่รวม เว้นแต่ส่ง --include-needs-review (คนตรวจ review/ แล้ว)
- status `fail`            → ไม่รวมเสมอ
ผลลัพธ์: work/batch/financial_report_batch_master.csv + batch_report.json
exit code: 1 ถ้ามี fail, 2 ถ้ามี needs_review ที่ไม่ถูกรวม, 0 เมื่อรวมครบทุกไฟล์
"""
import argparse
import csv
import glob
import json
import os
import sys
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


from ocr_pipeline.emit import OUT_COLS
from ocr_pipeline.run import load_config, run_pipeline


def read_batch_csv(folder: str):
    path = os.path.join(folder, "batch.csv")
    if not os.path.exists(path):
        sys.exit(f"ไม่พบ {path} — ต้องมีไฟล์ mapping (pdf, ตำบล, เทศบาล, ปีงบประมาณ)")
    jobs = []
    for i, r in enumerate(csv.DictReader(open(path, encoding="utf-8-sig"))):
        pdf = (r.get("pdf") or "").strip()
        ocr_dir = (r.get("ocr_dir") or "").strip()
        sub, year = r["ตำบล"].strip(), int(r["ปีงบประมาณ"])
        if pdf and not os.path.isabs(pdf):
            pdf = os.path.join(folder, pdf)
        jobs.append({
            "pdf": pdf or None, "ocr_dir": ocr_dir or None,
            "subdistrict": sub, "municipality": r["เทศบาล"].strip(), "year": year,
            "source": os.path.basename(pdf) if pdf else (r.get("source") or ocr_dir or f"row{i}"),
            "run_id": (r.get("run_id") or "").strip() or f"{sub}_{year}",
        })
    # ปีเก่าก่อนเสมอ → run ปีถัดไปได้ cross-year check กับผลที่เพิ่งผ่าน
    jobs.sort(key=lambda j: (j["subdistrict"], j["year"]))
    return jobs


def merge(results, work_dir: str, include_needs_review: bool, include_fails: bool = False):
    """รวม out.csv ของ run ที่ผ่าน gate — กัน (ตำบล, ปี) ซ้ำ (คงผลของ run แรกที่ผ่าน)"""
    merged, seen_docs, skipped_dup = [], set(), []
    for res in results:
        ok = (res["status"] == "pass"
              or (include_needs_review and res["status"] == "needs_review")
              or (include_fails and res["status"] == "fail"))
        if not ok:
            continue
        doc_key = (res["subdistrict"], res["year"])
        if doc_key in seen_docs:
            skipped_dup.append(res["run_id"])
            continue
        seen_docs.add(doc_key)
        out_csv = os.path.join(work_dir, res["run_id"], "out.csv")
        merged.extend(csv.DictReader(open(out_csv, encoding="utf-8-sig")))
        res["merged"] = True
    return merged, skipped_dup


def _cached_ocr_dir(work_dir: str, run_id: str):
    """หา OCR cache เดิมใน work/<run_id>/ocr/ (Tier 2 fallback — ไม่ต้องมี poppler/API key)"""
    d = os.path.join(work_dir, run_id, "ocr")
    return d if glob.glob(os.path.join(d, "page_*.md")) else None


def process_batch(folder: str, extractor: str = "typhoon",
                  include_needs_review: bool = False,
                  include_fails: bool = False,
                  config_path: str = "ocr_pipeline/config.yaml",
                  prefer_cached_ocr: bool = False) -> dict:
    """API สำหรับเรียกจากโค้ด (run_pipeline.py) — ตรรกะเดียวกับ CLI เดิมทุกประการ

    prefer_cached_ocr=True: job ที่ไม่ได้ระบุ ocr_dir จะใช้ work/<run_id>/ocr/ ถ้ามี
    (โหมด offline — ข้าม OCR จริง) · คืน summary dict เดียวกับ batch_report.json
    """
    cfg = load_config(config_path)
    work_dir = cfg["paths"]["work"]
    jobs = read_batch_csv(folder)

    if prefer_cached_ocr:
        for j in jobs:
            if not j["ocr_dir"]:
                cached = _cached_ocr_dir(work_dir, j["run_id"])
                if cached:
                    j["ocr_dir"] = cached

    results = []
    for j in jobs:
        run_args = SimpleNamespace(
            from_ocr=j["ocr_dir"], pdf=j["pdf"], extractor=extractor,
            subdistrict=j["subdistrict"], municipality=j["municipality"],
            year=j["year"], source=j["source"], run_id=j["run_id"])
        print(f"\n=== run {j['run_id']} ({j['subdistrict']} {j['year']}) ===")
        try:
            run_pipeline(run_args, cfg)
            report = json.load(open(os.path.join(work_dir, j["run_id"], "run_report.json"),
                                    encoding="utf-8"))
            status = report["status"]
        except Exception as e:                          # OCR/parse พังทั้งไฟล์ → นับเป็น fail
            print(f"[error] {e}")
            status = "fail"
        results.append({**j, "status": status, "merged": False})

    merged, skipped_dup = merge(results, work_dir, include_needs_review, include_fails)
    batch_dir = os.path.join(work_dir, "batch")
    os.makedirs(batch_dir, exist_ok=True)
    merged_path = os.path.join(batch_dir, "financial_report_batch_master.csv")
    with open(merged_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(merged)

    summary = {
        "runs": [{k: r[k] for k in ("run_id", "subdistrict", "year", "status", "merged")}
                 for r in results],
        "merged_rows": len(merged), "merged_path": merged_path,
        "skipped_duplicates": skipped_dup,
    }
    with open(os.path.join(batch_dir, "batch_report.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nรวม {len(merged)} แถว จาก {sum(1 for r in results if r['merged'])}/{len(results)} run"
          f" → {merged_path}")
    for r in results:
        print(f"  [{r['status']:<12}] {r['run_id']}" + ("" if r["merged"] else "  (ไม่ถูกรวม)"))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="โฟลเดอร์ที่มี PDF + batch.csv")
    ap.add_argument("--extractor", default="typhoon")
    ap.add_argument("--include-needs-review", action="store_true",
                    help="รวม run ที่ needs_review ด้วย (ใช้หลังคนตรวจ review/queue.csv แล้ว)")
    ap.add_argument("--include-fails", action="store_true",
                    help="รวม run ที่ fail ด้วย")
    ap.add_argument("--config", default="ocr_pipeline/config.yaml")
    args = ap.parse_args()

    summary = process_batch(args.folder, extractor=args.extractor,
                            include_needs_review=args.include_needs_review,
                            include_fails=args.include_fails,
                            config_path=args.config)

    print("\nขั้นถัดไป (ทำโดยคน — นอก scope pipeline): ตรวจ review/ ของ run ที่ needs_review,"
          "\nแล้ว copy ไฟล์รวมไป standardized_data/ + ปรับ account_map/validation ของ seed ก่อนรัน seed_database.py")

    runs = summary["runs"]
    if not args.include_fails and any(r["status"] == "fail" for r in runs):
        sys.exit(1)
    if any(not r["merged"] for r in runs):
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
