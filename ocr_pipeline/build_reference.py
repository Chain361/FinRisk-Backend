# -*- coding: utf-8 -*-
"""S1 — สกัดผังบัญชี e-LAAS (PDF มี text layer) → reference/chart_of_accounts.csv

    python -m ocr_pipeline.build_reference ผังบัญชี.pdf --out ocr_pipeline/reference/

ห้าม OCR — ใช้ pdfplumber อ่าน text layer ตรง ๆ (spec §1, §5.2)
ชื่อบัญชี = ข้อความหลังรหัสจนถึง "หมายถึง" หรือจบบรรทัด (คำอธิบายพันหลายบรรทัด — ตัดทิ้ง)
"""
import argparse
import csv
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


from ocr_pipeline.normalize import clean_display

CODE_RE = re.compile(r"^(\d{10})\.(\d{3})\s*(.*)$")
PAGE_HEADER_RE = re.compile(r"^-\s*\d+\s*-$")

# โครงรหัส 10 หลัก: d1 | d2 | d3d4 | d5d6 | d7d8 | d9d10 (level ตามตำแหน่ง trailing zeros)
def _groups(main: str):
    return [main[0], main[1], main[2:4], main[4:6], main[6:8], main[8:10]]


def level_and_parent(main: str):
    g = _groups(main)
    last = max((i for i, x in enumerate(g) if int(x) != 0), default=0)
    level = last + 1
    if last == 0:
        return level, ""
    parent = "".join(g[:last] + ["0" * len(x) for x in g[last:]])
    return level, parent + ".000"


def derive(main: str):
    """(statement_type, category) จากโครงรหัส — design doc §3.2 (หัวใจที่เลิกพึ่ง layout)"""
    d1, p2 = main[0], main[:2]
    st = {"1": "งบแสดงฐานะการเงิน", "2": "งบแสดงฐานะการเงิน", "3": "งบแสดงฐานะการเงิน",
          "4": "งบแสดงผลการดำเนินงาน", "5": "งบแสดงผลการดำเนินงาน"}[d1]
    if p2 == "11":
        cat = "สินทรัพย์หมุนเวียน"
    elif p2 == "12":
        cat = "สินทรัพย์ไม่หมุนเวียน"
    elif p2 == "21":
        cat = "หนี้สินหมุนเวียน"
    elif p2 == "22":
        cat = "หนี้สินไม่หมุนเวียน"
    elif d1 == "1":
        cat = "สินทรัพย์รวม"       # 1000000000 root
    elif d1 == "2":
        cat = "หนี้สินรวม"         # 2000000000 root
    elif d1 == "3":
        cat = "สินทรัพย์สุทธิ_ส่วนทุน"
    elif d1 == "4":
        cat = "รายได้"
    else:
        cat = "ค่าใช้จ่าย"
    return st, cat


def extract_chart(pdf_path: str):
    import pdfplumber
    rows = []
    seen = set()
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if PAGE_HEADER_RE.match(line):          # ข้าม header หน้า "- N -"
                    continue
                m = CODE_RE.match(line)
                if not m:
                    continue
                main, suffix, rest = m.groups()
                code = f"{main}.{suffix}"
                if code in seen:
                    continue
                seen.add(code)
                name = clean_display(rest.split("หมายถึง")[0])
                level, parent = level_and_parent(main)
                st, cat = derive(main)
                rows.append({
                    "account_code": code, "account_name": name,
                    "level": level, "parent_code": parent,
                    "statement_type": st, "category": cat,
                    "postable": 1 if suffix != "000" else 0,
                })
    rows.sort(key=lambda r: r["account_code"])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True, help="โฟลเดอร์ reference/")
    args = ap.parse_args()

    rows = extract_chart(args.pdf)
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "chart_of_accounts.csv")
    cols = ["account_code", "account_name", "level", "parent_code",
            "statement_type", "category", "postable"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    by_digit = Counter(r["account_code"][0] for r in rows)
    missing = [r for r in rows if not r["statement_type"] or not r["category"]]
    print(f"สกัดได้ {len(rows)} รหัส -> {out_path}")
    print("แบ่งตามหลักแรก:", dict(sorted(by_digit.items())))
    if missing:
        sys.exit(f"มี {len(missing)} แถว derive statement/category ไม่ได้")


if __name__ == "__main__":
    main()
