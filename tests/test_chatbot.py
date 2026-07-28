# -*- coding: utf-8 -*-
"""
เทสต์ chatbot orchestration (src/services/chatbot.py, src/routers/chatbot.py)

ไม่ยิง Gemini API จริง — monkeypatch chatbot_service._call_gemini เสมอ
ยืนยัน 3 เรื่องหลัก:
  1. role gate: เฉพาะ admin/project_auditor/risk_analyst เรียกได้
  2. 503 เมื่อยังไม่ได้ตั้ง GEMINI_API_KEY
  3. scope guard เป็น deterministic — tool ที่ขอโครงการนอกตำบลต้องได้ error ไม่ใช่ข้อมูลจริง
     (แม้ LLM จะ "ขอ" project_id นอกเขตมาก็ตาม)
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.database import db_session
from src.main import app
from src.services import chatbot as chatbot_service

client = TestClient(app)

AUDITOR1 = {"X-Username": "auditor1"}  # project_auditor ท่าช้าง
ANALYST1 = {"X-Username": "analyst1"}  # risk_analyst ท่าช้าง
LOCAL_EXEC = {"X-Username": "thachang_user"}  # local_executive — ไม่อยู่ใน role gate
PUBLIC = {"X-Username": "public1"}
MOCK_OTHER_SUBDISTRICT = "MOCK-CON-002"  # อยู่ตำบลโยนก — นอกเขตของ auditor1/analyst1


def _function_call_part(name: str, args: dict):
    return SimpleNamespace(function_call=SimpleNamespace(name=name, args=args), text=None)


def _text_part(text: str):
    return SimpleNamespace(function_call=None, text=text)


def _fake_response(parts):
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])


def test_chatbot_role_gate_forbidden():
    for headers in (LOCAL_EXEC, PUBLIC):
        r = client.post("/chatbot", json={"message": "สวัสดี"}, headers=headers)
        assert r.status_code == 403, headers


def test_chatbot_requires_auth():
    assert client.post("/chatbot", json={"message": "สวัสดี"}).status_code == 401


def test_chatbot_503_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(chatbot_service, "GEMINI_API_KEY", "")
    r = client.post("/chatbot", json={"message": "สวัสดี"}, headers=AUDITOR1)
    assert r.status_code == 503


def test_chatbot_tool_call_round_trip(monkeypatch):
    """1 รอบ function-call (get_project) แล้วตอบข้อความสุดท้าย — ยืนยัน orchestration ทำงานครบลูป"""
    responses = [
        _fake_response([_function_call_part("get_project", {"project_id": "MOCK-CON-001"})]),
        _fake_response([_text_part("โครงการนี้ยังไม่พบความเสี่ยงที่ triggered ค่ะ")]),
    ]
    calls = {"n": 0}

    def fake_call_gemini(contents, config):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    monkeypatch.setattr(chatbot_service, "GEMINI_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_gemini", fake_call_gemini)
    r = client.post("/chatbot", json={"message": "โครงการ MOCK-CON-001 เสี่ยงไหม"}, headers=AUDITOR1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "โครงการนี้ยังไม่พบความเสี่ยงที่ triggered ค่ะ"
    assert body["tool_calls"] == [{"name": "get_project", "args": {"project_id": "MOCK-CON-001"}}]


def test_chatbot_gives_up_after_max_turns(monkeypatch):
    """LLM ที่วน tool-call ไม่เลิก → ต้อง fallback ไม่ loop ไม่รู้จบ (กัน runaway cost)"""

    def fake_call_gemini(contents, config):
        return _fake_response([_function_call_part("list_laws", {})])

    monkeypatch.setattr(chatbot_service, "GEMINI_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_gemini", fake_call_gemini)
    r = client.post("/chatbot", json={"message": "ทดสอบวน"}, headers=ANALYST1)
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == chatbot_service.FALLBACK_REPLY
    assert len(body["tool_calls"]) == chatbot_service.MAX_TOOL_TURNS


def test_chatbot_rate_limit_429_then_ok_for_other_user(monkeypatch):
    """เกิน limit -> 429 (พร้อมข้อความภาษาไทย), ไม่เกิน -> ปกติ, limit แยกตาม user (issue #32)"""
    from src.rate_limit import SlidingWindowRateLimiter
    from src.routers import chatbot as chatbot_router

    monkeypatch.setattr(chatbot_router, "_rate_limiter", SlidingWindowRateLimiter(max_requests=2, window_seconds=60))
    monkeypatch.setattr(chatbot_service, "GEMINI_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_gemini", lambda contents, config: _fake_response([_text_part("ok")]))

    for _ in range(2):
        r = client.post("/chatbot", json={"message": "สวัสดี"}, headers=AUDITOR1)
        assert r.status_code == 200, r.text

    r_over = client.post("/chatbot", json={"message": "สวัสดี"}, headers=AUDITOR1)
    assert r_over.status_code == 429
    assert "จำกัด" in r_over.json()["detail"]

    r_other_user = client.post("/chatbot", json={"message": "สวัสดี"}, headers=ANALYST1)
    assert r_other_user.status_code == 200, r_other_user.text


def test_execute_tool_scope_guard_blocks_cross_subdistrict_access():
    """หัวใจของ guardrail: ต่อให้ LLM ขอ project_id นอกตำบล tool ต้องคืน error ไม่ใช่ข้อมูลจริง"""
    with db_session() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            ("auditor1",),
        ).fetchone()
        auditor1 = dict(row)

        result = chatbot_service._execute_tool(
            conn, auditor1, "get_project_legal", {"project_id": MOCK_OTHER_SUBDISTRICT}
        )
        assert "error" in result
        assert "risk_score" not in result and "project" not in result

        # เจ้าของตำบลเดียวกัน (auditor3 — โยนก) ต้องเห็นได้ปกติ
        row3 = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            ("auditor3",),
        ).fetchone()
        auditor3 = dict(row3)
        result3 = chatbot_service._execute_tool(
            conn, auditor3, "get_project_legal", {"project_id": MOCK_OTHER_SUBDISTRICT}
        )
        assert "error" not in result3
        assert "result" in result3  # project_legal_view คืน list → ถูก wrap เป็น {"result": [...]}
