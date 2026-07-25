# -*- coding: utf-8 -*-
"""L1 — field-level vs gold (key = account_code — ทนความต่างของชื่อ, design doc §5)

    python -m ocr_pipeline.eval.evaluate ocr_pipeline/work/t67_standin/out.csv \
        --year 2567 --subdistrict ท่าช้าง

Metric: row recall/precision (key = ประเภทงบ+account_code), accuracy ของ
มูลค่า/หมวดหมู่/ระดับรายละเอียด บนแถวที่ตรงกัน + ladder breakdown
(หมายเหตุไม่เทียบ — D2 กำหนดให้ output ว่างเสมอ ขณะที่ gold เก็บเลขหมายเหตุ)
"""
import argparse
import csv
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from collections import Counter

from ocr_pipeline.normalize import Reference

MAIN_STATEMENTS = ("งบแสดงฐานะการเงิน", "งบแสดงผลการดำเนินงาน")
VALUE_TOL = 0.01


def load_keyed(path: str, ref: Reference, year=None, subdistrict=None, statements=None):
    """CSV → {(ประเภทงบ, account_code): row} — key ผ่าน resolve_canonical (ทนความต่างของชื่อ)"""
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if year and r["ปีงบประมาณ"] != str(year):
            continue
        if subdistrict and r["ตำบล"] != subdistrict:
            continue
        if statements and r["ประเภทงบ"] not in statements:
            continue
        code = ref.resolve_canonical(r["รายการบัญชี"])
        key = (r["ประเภทงบ"], code or f"UNRESOLVED:{r['รายการบัญชี']}")
        out.setdefault(key, r)
    return out


def run(extracted_path: str, gold_path: str, year, subdistrict, ref_dir: str) -> dict:
    ref = Reference(ref_dir)
    ext = load_keyed(extracted_path, ref)
    statements = {k[0] for k in ext} or set(MAIN_STATEMENTS)
    gold = load_keyed(gold_path, ref, year, subdistrict, statements)

    # ladder breakdown ของ run จริงจาก run_report.json (ถ้า out.csv อยู่ใน work/<run_id>/)
    import json
    import os
    ladder = {}
    report_path = os.path.join(os.path.dirname(extracted_path), "run_report.json")
    if os.path.exists(report_path):
        ladder = json.load(open(report_path, encoding="utf-8")).get("ladder", {})

    matched = set(ext) & set(gold)
    n = len(matched)
    acc = {"มูลค่า": 0, "หมวดหมู่": 0, "ระดับรายละเอียด": 0}
    diffs = []
    for k in sorted(matched):
        e, g = ext[k], gold[k]
        if abs(float(e["มูลค่า"]) - float(g["มูลค่า"])) <= VALUE_TOL:
            acc["มูลค่า"] += 1
        else:
            diffs.append(f"มูลค่า {k}: extract={e['มูลค่า']} gold={g['มูลค่า']}")
        for f in ("หมวดหมู่", "ระดับรายละเอียด"):
            if e[f].strip() == g[f].strip():
                acc[f] += 1
            else:
                diffs.append(f"{f} {k}: extract={e[f]!r} gold={g[f]!r}")

    return {
        "gold_rows": len(gold), "extract_rows": len(ext), "matched": n,
        "recall": n / len(gold) if gold else 0.0,
        "precision": n / len(ext) if ext else 0.0,
        "accuracy": {f: (c / n if n else 0.0) for f, c in acc.items()},
        "ladder": ladder,
        "missing": sorted(set(gold) - set(ext)), "extra": sorted(set(ext) - set(gold)),
        "diffs": diffs,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("extracted")
    ap.add_argument("--gold", default="standardized_data/financial_report_ALL_master.csv")
    ap.add_argument("--year", required=True)
    ap.add_argument("--subdistrict", required=True)
    ap.add_argument("--reference", default="ocr_pipeline/reference")
    args = ap.parse_args()

    res = run(args.extracted, args.gold, args.year, args.subdistrict, args.reference)
    print(f"gold {res['gold_rows']} แถว | extract {res['extract_rows']} แถว | ตรงกัน {res['matched']}")
    print(f"row recall    {res['matched']}/{res['gold_rows']} = {res['recall']:.1%}")
    print(f"row precision {res['matched']}/{res['extract_rows']} = {res['precision']:.1%}")
    for f, v in res["accuracy"].items():
        print(f"{f:<16}{v:.1%}")
    if res["ladder"]:
        print(f"ladder (จาก run_report): {res['ladder']}")
    for label, items in (("แถวหาย (ใน gold แต่ extract ไม่เจอ)", res["missing"]),
                         ("แถวเกิน (extract มาแต่ไม่มีใน gold)", res["extra"])):
        if items:
            print(f"\n{label}:")
            for k in items:
                print("  -", k)
    if res["diffs"]:
        print("\nค่าที่ไม่ตรง:")
        for d in res["diffs"]:
            print("  ", d)


if __name__ == "__main__":
    main()
