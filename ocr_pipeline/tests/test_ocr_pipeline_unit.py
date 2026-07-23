# -*- coding: utf-8 -*-
"""Unit tests (S6): normalize_name, money, matching ladder (รวม tie-break), derive จากรหัส"""
from ocr_pipeline.build_reference import derive, level_and_parent
from ocr_pipeline.normalize import Reference, normalize_name
from ocr_pipeline.parse import clean, money

REF_DIR = "ocr_pipeline/reference"


# ---------------------------------------------------------------- normalize_name (§5.1)

def test_normalize_removes_markup_and_whitespace():
    assert normalize_name("**รวมสินทรัพย์**") == "รวมสินทรัพย์"
    assert normalize_name("<b>เงินสด</b> ใน มือ") == "เงินสดในมือ"


def test_normalize_thai_digits():
    assert normalize_name("ปีที่ ๒๕๖๗") == "ปีที่2567"


def test_normalize_heals_broken_glyph():
    # text layer ผังบัญชีมี combining mark แตกจากคำ เช่น "สินทรัพย ์"
    assert normalize_name("สินทรัพย ์") == "สินทรัพย์"
    # ◌ํ + า (0E4D 0E32) ต้องรวมเป็น ำ (0E33) — "กําหนด" ในผัง vs "กำหนด" ใน OCR
    assert normalize_name("กําหนด") == "กำหนด"


def test_normalize_strips_trailing_punct():
    assert normalize_name("ค่าใช้จ่ายอื่น.") == "ค่าใช้จ่ายอื่น"
    assert normalize_name("รวมรายได้ *") == "รวมรายได้"


# ---------------------------------------------------------------- money (ตรรกะ v1 คงไว้)

def test_money_basic():
    assert money("266,235,855.98") == 266235855.98
    assert money("-") == 0.0
    assert money("(1,234.00)") == -1234.0
    assert money("หมายเหตุ") is None
    assert money("(หน่วย:บาท) 2566") is None


def test_clean_translates_thai_digits_for_money():
    assert money(clean("๑,๒๓๔.๕๐")) == 1234.5


# ---------------------------------------------------------------- derive จากโครงรหัส (§5.2)

def test_level_and_parent():
    assert level_and_parent("1000000000") == (1, "")
    assert level_and_parent("1100000000") == (2, "1000000000.000")
    assert level_and_parent("1101000000") == (3, "1100000000.000")
    assert level_and_parent("1101010101") == (6, "1101010100.000")


def test_derive_statement_category():
    assert derive("1101010101") == ("งบแสดงฐานะการเงิน", "สินทรัพย์หมุนเวียน")
    assert derive("2200000000") == ("งบแสดงฐานะการเงิน", "หนี้สินไม่หมุนเวียน")
    assert derive("3102000000") == ("งบแสดงฐานะการเงิน", "สินทรัพย์สุทธิ_ส่วนทุน")
    assert derive("4402010000") == ("งบแสดงผลการดำเนินงาน", "รายได้")
    assert derive("5105000000") == ("งบแสดงผลการดำเนินงาน", "ค่าใช้จ่าย")


# ---------------------------------------------------------------- matching ladder (§5.4, D6)

def test_ladder_exact_pseudo():
    ref = Reference(REF_DIR)
    m = ref.match("รวมสินทรัพย์")
    assert m["method"] == "exact" and m["code"] == "TOTAL:1000000000"
    # NET:SURPLUS ชนะชื่อผัง postable ที่สะกดเหมือนกัน (pseudo canonical มีสิทธิ์ก่อน)
    m = ref.match("รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ")
    assert m["code"] == "NET:SURPLUS"


def test_ladder_exact_postable():
    ref = Reference(REF_DIR)
    m = ref.match("หนี้สินหมุนเวียนอื่น")
    assert m["method"] == "exact" and m["code"].startswith("2116")


def test_ladder_alias():
    ref = Reference(REF_DIR)
    m = ref.match("ลูกหนี้การค้า")
    assert m["method"] == "alias" and m["code"] == "1102000000.000"
    m = ref.match("เงินสดและรายการเทียบเท่าเงินสด")
    assert m["method"] == "alias" and m["code"] == "1101000000.000"


def test_ladder_fuzzy_accept():
    # ชุดเต็มหน้า 09 พิมพ์ไม่มีเครื่องหมาย '/' — ต้องเข้า fuzzy (score ≥ 92, margin ≥ 3)
    ref = Reference(REF_DIR)
    m = ref.match("รายได้สูง(ต่ำ)กว่าค่าใช้จ่ายสะสม")
    assert m["method"] == "fuzzy" and m["code"] == "3102000000.000"
    assert m["score"] >= 92


def test_ladder_fuzzy_margin_tiebreak_rejects():
    # "สำหรับงวด" (งบแสดงการเปลี่ยนแปลงฯ) อยู่กึ่งกลางระหว่าง สะสม/สุทธิ → ห้ามเดา
    ref = Reference(REF_DIR)
    m = ref.match("รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสำหรับงวด")
    assert m["method"] == "unmatched" and m["code"] is None
    assert len(m["candidates"]) == 3          # top-3 ส่งเข้า review queue


def test_ladder_unmatched_garbage():
    ref = Reference(REF_DIR)
    m = ref.match("ยอดคงเหลือ ณ วันที่ 30 กันยายน 2567")
    assert m["method"] == "unmatched"


def test_resolve_canonical_consistency():
    # ชื่อ canonical ที่ emit + ชื่อในเอกสาร/gold ของรายการเดียวกัน ต้องได้รหัสเดียวกัน
    ref = Reference(REF_DIR)
    assert ref.resolve_canonical("ที่ดิน") == ref.resolve_canonical("ที่ดิน อาคาร และอุปกรณ์ - สุทธิ")
    assert ref.resolve_canonical("รวมสินทรัพย์") == "TOTAL:1000000000"
