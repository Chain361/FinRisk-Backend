# -*- coding: utf-8 -*-
"""Stage 2 — Parse "ตามที่พิมพ์": OCR markdown → raw rows (ชื่อดิบ, note, values[], page)

reuse ตรรกะ v1: pipe/HTML table parser, money() (วงเล็บ=ติดลบ, '-'=0, เลขไทย),
การแยกเลขหมายเหตุ (D2 — ตรวจจับกันปนคอลัมน์เงิน แต่ output เขียนว่างเสมอ),
การข้ามหน้า "หมายเหตุประกอบงบการเงิน"

เปลี่ยนจาก v1: section header เก็บเป็น layout_hint เท่านั้น — ไม่ใช้กำหนดหมวดหมู่ (§5.4)
งบนอก scope (D1) เช่น งบแสดงการเปลี่ยนแปลงสินทรัพย์สุทธิ/ส่วนทุน → statement_hint="OTHER"
"""
import glob
import os
import re

MONEY_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
NOTE_RE = re.compile(r"^\d{1,2}$")                     # เลขหมายเหตุ 1–2 หลัก (D2)
YEAR_RE = re.compile(r"^\d{4}$")                       # หัวคอลัมน์ปี พ.ศ. เช่น "2567"
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# ชื่องบใน PDF → ชื่อ canonical (เรียงยาว→สั้น เพื่อ match แบบ substring อย่างถูกต้อง)
STATEMENT_CANON = [
    ("งบแสดงผลการดำเนินงานทางการเงิน", "งบแสดงผลการดำเนินงาน"),
    ("งบแสดงผลการดำเนินงาน", "งบแสดงผลการดำเนินงาน"),
    ("งบแสดงฐานะการเงิน", "งบแสดงฐานะการเงิน"),
]
# งบที่อยู่นอก scope v2 (D1) — แถวใต้หัวนี้ห้ามเข้า output
OTHER_STATEMENT_MARKERS = ["งบแสดงการเปลี่ยนแปลง"]

# หัว section ในเอกสาร — เก็บเป็น layout_hint เท่านั้น (ห้ามใช้กำหนดหมวดหมู่)
SECTION_HINTS = {
    "สินทรัพย์หมุนเวียน", "สินทรัพย์ไม่หมุนเวียน", "หนี้สินหมุนเวียน",
    "หนี้สินไม่หมุนเวียน", "สินทรัพย์สุทธิ/ส่วนทุน", "รายได้", "ค่าใช้จ่าย",
}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("**", "").translate(THAI_DIGITS)).strip()


def money(s: str):
    """'266,235,855.98'→float | '-'→0.0 | '(1,234.00)'→-1234.0 | ไม่ใช่เงิน→None"""
    s = s.strip()
    if s == "-":
        return 0.0
    if not MONEY_RE.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()").replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def table_rows(md: str):
    """ดึงแถวจาก markdown pipe table และ HTML table (รองรับ output ทุก task_type)"""
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("|") and not re.match(r"^\|[\s:\-|]+\|$", line):
            yield [clean(c) for c in line.strip("|").split("|")]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", md, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        if cells:
            yield [clean(re.sub(r"<[^>]+>", " ", c)) for c in cells]


def _detect_statement(md: str, ctx: dict) -> bool:
    """อัปเดต ctx['statement'] จาก heading (บรรทัดสั้น < 120 ตัวอักษร — กันชื่องบในย่อหน้ารายงานผู้สอบ)
    คืน True เมื่อเจอ heading ของงบ (รวม OTHER) ในหน้านี้"""
    for line in md.splitlines():
        cl = clean(line)
        if not cl or len(cl) >= 120:
            continue
        if any(mk in cl for mk in OTHER_STATEMENT_MARKERS):
            if ctx.get("statement") != "OTHER":
                ctx["statement"] = "OTHER"
            return True
        for raw, canon in STATEMENT_CANON:
            if raw in cl:
                if ctx.get("statement") != canon:
                    ctx["statement"] = canon
                    ctx["layout_hint"] = ""
                return True
    return False


def parse_page(md: str, ctx: dict):
    """คืน list ของ raw row — ctx เก็บ statement/layout_hint ข้ามหน้า (งบเดียวกินหลายหน้า)"""
    # ข้ามหน้า "หมายเหตุประกอบงบการเงิน" (heading สั้น ≠ footer "เป็นส่วนหนึ่ง..." / ย่อหน้ารายงาน)
    for line in md.splitlines():
        cl = clean(line)
        if "หมายเหตุประกอบงบ" in cl and "เป็นส่วนหนึ่ง" not in cl and len(cl) < 120:
            ctx["is_notes"] = True
            return []
    if ctx.get("is_notes"):
        # เอกสารบางแห่งวาง "หมายเหตุประกอบงบ" ก่อนงบตัวเลข — เจอ heading งบอีกครั้ง → reset
        if _detect_statement(md, ctx) and ctx["statement"] != "OTHER":
            ctx["is_notes"] = False
        else:
            return []
    else:
        _detect_statement(md, ctx)
    if not ctx.get("statement"):
        return []

    out = []
    for cells in table_rows(md):
        cells = [c for c in cells if c != ""]
        if not cells:
            continue
        name = cells[0]
        # แยกเลขหมายเหตุ (ตัวแรกหลังชื่อ ก่อนเจอคอลัมน์เงิน) — D2
        note, values, raw_value_cells = "", [], []
        for c in cells[1:]:
            if not note and NOTE_RE.match(c) and not values:
                note = c
                continue
            v = money(c)
            if v is not None:
                values.append(v)
                raw_value_cells.append(c)

        if not values:                                  # หัว section / แถวขยะ → layout hint
            if name in SECTION_HINTS:
                ctx["layout_hint"] = name
            continue
        # แถวหัวตาราง (คอลัมน์ปี พ.ศ. ล้วน เช่น "| สินทรัพย์ | หมายเหตุ | 2567 | 2566 |")
        if all(YEAR_RE.match(c) for c in raw_value_cells):
            continue

        out.append({
            "raw_name": name, "note": note, "values": values,
            "page": ctx["page"], "statement_hint": ctx["statement"],
            "layout_hint": ctx.get("layout_hint", ""),
        })
    return out


def parse_ocr_dir(ocr_dir: str):
    """อ่าน page_NN.md ทั้งโฟลเดอร์ → (raw rows, จำนวนหน้า)"""
    ctx, rows = {}, []
    paths = sorted(glob.glob(os.path.join(ocr_dir, "page_*.md")))
    for path in paths:
        ctx["page"] = os.path.basename(path)[5:-3]
        with open(path, encoding="utf-8") as f:
            rows.extend(parse_page(f.read(), ctx))
    return rows, len(paths)
