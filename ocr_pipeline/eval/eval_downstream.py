# -*- coding: utf-8 -*-
"""L2 — downstream check (ไม่ใช้ DB): ค่า 5 ตัวที่ risk factor Y2/Y3 ใช้ ต้องตรง gold ±0.01

    python -m ocr_pipeline.eval.eval_downstream ocr_pipeline/work/t67_standin/out.csv \
        --year 2567 --subdistrict ท่าช้าง

ตัวชี้ขาดของ pipeline คือ consumer จริง (risk engine) — แถวผิดที่พลิกคะแนนความเสี่ยง
ต้องมองเห็นแยกจากแถวผิดที่ไม่กระทบ (design doc §5)
"""
import argparse
import csv
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


from ocr_pipeline.normalize import Reference

TOL = 0.01

# (ป้ายกำกับ, วิธีเลือกแถว) — เลือกด้วย account_code ที่ resolve แล้ว
TARGETS = [
    ("รวมรายได้ (TOTAL:4000000000)", lambda code: code == "TOTAL:4000000000"),
    ("รวมค่าใช้จ่าย (TOTAL:5000000000)", lambda code: code == "TOTAL:5000000000"),
    ("รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ (NET:SURPLUS)", lambda code: code == "NET:SURPLUS"),
    ("เงินสดและรายการเทียบเท่าเงินสด (1101…)", lambda code: str(code).startswith("1101")),
    ("รวมหนี้สินหมุนเวียน (TOTAL:2100000000)", lambda code: code == "TOTAL:2100000000"),
]

MAIN_STATEMENTS = ("งบแสดงฐานะการเงิน", "งบแสดงผลการดำเนินงาน")


def load_values(path: str, ref: Reference, year=None, subdistrict=None) -> dict:
    """CSV → {account_code: มูลค่า} (แถวแรกต่อ code — dedup ตามพฤติกรรม pipeline)"""
    vals = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if year and r["ปีงบประมาณ"] != str(year):
            continue
        if subdistrict and r["ตำบล"] != subdistrict:
            continue
        if r["ประเภทงบ"] not in MAIN_STATEMENTS:
            continue
        code = ref.resolve_canonical(r["รายการบัญชี"])
        if code is not None:
            vals.setdefault(code, float(r["มูลค่า"]))
    return vals


def pick(vals: dict, selector) -> float | None:
    for code, v in vals.items():
        if selector(code):
            return v
    return None


def run(extracted_path: str, gold_path: str, year, subdistrict, ref_dir: str):
    ref = Reference(ref_dir)
    ext = load_values(extracted_path, ref)
    gold = load_values(gold_path, ref, year, subdistrict)
    results = []
    for label, sel in TARGETS:
        e, g = pick(ext, sel), pick(gold, sel)
        ok = e is not None and g is not None and abs(e - g) <= TOL
        results.append({"target": label, "extract": e, "gold": g, "ok": ok})
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("extracted")
    ap.add_argument("--gold", default="standardized_data/financial_report_ALL_master.csv")
    ap.add_argument("--year", required=True)
    ap.add_argument("--subdistrict", required=True)
    ap.add_argument("--reference", default="ocr_pipeline/reference")
    args = ap.parse_args()

    results = run(args.extracted, args.gold, args.year, args.subdistrict, args.reference)
    fails = 0
    for r in results:
        mark = "[PASS]" if r["ok"] else "[FAIL]"
        fails += 0 if r["ok"] else 1
        fmt = lambda v: f"{v:,.2f}" if v is not None else "ไม่พบแถว"
        print(f"{mark} {r['target']}: extract={fmt(r['extract'])} gold={fmt(r['gold'])}")
    print(f"\nผล: {'ผ่านทั้ง 5 ค่า' if fails == 0 else f'ไม่ผ่าน {fails} ค่า'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
