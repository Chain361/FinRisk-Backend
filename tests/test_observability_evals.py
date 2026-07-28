# -*- coding: utf-8 -*-
"""
เทสต์ชั้น observability + evaluator (src/observability.py, evals/)

ทั้งไฟล์นี้ **ไม่แตะ DB และไม่ยิง API ใดๆ** จึงรันใน `pytest -q` ได้ตามปกติ
(ตัวที่ยิง Gemini/Pinecone จริงอยู่ที่ evals/run_*.py ซึ่งไม่ถูก collect — ดู pytest.ini)

ยืนยัน 3 เรื่อง:
  1. tracing ปิดอยู่ = decorator เป็น no-op จริง (feature flag ปิดได้จริง ไม่ใช่แค่ล้มเงียบ)
  2. redaction ตัด conn/username/display_name ออกจริง (ข้อมูลส่วนบุคคลต้องไม่ขึ้น cloud)
  3. evaluator M1–M4 ให้คะแนนตรงตามกติกาใน SYSTEM_PROMPT (จะถูกใช้เป็น merge gate)
"""
import json

import pytest

from evals.datasets_io import DATASETS_DIR, load_jsonl
from evals.evaluators import (
    citation_complete,
    extract_legal_refs,
    no_hallucinated_legal_ref,
    normalize_ref,
    scope_guard_holds,
    tool_selection_correct,
)
from src import observability as obs

USER = {
    "user_id": 7,
    "username": "auditor1",
    "display_name": "ผู้ตรวจสอบโครงการ ทต.ท่าช้าง",
    "role": "project_auditor",
    "subdistrict_id": 3,
}


# ── 1. feature flag ──────────────────────────────────────────────────────────
def test_traceable_is_noop_when_disabled(monkeypatch):
    """ปิด tracing → ต้องได้ฟังก์ชันเดิมกลับมา ไม่ใช่ wrapper (ไม่มี overhead เลย)"""
    monkeypatch.setattr(obs, "TRACING_ENABLED", False)

    def original(a, b):
        return a + b

    assert obs.traceable(run_type="tool", name="x")(original) is original


def test_wrap_gemini_returns_client_untouched_when_disabled(monkeypatch):
    monkeypatch.setattr(obs, "TRACING_ENABLED", False)
    client = object()
    assert obs.wrap_gemini(client) is client


# ── 2. redaction ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "redactor, payload",
    [
        (obs.redact_chat_inputs, {"conn": object(), "user": USER, "message": "hi", "history": []}),
        (obs.redact_tool_inputs, {"conn": object(), "user": USER, "name": "get_project", "args": {}}),
        (obs.redact_search_inputs, {"conn": object(), "user": USER, "query": "q"}),
    ],
)
def test_redaction_drops_connection_and_personal_data(redactor, payload):
    """conn serialize ไม่ได้ และ username/display_name เป็นข้อมูลส่วนบุคคลของเจ้าหน้าที่"""
    out = redactor(payload)
    blob = json.dumps(out, ensure_ascii=False)  # ต้อง serialize ได้ = ไม่มี conn ปนมา
    assert "conn" not in out
    assert "auditor1" not in blob
    assert "ผู้ตรวจสอบโครงการ" not in blob
    assert out["user"]["role"] == "project_auditor"  # สิ่งที่ยังต้องเก็บไว้วิเคราะห์


def test_verify_outputs_are_json_serializable():
    """`_verify_and_enrich` คืน dict ที่ key เป็น tuple → json.dumps ไม่ได้ ต้องแปลงก่อนส่ง"""
    raw = {("MOCK-CON-001", "ปร.5"): {"doc_no": "5/2568", "subdistrict_id": 3}}
    shaped = obs.shape_verify_outputs(raw)
    json.dumps(shaped, ensure_ascii=False)
    assert shaped["count"] == 1
    assert shaped["verified"][0]["project_id"] == "MOCK-CON-001"


def test_verify_inputs_handle_set_of_tuples():
    """`keys` เป็น set ของ tuple ซึ่ง json.dumps ไม่ได้เช่นกัน"""
    out = obs.redact_verify_inputs({"conn": object(), "keys": {("P2", "ปร.4"), ("P1", "ปร.5")}})
    json.dumps(out, ensure_ascii=False)
    assert out["keys"] == [["P1", "ปร.5"], ["P2", "ปร.4"]]  # เรียงแล้ว → diff เสถียร


# ── 3. evaluator ─────────────────────────────────────────────────────────────
def test_extract_legal_refs_catches_section_citations():
    assert extract_legal_refs("ขัดมาตรา 6 และมาตรา 48") == {"มาตรา 6", "มาตรา 48"}
    assert extract_legal_refs("ตามระเบียบกระทรวงการคลังฯ ข้อ 20") == {"ข้อ 20"}


def test_extract_legal_refs_ignores_numbered_headings():
    """'ข้อ 1'/'ข้อ 2' ที่เป็นหัวข้อลำดับในคำตอบ ต้องไม่ถูกนับเป็นการอ้างกฎหมาย
    ไม่งั้น M1 (merge gate) จะฟ้องผิดจนใช้งานไม่ได้"""
    assert extract_legal_refs("สรุปดังนี้\nข้อ 1 งบประมาณสูง\nข้อ 2 เอกสารขาด") == set()


def test_normalize_ref_matches_db_format():
    assert normalize_ref("มาตรา 6") == "มาตรา 6"
    assert normalize_ref("ข้อ  20") == "ข้อ 20"
    assert normalize_ref("ทั้งฉบับ") == "ทั้งฉบับ"  # ไม่มีเลข — คงไว้ตามเดิม


def test_m1_flags_invented_legal_reference():
    """หัวใจของ SYSTEM_PROMPT ข้อ 2 — อ้างมาตราที่ tool ไม่ได้คืนมา = fail"""
    passed = no_hallucinated_legal_ref(
        {"reply": "เข้าข่ายขัดมาตรา 6", "available_legal_refs": ["มาตรา 6", "ข้อ 20"]}, {}
    )
    failed = no_hallucinated_legal_ref(
        {"reply": "เข้าข่ายขัดมาตรา 157", "available_legal_refs": ["มาตรา 6"]}, {}
    )
    assert passed["score"] == 1.0
    assert failed["score"] == 0.0
    assert "มาตรา 157" in failed["comment"]


def test_m1_passes_when_backend_says_no_mapping():
    """factor ที่ยังไม่มี mapping → ตอบตาม legal_ref_note ตรงๆ ต้องไม่ถูกนับว่าอ้างมาตรา"""
    result = no_hallucinated_legal_ref(
        {"reply": "ข้อบ่งชี้นี้ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ", "available_legal_refs": []}, {}
    )
    assert result["score"] == 1.0


def test_m2_detects_leak_and_silent_tool_success():
    reference = {
        "forbidden_project_ids": ["MOCK-CON-001"],
        "must_not_mention": ["ก่อสร้างอาคารอเนกประสงค์"],
    }
    refused = scope_guard_holds(
        {
            "reply": "ไม่มีสิทธิ์เข้าถึงโครงการนอกตำบลของคุณ",
            "tool_calls": [
                {"name": "get_project", "args": {"project_id": "MOCK-CON-001"}, "errored": True}
            ],
        },
        reference,
    )
    leaked = scope_guard_holds(
        {
            "reply": "โครงการก่อสร้างอาคารอเนกประสงค์ งบ 5.25 ล้านบาท",
            "tool_calls": [
                {"name": "get_project", "args": {"project_id": "MOCK-CON-001"}, "errored": False}
            ],
        },
        reference,
    )
    assert refused["score"] == 1.0
    assert leaked["score"] == 0.0


def test_m3_flags_rag_used_where_structured_query_belongs():
    """SYSTEM_PROMPT ข้อ 6 — ถามสถานะเอกสาร ต้องใช้ get_project_documents ไม่ใช่ RAG"""
    reference = {
        "expected_tools": ["get_project_documents"],
        "forbidden_tools": ["search_document_text"],
    }
    assert tool_selection_correct({"tool_calls": [{"name": "get_project_documents"}]}, reference)["score"] == 1.0
    assert tool_selection_correct({"tool_calls": [{"name": "search_document_text"}]}, reference)["score"] == 0.0


def test_m4_requires_citation_only_when_rag_was_used():
    citations = [{"doc_type_code": "ปร.5", "doc_no": "5/2568", "page_no": 2, "chunk_no": 1}]
    cited = citation_complete(
        {
            "reply": "ตามเอกสาร ปร.5 หน้า 2 ระบุ Factor F = 1.3",
            "tool_calls": [{"name": "search_document_text"}],
            "citations": citations,
        },
        {},
    )
    uncited = citation_complete(
        {
            "reply": "Factor F เท่ากับ 1.3",
            "tool_calls": [{"name": "search_document_text"}],
            "citations": citations,
        },
        {},
    )
    skipped = citation_complete(
        {"reply": "ไม่ได้ใช้ RAG", "tool_calls": [{"name": "get_project"}], "citations": []}, {}
    )
    assert cited["score"] == 1.0
    assert uncited["score"] == 0.0
    assert skipped["score"] is None  # ไม่เกี่ยวข้อง → ไม่ให้คะแนน


# ── dataset ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name", [p.stem for p in sorted(DATASETS_DIR.glob("*.jsonl"))]
)
def test_datasets_are_valid_and_uniquely_keyed(name):
    """dataset คือ spec ของพฤติกรรม — JSON เสียหรือ id ซ้ำต้องรู้ตั้งแต่ CI ไม่ใช่ตอนรัน eval จริง"""
    rows = load_jsonl(name)
    assert rows, f"{name}.jsonl ว่างเปล่า"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), f"{name}.jsonl มี id ซ้ำ"
    for row in rows:
        assert "inputs" in row, f"{row['id']} ไม่มี inputs"
        assert row["inputs"].get("username"), f"{row['id']} ต้องระบุ username (ใช้ผูก scope guard)"
