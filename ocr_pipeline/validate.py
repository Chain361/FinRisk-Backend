# -*- coding: utf-8 -*-
"""Stage 4 — Validate (gate): สมการบัญชี + coverage + cross-year/cross-run (spec §6)

สถานะ 3 ระดับ:
  pass         ทุกสมการผ่าน + unmatched=0 + fuzzy_pct ≤ เกณฑ์
  needs_review สมการขาดแถว (เอกสารสรุป — D4) / fuzzy/coverage เกินเกณฑ์ / มีแถวถูกกักไว้ review
  fail         สมการที่มีครบทุกแถวแต่ไม่ลงตัว
ห้าม auto-fix — แถวที่สงสัยส่ง review เท่านั้น (precision-first)

โหมด standalone (ใช้กับ out.csv ที่ emit แล้ว — S4b/S4c):
    python -m ocr_pipeline.validate ocr_pipeline/work/<run_id>/out.csv
"""
import argparse
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


BS, PL = "งบแสดงฐานะการเงิน", "งบแสดงผลการดำเนินงาน"

# category → pseudo-code ของยอดรวมประจำหมวด (check ข้อ 1)
CATEGORY_TOTAL = {
    (BS, "สินทรัพย์หมุนเวียน"): "TOTAL:1100000000",
    (BS, "สินทรัพย์ไม่หมุนเวียน"): "TOTAL:1200000000",
    (BS, "หนี้สินหมุนเวียน"): "TOTAL:2100000000",
    (BS, "หนี้สินไม่หมุนเวียน"): "TOTAL:2200000000",
    (BS, "สินทรัพย์สุทธิ_ส่วนทุน"): "TOTAL:3000000000",
    (PL, "รายได้"): "TOTAL:4000000000",
    (PL, "ค่าใช้จ่าย"): "TOTAL:5000000000",
}
# สมการยอดรวม (check ข้อ 2–5): (ชื่อ, [ฝั่งซ้าย (code, sign)], ฝั่งขวา)
TOTAL_EQUATIONS = [
    ("สินทรัพย์หมุนเวียน + ไม่หมุนเวียน = รวมสินทรัพย์",
     [("TOTAL:1100000000", 1), ("TOTAL:1200000000", 1)], "TOTAL:1000000000"),
    ("รวมหนี้สิน + รวมสินทรัพย์สุทธิ/ส่วนทุน = รวมหนี้สินและสินทรัพย์สุทธิ/ส่วนทุน",
     [("TOTAL:2000000000", 1), ("TOTAL:3000000000", 1)], "TOTAL:LIAB_EQUITY"),
    ("สมการบัญชี: รวมสินทรัพย์ = หนี้สิน+ทุน",
     [("TOTAL:1000000000", 1)], "TOTAL:LIAB_EQUITY"),
    ("รวมรายได้ − รวมค่าใช้จ่าย = รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ",
     [("TOTAL:4000000000", 1), ("TOTAL:5000000000", -1)], "NET:SURPLUS"),
]


def check_equations(matched, quarantined_keys=(), tol: float = 0.01):
    """คืน (checks, status_equations) — matched: rows ที่มี code/value/detail/category แล้ว

    quarantined_keys: (statement, category) ที่มี line_item ถูกกักไป review →
    สมการของหมวดนั้นถือว่า "ขาดแถว" (needs_review) ไม่ใช่ fail
    """
    val = {r["code"]: float(r["value"]) for r in matched}
    line_sum, line_count = defaultdict(float), defaultdict(int)
    for r in matched:
        if r["detail_level"] == "line_item":
            k = (r["statement_type"], r["category"])
            line_sum[k] += float(r["value"])
            line_count[k] += 1

    checks = []

    # 1) Σ line_item ต่อ (งบ, category) = ยอดรวมประจำหมวด (เมื่อมี line_item)
    cats = {(r["statement_type"], r["category"]) for r in matched} | set(quarantined_keys)
    for key in sorted(cats):
        code = CATEGORY_TOTAL.get(key)
        if code is None:
            continue
        name = f"Σ line_item {key[1]} = ยอดรวมหมวด"
        if key in quarantined_keys:
            checks.append({"check": name, "result": "incomplete",
                           "detail": "มีแถวถูกกักไว้ review — สมการขาดแถว"})
        elif line_count[key] == 0 or code not in val:
            checks.append({"check": name, "result": "incomplete",
                           "detail": "ไม่มี line_item หรือไม่มีแถวยอดรวม (เอกสารแบบสรุป — D4)"})
        else:
            got, expect = line_sum[key], val[code]
            checks.append({"check": name, "result": "pass" if abs(got - expect) <= tol else "fail",
                           "expected": round(expect, 2), "got": round(got, 2)})

    # 2–5) สมการยอดรวม
    for name, lhs, rhs in TOTAL_EQUATIONS:
        if rhs not in val or any(c not in val for c, _s in lhs):
            checks.append({"check": name, "result": "incomplete", "detail": "แถวที่ต้องใช้หายไป"})
            continue
        got = sum(val[c] * s for c, s in lhs)
        expect = val[rhs]
        checks.append({"check": name, "result": "pass" if abs(got - expect) <= tol else "fail",
                       "expected": round(expect, 2), "got": round(got, 2)})
    return checks


def overall_status(checks, ladder, gate, quarantined: int = 0, cross_year_mismatch: int = 0) -> str:
    if any(c["result"] == "fail" for c in checks):
        return "fail"
    matched_n = sum(ladder.get(k, 0) for k in ("exact", "alias", "fuzzy"))
    fuzzy_pct = 100.0 * ladder.get("fuzzy", 0) / matched_n if matched_n else 0.0
    if (any(c["result"] == "incomplete" for c in checks)
            or ladder.get("unmatched", 0) > gate.get("max_unmatched", 0)
            or fuzzy_pct > gate.get("max_fuzzy_pct", 10)
            or quarantined > 0 or cross_year_mismatch > 0):
        return "needs_review"
    return "pass"


EXIT_CODE = {"pass": 0, "fail": 1, "needs_review": 2}


# ---------------------------------------------------------------- batch-level circuit breaker

def validate_batch(summary: dict) -> dict:
    """Circuit breaker ระดับ batch (ใช้โดย run_pipeline.py ก่อน promote ลง DB)

    นโยบาย "promote เฉพาะเอกสารที่ผ่าน gate":
    - เอกสาร fail/needs_review ถูกกันออกจาก merged CSV อยู่แล้ว (error isolation)
    - abort เมื่อไม่มีเอกสารใดถูก merge เลย (merged_rows == 0) — ไม่มีอะไรปลอดภัยพอจะเขียนลง DB

    รับ summary จาก batch.process_batch() → คืน {"ok", "reason", "promoted", "held_back", "pass_rate"}
    """
    runs = summary.get("runs", [])
    promoted = [r["run_id"] for r in runs if r.get("merged")]
    held_back = [{"run_id": r["run_id"], "status": r["status"]}
                 for r in runs if not r.get("merged")]
    pass_rate = round(100.0 * len(promoted) / len(runs), 1) if runs else 0.0
    if not runs:
        return {"ok": False, "reason": "batch ว่าง — ไม่มี job ใน batch.csv",
                "promoted": [], "held_back": [], "pass_rate": 0.0}
    if summary.get("merged_rows", 0) == 0 or not promoted:
        return {"ok": False,
                "reason": "ไม่มีเอกสารใดผ่าน gate (ทุกไฟล์ fail/needs_review) — ยกเลิกก่อนเขียน DB",
                "promoted": promoted, "held_back": held_back, "pass_rate": pass_rate}
    return {"ok": True, "reason": None,
            "promoted": promoted, "held_back": held_back, "pass_rate": pass_rate}


# ---------------------------------------------------------------- standalone (out.csv ที่ emit แล้ว)

def rows_from_csv(path: str, ref) -> list:
    """สร้าง matched rows จาก out.csv — resolve ชื่อ canonical กลับเป็น code ด้วย ladder เดิม"""
    import csv
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        code = ref.resolve_canonical(r["รายการบัญชี"])
        rows.append({
            "code": code if code else f"UNRESOLVED:{r['รายการบัญชี']}",
            "statement_type": r["ประเภทงบ"], "category": r["หมวดหมู่"],
            "detail_level": r["ระดับรายละเอียด"], "value": float(r["มูลค่า"]),
        })
    return rows


def main() -> None:
    from ocr_pipeline.normalize import Reference
    from ocr_pipeline.run import load_config

    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--config", default="ocr_pipeline/config.yaml")
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    ref = Reference(args.reference or cfg["paths"]["reference"])
    rows = rows_from_csv(args.csv_path, ref)
    checks = check_equations(rows, tol=cfg["gate"]["money_tol"])
    for c in checks:
        mark = {"pass": "[PASS]", "fail": "[FAIL]", "incomplete": "[REVIEW]"}[c["result"]]
        extra = (f" ({c['got']:,.2f} vs {c['expected']:,.2f})" if "got" in c else f" — {c.get('detail', '')}")
        print(f"{mark} {c['check']}{extra}")
    status = overall_status(checks, {"exact": len(rows)}, cfg["gate"])
    print(f"\nสถานะ: {status}")
    sys.exit(EXIT_CODE[status])


if __name__ == "__main__":
    main()
