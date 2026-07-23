# -*- coding: utf-8 -*-
"""Stage 3 — Normalize: matching ladder (exact → alias → fuzzy → unmatched)

ผังบัญชี e-LAAS (reference/chart_of_accounts.csv) = source of truth เดียวของ
ชื่อ canonical / statement_type / category / detail_level (spec §5.1–§5.4)
unmatched ห้ามหลุดเข้า output — ไปที่ review/queue.csv เท่านั้น (D5)
"""
import csv
import os
import re

# ---------------------------------------------------------------- normalize_name (§5.1)

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
# สระบน/ล่าง + วรรณยุกต์ + ทัณฑฆาต + นิคหิต (combining marks ที่ text layer ผังบัญชีแตก glyph)
_COMBINING = "ัิีึืฺุู็่้๊๋์ํ๎"


def _heal(s: str) -> str:
    """ประสาน glyph ที่แตก: 'สินทรัพย ์' → 'สินทรัพย์', 'กํ'+'า' (0E4D+0E32) → 'กำ' (0E33)"""
    s = re.sub(r"\s+([" + _COMBINING + r"])", r"\1", s)
    return s.replace("ํา", "ำ")


def normalize_name(s: str) -> str:
    """key สำหรับเทียบชื่อ — ใช้ทุกจุด (build reference + runtime) ห้ามใช้เขียน output"""
    s = re.sub(r"<[^>]+>", "", s.replace("**", ""))   # 1) ลบ ** และ tag HTML
    s = s.translate(THAI_DIGITS)                      # 2) เลขไทย → อารบิก
    s = re.sub(r"\s+", "", s)                         # 3) ลบ whitespace ทั้งหมด
    s = _heal(s)
    return s.rstrip(".,*")                            # 4) ลบ . , * ท้ายชื่อ


def clean_display(s: str) -> str:
    """ชื่อสำหรับแสดงผล/เขียน reference — คง space เดียวระหว่างคำ + ประสาน glyph"""
    s = re.sub(r"\s+", " ", s.replace("**", "")).strip()
    return _heal(s)


# ---------------------------------------------------------------- pseudo-codes (§5.3 — ตารางปิดแล้ว)

BS, PL = "งบแสดงฐานะการเงิน", "งบแสดงผลการดำเนินงาน"

PSEUDO_CODES = {
    "TOTAL:1100000000": ("รวมสินทรัพย์หมุนเวียน", "สินทรัพย์หมุนเวียน", "subtotal", BS),
    "TOTAL:1200000000": ("รวมสินทรัพย์ไม่หมุนเวียน", "สินทรัพย์ไม่หมุนเวียน", "subtotal", BS),
    "TOTAL:1000000000": ("รวมสินทรัพย์", "สินทรัพย์รวม", "total", BS),
    "TOTAL:2100000000": ("รวมหนี้สินหมุนเวียน", "หนี้สินหมุนเวียน", "subtotal", BS),
    "TOTAL:2200000000": ("รวมหนี้สินไม่หมุนเวียน", "หนี้สินไม่หมุนเวียน", "subtotal", BS),
    "TOTAL:2000000000": ("รวมหนี้สิน", "หนี้สินรวม", "total", BS),
    "TOTAL:3000000000": ("รวมสินทรัพย์สุทธิ/ส่วนทุน", "สินทรัพย์สุทธิ_ส่วนทุน", "subtotal", BS),
    "TOTAL:LIAB_EQUITY": ("รวมหนี้สินและสินทรัพย์สุทธิ/ส่วนทุน", "หนี้สินและส่วนทุนรวม", "total", BS),
    "TOTAL:4000000000": ("รวมรายได้", "รายได้รวม", "total", PL),
    "TOTAL:5000000000": ("รวมค่าใช้จ่าย", "ค่าใช้จ่ายรวม", "total", PL),
    "NET:SURPLUS": ("รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ", "สรุปผล", "total", PL),
    "SUBTOTAL:PERSONNEL": ("รวมค่าใช้จ่ายบุคลากร (เงินเดือน+บำนาญ+ค่าตอบแทน)", "ค่าใช้จ่าย", "subtotal", PL),
}


# ---------------------------------------------------------------- reference

class Reference:
    """โหลด chart_of_accounts.csv + account_aliases.csv แล้วให้บริการ matching ladder"""

    def __init__(self, ref_dir: str):
        self.ref_dir = ref_dir
        self.coa = {}          # account_code -> row dict
        self.exact = {}        # normalize_name(ชื่อผัง postable | canonical pseudo) -> code
        self.alias = {}        # alias_normalized -> target_code
        with open(os.path.join(ref_dir, "chart_of_accounts.csv"), encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                self.coa[r["account_code"]] = r
        # exact ชั้น 1: ชื่อผังเฉพาะ postable (§5.4) — collision: คงรหัสแรก (เรียงตามไฟล์ = ตามรหัส)
        for code, r in self.coa.items():
            if r["postable"] == "1":
                self.exact.setdefault(normalize_name(r["account_name"]), code)
        # exact ชั้น 1: canonical_name ของ pseudo-code
        for code, (canon, _cat, _dl, _st) in PSEUDO_CODES.items():
            self.exact[normalize_name(canon)] = code
        alias_path = os.path.join(ref_dir, "account_aliases.csv")
        if os.path.exists(alias_path):
            with open(alias_path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    self.alias[r["alias_normalized"]] = r["target_code"]
        # candidates สำหรับ fuzzy = ทุก key จากชั้น 1 + 2 (§5.4 ข้อ 3)
        self.candidates = dict(self.exact)
        for k, v in self.alias.items():
            self.candidates.setdefault(k, v)
        # index ชื่อผังทุกระดับ (รวม non-postable) — ใช้เฉพาะงาน internal:
        # resolve ชื่อ canonical ที่ emit แล้วกลับเป็น code (evaluate/validate/cross-check)
        # ไม่ใช่ส่วนหนึ่งของ matching ladder ของชื่อจากเอกสาร (§5.4)
        self.canonical_all = {}
        for code in sorted(self.coa):
            self.canonical_all.setdefault(normalize_name(self.coa[code]["account_name"]), code)
        for code, (canon, _cat, _dl, _st) in PSEUDO_CODES.items():
            self.canonical_all[normalize_name(canon)] = code

    # -------------------------------------------------- attributes จาก reference เท่านั้น (§5.4)

    def attrs(self, code: str):
        """(canonical_name, statement_type, category, detail_level) ของ code ที่ match แล้ว"""
        if code in PSEUDO_CODES:
            canon, cat, dl, st = PSEUDO_CODES[code]
            return canon, st, cat, dl
        r = self.coa[code]
        return r["account_name"], r["statement_type"], r["category"], "line_item"

    def resolve_canonical(self, name: str):
        """ชื่อ canonical (จาก out.csv/gold) → code — deterministic, ไม่ใช้ fuzzy

        ใช้เป็น "คีย์เทียบ" ระหว่างไฟล์ (evaluate L1/L2, cross-run/cross-year):
        ชื่อผังทุกระดับก่อน (เรียงตามรหัส — กันชื่อซ้ำข้ามระดับ เช่น 'ที่ดิน')
        แล้วจึง alias (ชื่อสไตล์เอกสาร) — ชื่อเดียวกัน resolve เป็นรหัสเดียวกันเสมอ
        ไม่ว่าจะมาจากเอกสาร, gold, หรือ out.csv"""
        k = normalize_name(name)
        return self.canonical_all.get(k) or self.exact.get(k) or self.alias.get(k)

    # -------------------------------------------------- matching ladder (§5.4)

    def match(self, raw_name: str, threshold: int = 92, margin: int = 3) -> dict:
        """คืน {method, code, score, candidates} — method ∈ exact|alias|fuzzy|unmatched"""
        k = normalize_name(raw_name)
        if k in self.exact:
            return {"method": "exact", "code": self.exact[k], "score": 100, "candidates": []}
        if k in self.alias:
            return {"method": "alias", "code": self.alias[k], "score": 100, "candidates": []}
        from rapidfuzz import fuzz
        scored = sorted(
            ((fuzz.ratio(k, cand), cand, code) for cand, code in self.candidates.items()),
            reverse=True,
        )
        top3 = [{"name": c, "code": code, "score": round(s, 1)} for s, c, code in scored[:3]]
        if scored:
            s1, _c1, code1 = scored[0]
            # margin เทียบกับ candidate ที่ชี้ไป "คนละรหัส" (คีย์หลายตัวของรหัสเดียวกันไม่ใช่ความกำกวม)
            s2 = next((s for s, _c, code in scored[1:] if code != code1), 0.0)
            if s1 >= threshold and (s1 - s2) >= margin:
                return {"method": "fuzzy", "code": code1, "score": round(s1, 1), "candidates": top3}
        return {"method": "unmatched", "code": None, "score": None, "candidates": top3}


def normalize_rows(parsed_rows, ref: Reference, threshold: int = 92, margin: int = 3):
    """แปลง raw rows จาก parse → (matched, review)

    matched: ผูก account_code แล้ว attrs มาจาก reference เท่านั้น + dedup ตาม (statement, code)
    review: unmatched + แถวจากงบที่ไม่อยู่ใน scope (D1) — ห้ามเข้า output (D5)
    """
    matched, review, seen = [], [], set()
    for row in parsed_rows:
        if row["statement_hint"] == "OTHER":
            review.append({**row, "reason": "unsupported_statement", "candidates": []})
            continue
        m = ref.match(row["raw_name"], threshold, margin)
        if m["method"] == "unmatched":
            review.append({**row, "reason": "unmatched", "candidates": m["candidates"]})
            continue
        canon, st, cat, dl = ref.attrs(m["code"])
        key = (st, m["code"])
        if key in seen:                       # ตารางซ้ำข้ามหน้า — คงแถวแรก
            continue
        seen.add(key)
        matched.append({
            "code": m["code"], "canonical": canon, "statement_type": st,
            "category": cat, "detail_level": dl,
            "value": row["values"][0],
            "prior_value": row["values"][1] if len(row["values"]) > 1 else None,
            "note": row["note"], "page": row["page"], "raw_name": row["raw_name"],
            "layout_hint": row.get("layout_hint", ""),
            "method": m["method"], "score": m["score"],
        })
    return matched, review
