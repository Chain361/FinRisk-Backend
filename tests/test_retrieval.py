# -*- coding: utf-8 -*-
"""
เทสต์ชั้น RAG (src/services/retrieval.py + GET /projects/{id}/documents/search + tool ตัวที่ 6)

ไม่ยิง Pinecone จริง — monkeypatch `retrieval._vector_search` เสมอ (pattern เดียวกับ
`chatbot._call_qwen` ใน test_chatbot.py) เทสต์ตามตาราง §9 ของ docs/rag_pinecone_plan.md

⚠️ MOCK-CON-001 อยู่ตำบลโยนก → auditor3 เห็นได้, auditor1 (ท่าช้าง) เห็นไม่ได้
"""
import pytest
from fastapi.testclient import TestClient

from src.database import db_session
from src.main import app
from src.services import chatbot as chatbot_service
from src.services import retrieval as retrieval_service
from src.services.common import ForbiddenError, ServiceError

client = TestClient(app)

AUDITOR1 = {"X-Username": "auditor1"}   # project_auditor ท่าช้าง — นอกเขต MOCK-CON-001
AUDITOR3 = {"X-Username": "auditor3"}   # project_auditor โยนก — เจ้าของ MOCK-CON-001
PROJECT = "MOCK-CON-001"

FAKE_HIT = {
    "_id": f"{PROJECT}:PR5:3",
    "score": 0.91,
    "text": "ค่างานต้นทุน 3,980,000 บาท Factor F = 1.3061",
    "project_id": PROJECT,
    "doc_type_code": "PR5",
    "chunk_no": 3,
    "page_no": 1,
}


def _user(conn, username: str) -> dict:
    row = conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    return dict(row)


def _stub_search(monkeypatch, hits, calls=None):
    def fake(query, top_k, flt):
        if calls is not None:
            calls.append({"query": query, "top_k": top_k, "filter": flt})
        return [dict(h) for h in hits]

    monkeypatch.setattr(retrieval_service, "PINECONE_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(retrieval_service, "_vector_search", fake)


# ──────────────────────────────────────────────────────────────────────────────
def test_search_requires_pinecone_key(monkeypatch):
    """คีย์ว่าง = tool ตัวที่ 6 ไม่ถูกประกาศให้ Qwen เลย และ endpoint ตอบ 503
    (ระบบเดิม tool 5 ตัวต้องทำงานครบเหมือนไม่มีอะไรเกิดขึ้น)"""
    monkeypatch.setattr(retrieval_service, "PINECONE_API_KEY", "")

    names = [d["name"] for d in chatbot_service._tools()]
    assert "search_document_text" not in names
    assert len(names) == len(chatbot_service.TOOL_DECLARATIONS)

    r = client.get(f"/projects/{PROJECT}/documents/search", params={"q": "Factor F"}, headers=AUDITOR3)
    assert r.status_code == 503

    # ต่อให้ LLM ดันเรียก tool ที่ไม่ได้ประกาศ ต้องได้ error กลับไป ไม่ใช่ exception หลุดออก request
    with db_session() as conn:
        result = chatbot_service._execute_tool(
            conn, _user(conn, "auditor3"), "search_document_text", {"query": "Factor F"}
        )
    assert "error" in result


def test_tool_declared_when_key_present(monkeypatch):
    monkeypatch.setattr(retrieval_service, "PINECONE_API_KEY", "dummy-key-for-test")
    names = [d["name"] for d in chatbot_service._tools()]
    assert "search_document_text" in names


def test_search_scoped_to_own_subdistrict(monkeypatch):
    """auditor3 (โยนก) ค้นแล้วได้ chunk ของ MOCK-CON-001 พร้อม doc_no ที่ post-verify ดึงมาจาก DB"""
    calls: list[dict] = []
    _stub_search(monkeypatch, [FAKE_HIT], calls)

    r = client.get(
        f"/projects/{PROJECT}/documents/search", params={"q": "Factor F"}, headers=AUDITOR3
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["chunks"]) == 1
    chunk = body["chunks"][0]
    assert chunk["doc_type_code"] == "PR5"
    assert chunk["doc_no"] == "ปร.5-เดโม-001"        # ← มาจาก Postgres ไม่ใช่ metadata ของ Pinecone
    assert chunk["page_no"] == 1 and chunk["score"] == 0.91

    # ชั้น 1: pre-filter ต้องถูกส่งไป Pinecone ด้วยเสมอ (subdistrict จาก JWT + project ที่ระบุ)
    assert calls[0]["filter"]["project_id"] == PROJECT
    assert "$in" in calls[0]["filter"]["subdistrict_id"]


def test_search_post_verify_blocks_poisoned_hit(monkeypatch):
    """สำคัญที่สุด — Pinecone จงใจคืน chunk ของโยนกให้ auditor1 (ท่าช้าง) โดยข้าม pre-filter
    ชั้น 2 ต้องกรองทิ้งจนเหลือผลว่าง ถ้าเทสต์นี้ไม่ผ่าน = ข้อมูลข้ามตำบลรั่ว"""
    _stub_search(monkeypatch, [FAKE_HIT])

    with db_session() as conn:
        out = retrieval_service.search_document_text(
            conn, _user(conn, "auditor1"), "Factor F"      # ไม่ระบุ project_id → ไม่ชน 403 ตั้งแต่ต้น
        )
    assert out["chunks"] == []
    assert out["note"] == retrieval_service.EMPTY_NOTE


def test_search_drops_hit_missing_in_postgres(monkeypatch):
    """hit ที่ไม่มีแถวใน project_documents แล้ว (ingest ค้างจากรอบก่อน) ต้องถูกทิ้ง ไม่ใช่คืนดิบๆ"""
    ghost = {**FAKE_HIT, "_id": "GHOST-001:PR9:1", "project_id": "GHOST-001", "doc_type_code": "PR9"}
    _stub_search(monkeypatch, [ghost])

    with db_session() as conn:
        out = retrieval_service.search_document_text(conn, _user(conn, "admin"), "Factor F")
    assert out["chunks"] == []


def test_search_project_id_out_of_scope_403(monkeypatch):
    """ระบุ project_id นอกตำบล → ForbiddenError ตั้งแต่ก่อนยิง Pinecone (ไม่เสีย read unit)"""
    calls: list[dict] = []
    _stub_search(monkeypatch, [FAKE_HIT], calls)

    with db_session() as conn:
        with pytest.raises(ForbiddenError):
            retrieval_service.search_document_text(
                conn, _user(conn, "auditor1"), "Factor F", project_id=PROJECT
            )
    assert calls == []                                  # ← ต้องยังไม่ได้ยิง Pinecone เลย

    r = client.get(
        f"/projects/{PROJECT}/documents/search", params={"q": "Factor F"}, headers=AUDITOR1
    )
    assert r.status_code == 403


def test_search_survives_empty_document_chunks(monkeypatch):
    """ลบ document_chunks ทั้งตาราง → RAG ยังคืนผลได้ (retrieval ต้องไม่พึ่งตารางนี้ — แผน §4.3)

    reseed ทุก deploy ทำให้ตารางนี้ว่างทุกครั้ง ถ้าเทสต์นี้ไม่ผ่าน RAG จะพังหลัง deploy ทุกรอบ
    โดยไม่มี error ให้เห็น (ผู้ใช้เห็นแค่ "ไม่พบข้อมูลในเอกสาร")
    """
    _stub_search(monkeypatch, [FAKE_HIT])

    with db_session() as conn:
        try:
            conn.execute("DELETE FROM document_chunks")   # ไม่ commit — rollback ท้ายเทสต์
            out = retrieval_service.search_document_text(
                conn, _user(conn, "auditor3"), "Factor F", project_id=PROJECT
            )
            assert len(out["chunks"]) == 1
            assert out["chunks"][0]["text"] == FAKE_HIT["text"]
        finally:
            conn.rollback()


def test_min_score_filters_low_hits(monkeypatch):
    """คะแนนต่ำกว่า threshold ต้องถูกกรองทิ้ง และ min_score=0 ต้องเห็นทุก hit (ใช้ตอน calibrate)"""
    weak = {**FAKE_HIT, "_id": f"{PROJECT}:PR5:4", "chunk_no": 4, "score": 0.61}
    _stub_search(monkeypatch, [FAKE_HIT, weak])

    with db_session() as conn:
        user3 = _user(conn, "auditor3")
        strict = retrieval_service.search_document_text(conn, user3, "Factor F", project_id=PROJECT)
        raw = retrieval_service.search_document_text(
            conn, user3, "Factor F", project_id=PROJECT, min_score=0
        )
    assert [c["chunk_no"] for c in strict["chunks"]] == [3]
    assert [c["chunk_no"] for c in raw["chunks"]] == [3, 4]


def test_chatbot_returns_citations(monkeypatch):
    """คำตอบที่อ้างเอกสารต้องมี citations ติดมาด้วยเสมอ (แผน §8 — ไม่มี citation ก็ไม่ควรเปิด RAG)"""
    from types import SimpleNamespace

    def _tool_use_block(name, args):
        return SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=args)

    def _text_block(text):
        return SimpleNamespace(type="text", text=text)

    responses = [
        SimpleNamespace(content=[
            _tool_use_block("search_document_text", {"query": "Factor F", "project_id": PROJECT})]),
        SimpleNamespace(content=[
            _text_block("ปร.5 ระบุ Factor F = 1.3061 (ปร.5-เดโม-001 หน้า 1)")]),
    ]
    n = {"i": 0}

    def fake_call_qwen(messages, tools):
        r = responses[n["i"]]
        n["i"] += 1
        return r

    _stub_search(monkeypatch, [FAKE_HIT])
    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_qwen", fake_call_qwen)

    r = client.post("/chatbot", data={"message": "ปร.5 ระบุอะไรบ้าง"}, headers=AUDITOR3)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["citations"] == [
        {"project_id": PROJECT, "doc_type_code": "PR5", "doc_no": "ปร.5-เดโม-001",
         "page_no": 1, "chunk_no": 3}
    ]


def test_search_disabled_raises_service_error(monkeypatch):
    monkeypatch.setattr(retrieval_service, "PINECONE_API_KEY", "")
    with db_session() as conn:
        with pytest.raises(ServiceError):
            retrieval_service.search_document_text(conn, _user(conn, "auditor3"), "Factor F")
