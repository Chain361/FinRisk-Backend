# -*- coding: utf-8 -*-
"""
เทสต์ชั้นกฎหมาย + ชั้นเอกสาร (docs/legal_linkage_plan.md ข้อ 4)

ยืนยัน 3 เรื่องหลัก:
  1. payload มี `computable` และแยก "ไม่เสี่ยง" ออกจาก "ประเมินไม่ได้"
  2. scope guard ทำงาน (โครงการ MOCK อยู่ตำบลโยนก → ตำบลอื่นเข้าไม่ได้ 403)
  3. mock 2 โครงการให้ผลตามสถานการณ์ที่ออกแบบ (A1+L3 / D1+L1+L2)
"""
from fastapi.testclient import TestClient

from src.main import app
from src.services.legal import NO_LEGAL_MAPPING_NOTE

client = TestClient(app)

ADMIN = {"X-Username": "admin"}
THACHANG = {"X-Username": "thachang_user"}  # local_executive ตำบลท่าช้าง (scoped)
MOCK_FULL = "MOCK-CON-001"    # เอกสารครบ แต่มี findings 3 จุด → A1 + L3
MOCK_MISSING = "MOCK-CON-002"  # ขาด ปร.4/5/6 + นอกเขตอำนาจ → D1 + L1 + L2


def _factors(project_id, headers=ADMIN, **params):
    r = client.get(f"/risk/projects/{project_id}/legal", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {f["factor_code"]: f for f in r.json()}


def test_laws_reference():
    r = client.get("/legal/laws", headers=ADMIN)
    assert r.status_code == 200
    laws = r.json()
    assert len(laws) == 6
    assert sum(len(law["sections"]) for law in laws) == 9
    by_code = {law["law_code"]: law for law in laws}
    # ตัวบทห้ามแบ่งซื้อแบ่งจ้างอยู่ใน "ระเบียบ" กค. 2560 ข้อ 20 (ไม่ใช่ พรบ.)
    mof = by_code["MOF-REG2560"]
    assert mof["law_type"] == "ระเบียบ"
    assert [s["section_no"] for s in mof["sections"]] == ["ข้อ 20"]
    # พรบ.ป่าไม้/ป่าสงวน แยกเป็น 2 ฉบับ และใช้ 'ทั้งฉบับ' (ไฟล์ case ไม่ระบุมาตรา)
    for code in ("FOREST2484", "FOREST2507"):
        assert [s["section_no"] for s in by_code[code]["sections"]] == ["ทั้งฉบับ"]


def test_laws_requires_auth():
    assert client.get("/legal/laws").status_code == 401


def test_document_types_reference():
    r = client.get("/documents/types", headers=ADMIN)
    assert r.status_code == 200
    types = {t["doc_type_code"]: t for t in r.json()}
    assert set(types) == {"PR4", "PR5", "PR6"}
    assert all(t["required_for_project_type"] == "จ้างก่อสร้าง" for t in types.values())
    # ปร.5/ปร.6 เป็นเอกสารที่ระบุ "ราคากลาง" (ตอบคำถาม chatbot ข้อ 2)
    assert "ราคากลาง" in types["PR5"]["provides"]
    assert "ราคากลาง" in types["PR6"]["provides"]
    assert "ราคากลาง" not in types["PR4"]["provides"]


def test_mock_missing_docs_triggers_d1_l1_l2_with_legal_refs():
    factors = _factors(MOCK_MISSING)
    for code in ("D1", "L1", "L2"):
        assert factors[code]["triggered"] == 1, code
        assert factors[code]["computable"] == 1, code
        assert factors[code]["legal_refs"], f"{code} ต้องมีข้อกฎหมายผูกไว้"
        assert factors[code]["action_suggestion"]

    # D1 ต้องอ้าง ม.48 + ระเบียบ กค. ข้อ 20 + พรบ.ฮั้ว ม.11/ม.12
    d1 = {(r["law_code"], r["section_no"]) for r in factors["D1"]["legal_refs"]}
    assert d1 == {
        ("FDA2561", "มาตรา 48"),
        ("MOF-REG2560", "ข้อ 20"),
        ("BID2542", "มาตรา 11"),
        ("BID2542", "มาตรา 12"),
    }
    # L2 อ้างกฎหมายป่าไม้ทั้ง 2 ฉบับ
    assert {r["law_code"] for r in factors["L2"]["legal_refs"]} == {"FOREST2484", "FOREST2507"}

    # L3 ของโครงการนี้ประเมินไม่ได้ (ไม่มีเอกสาร present) — ต้องไม่ใช่ triggered=0 เฉย ๆ
    assert factors["L3"]["computable"] == 0
    assert factors["L3"]["triggered"] == 0
    assert factors["L3"]["evidence_text"]


def test_mock_full_docs_triggers_a1_l3_and_carries_findings():
    factors = _factors(MOCK_FULL)
    assert factors["A1"]["triggered"] == 1
    assert factors["L1"]["triggered"] == 0 and factors["L1"]["computable"] == 1
    assert factors["L2"]["triggered"] == 0

    l3 = factors["L3"]
    assert l3["triggered"] == 1
    assert len(l3["findings"]) == 3
    assert all(f["legal_refs"] for f in l3["findings"])
    categories = {f["risk_category"] for f in l3["findings"]}
    assert categories == {
        "ปริมาณงาน/ราคากลางเกินจริง",
        "การคำนวณราคากลางคลาดเคลื่อน",
        "เอกสารไม่ครบถ้วน/ตรวจสอบย้อนกลับไม่ได้",
    }
    # ปริมาณงานเกินจริง 1,850 vs 1,600 ตร.ม.
    qty = next(f for f in l3["findings"] if f["risk_category"] == "ปริมาณงาน/ราคากลางเกินจริง")
    assert qty["observed_value"] == "1,850 ตร.ม." and qty["expected_value"] == "1,600 ตร.ม."


def test_unmapped_factor_gets_fixed_note_not_invented_law():
    """A2/A3 ยังไม่ curate mapping (v1) → ต้องส่งข้อความตายตัว ไม่ปล่อยให้ LLM เดามาตรา"""
    projects = client.get("/projects", headers=ADMIN, params={"risk_level": "high"}).json()
    found = False
    for p in projects:
        for code, f in _factors(p["project_id"]).items():
            if f["triggered"] and not f["legal_refs"]:
                assert f["legal_ref_note"] == NO_LEGAL_MAPPING_NOTE, code
                found = True
        if found:
            break
    assert found, "seed ต้องมี factor ที่ triggered แต่ยังไม่มี mapping กฎหมาย"


def test_only_triggered_filter():
    all_f = _factors(MOCK_MISSING)
    only = _factors(MOCK_MISSING, only_triggered=True)
    assert set(only) == {c for c, f in all_f.items() if f["triggered"]}
    assert set(only) == {"D1", "L1", "L2"}


def test_documents_view_missing_list_and_provides_index():
    r = client.get(f"/projects/{MOCK_MISSING}/documents", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["required_doc_types"] == ["PR4", "PR5", "PR6"]
    assert body["has_document_data"] is True
    assert {m["doc_type_code"] for m in body["missing_doc_types"]} == {"PR4", "PR5", "PR6"}
    assert all(m["reason"] == "missing" for m in body["missing_doc_types"])
    assert body["findings_count"] == 0
    # "เอกสารใดระบุราคากลาง" → ปร.5 + ปร.6 (พร้อมสถานะว่าขาด)
    price_docs = body["provides_index"]["ราคากลาง"]
    assert {d["doc_type_code"] for d in price_docs} == {"PR5", "PR6"}
    assert all(d["status"] == "missing" for d in price_docs)


def test_documents_view_present_docs_with_findings():
    body = client.get(f"/projects/{MOCK_FULL}/documents", headers=ADMIN).json()
    assert body["missing_doc_types"] == []
    assert body["findings_count"] == 3
    docs = {d["doc_type_code"]: d for d in body["documents"]}
    assert all(d["status"] == "present" and d["source"] == "mock" for d in docs.values())
    assert docs["PR5"]["extracted"]["ราคากลาง"] == 5200000
    assert docs["PR5"]["extracted"]["factor_f"] == 1.3061
    assert len(docs["PR4"]["findings"]) == 1
    assert docs["PR4"]["findings"][0]["legal_refs"][0]["section_no"] == "มาตรา 6"
    # badge MOCK ให้ frontend แยกออกจากข้อมูลจริง (Mission §6.1)
    assert body["data_quality_note"] == "MOCK สำหรับเดโม legal linkage"


def test_real_construction_project_has_no_document_data():
    """โครงการก่อสร้างจริงยังไม่มีข้อมูลเอกสาร → computable=0 ไม่ใช่ 'ขาดเอกสาร'"""
    real = next(
        p
        for p in client.get("/projects", headers=ADMIN).json()
        if p["project_type"] == "จ้างก่อสร้าง" and not p["project_id"].startswith("MOCK-")
    )
    body = client.get(f"/projects/{real['project_id']}/documents", headers=ADMIN).json()
    assert body["has_document_data"] is False
    assert body["documents"] == []
    # missing_doc_types บอกว่า "ไม่มีบันทึก" (no_record) แยกจาก "บันทึกว่าขาด"
    assert all(m["reason"] == "no_record" for m in body["missing_doc_types"])

    factors = _factors(real["project_id"])
    for code in ("L1", "L2", "L3"):
        assert factors[code]["computable"] == 0, code
        assert factors[code]["triggered"] == 0, code


def test_non_construction_project_has_no_l_factors():
    """gate ตาม applies_to_project_type → โครงการประเภทอื่นไม่มีแถวผล L1–L3"""
    other = next(
        p
        for p in client.get("/projects", headers=ADMIN).json()
        if p["project_type"] and p["project_type"] != "จ้างก่อสร้าง"
    )
    factors = _factors(other["project_id"])
    assert not {"L1", "L2", "L3"} & set(factors)
    body = client.get(f"/projects/{other['project_id']}/documents", headers=ADMIN).json()
    assert body["required_doc_types"] == []


def test_scope_guard_blocks_other_subdistrict():
    # MOCK อยู่ตำบลโยนก — local_executive ของท่าช้างต้องถูกกัน 403 ทั้ง 2 endpoint
    assert client.get(f"/risk/projects/{MOCK_FULL}/legal", headers=THACHANG).status_code == 403
    assert client.get(f"/projects/{MOCK_FULL}/documents", headers=THACHANG).status_code == 403
    # โยนกเข้าถึงได้
    yonok = next(
        u for u in ("yonok_user", "admin")
        if client.get(f"/risk/projects/{MOCK_FULL}/legal", headers={"X-Username": u}).status_code == 200
    )
    assert yonok


def test_unknown_project_404():
    assert client.get("/risk/projects/NO-SUCH/legal", headers=ADMIN).status_code == 404
    assert client.get("/projects/NO-SUCH/documents", headers=ADMIN).status_code == 404


def test_access_log_resource_mapping():
    """accountability trail ต้องชี้ resource ได้ถูกต้องสำหรับ endpoint ใหม่"""
    from src.audit_log import derive_action_resource

    assert derive_action_resource("GET", "/legal/laws") == ("view_list", "legal", "laws")
    assert derive_action_resource("GET", "/documents/types") == (
        "view_list",
        "document",
        "types",
    )
    # id ซ้อนชั้นที่ 3 — ต้องบันทึก project_id ไม่ใช่คำว่า 'projects'
    assert derive_action_resource("GET", f"/risk/projects/{MOCK_FULL}/legal") == (
        "view_detail",
        "project",
        MOCK_FULL,
    )


def test_error_debug_log_sanitizes_sensitive_text():
    from src.error_log import sanitize_log_text

    sanitized = sanitize_log_text(
        "failed password=secret123 token=abc person@example.com tin 1234567890123"
    )
    assert "secret123" not in sanitized
    assert "abc" not in sanitized
    assert "person@example.com" not in sanitized
    assert "1234567890123" not in sanitized
    assert "[EMAIL]" in sanitized
    assert "[NUMBER]" in sanitized
    assert "[MASKED]" in sanitized


def test_existing_project_endpoint_untouched():
    """endpoint เดิมต้องไม่เปลี่ยน shape (legal linkage เป็น layer เสริม)"""
    body = client.get(f"/projects/{MOCK_FULL}", headers=ADMIN).json()
    assert set(body) == {"project", "risk_score", "risk_factors"}
    assert "legal_refs" not in body["risk_factors"][0]
