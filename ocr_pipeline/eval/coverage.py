# -*- coding: utf-8 -*-
"""S2 — วัด coverage ของ reference (ผัง + aliases) กับ gold ทั้งไฟล์

    python -m ocr_pipeline.eval.coverage

DoD: ชื่อ distinct (ประเภทงบ, รายการบัญชี) ใน gold 2 งบหลัก = 72 คู่ (264 แถว)
resolve ผ่าน exact/alias ครบ 72/72, fuzzy = 0, unmatched = 0
+ cross-check ว่า statement_type/category/detail_level ที่ derive จาก reference ตรง gold
"""
import argparse
import csv
import sys
from collections import Counter

from ocr_pipeline.normalize import Reference

MAIN_STATEMENTS = ("งบแสดงฐานะการเงิน", "งบแสดงผลการดำเนินงาน")


def run(gold_path: str, ref_dir: str) -> dict:
    ref = Reference(ref_dir)
    rows = [r for r in csv.DictReader(open(gold_path, encoding="utf-8-sig"))
            if r["ประเภทงบ"] in MAIN_STATEMENTS]
    pairs = {}
    for r in rows:
        pairs.setdefault((r["ประเภทงบ"], r["รายการบัญชี"]), r)

    ladder = Counter()
    problems = []
    for (st, name), g in sorted(pairs.items()):
        m = ref.match(name)
        ladder[m["method"]] += 1
        if m["method"] in ("fuzzy", "unmatched"):
            problems.append(f"[{m['method']}] {st} | {name} | top: {m['candidates'][:1]}")
            continue
        canon, d_st, d_cat, d_dl = ref.attrs(m["code"])
        if d_st != st:
            problems.append(f"[statement ไม่ตรง] {name}: derive={d_st} gold={st}")
        if d_cat != g["หมวดหมู่"]:
            problems.append(f"[category ไม่ตรง] {name}: derive={d_cat} gold={g['หมวดหมู่']}")
        if d_dl != g["ระดับรายละเอียด"]:
            problems.append(f"[detail ไม่ตรง] {name}: derive={d_dl} gold={g['ระดับรายละเอียด']}")

    unit_bad = sum(1 for r in rows if r["หน่วย"] != "บาท")
    detail = Counter(r["ระดับรายละเอียด"] for r in rows)
    return {"rows": len(rows), "pairs": len(pairs), "ladder": dict(ladder),
            "unit_bad": unit_bad, "detail": dict(detail), "problems": problems}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="standardized_data/financial_report_ALL_master.csv")
    ap.add_argument("--reference", default="ocr_pipeline/reference")
    args = ap.parse_args()

    res = run(args.gold, args.reference)
    resolved = res["ladder"].get("exact", 0) + res["ladder"].get("alias", 0)
    print(f"gold 2 งบหลัก: {res['rows']} แถว, {res['pairs']} คู่ distinct (ประเภทงบ, รายการบัญชี)")
    print(f"ladder: {res['ladder']}  → resolve ผ่าน exact/alias {resolved}/{res['pairs']}")
    print(f"detail_level ใน gold: {res['detail']}  | หน่วยไม่ใช่บาท: {res['unit_bad']} แถว")
    for p in res["problems"]:
        print(" ", p)
    ok = (resolved == res["pairs"] and not res["problems"] and res["unit_bad"] == 0
          and res["ladder"].get("fuzzy", 0) == 0 and res["ladder"].get("unmatched", 0) == 0)
    print("ผล:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
