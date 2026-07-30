# -*- coding: utf-8 -*-
"""
เทสต์ chatbot orchestration (src/services/chatbot.py, src/routers/chatbot.py)

ไม่ยิง Qwen API จริง — monkeypatch chatbot_service._call_qwen เสมอ
ยืนยัน 3 เรื่องหลัก:
  1. role gate: เฉพาะ admin/project_auditor/risk_analyst เรียกได้
  2. 503 เมื่อยังไม่ได้ตั้ง QWEN_API_KEY
  3. scope guard เป็น deterministic — tool ที่ขอโครงการนอกตำบลต้องได้ error ไม่ใช่ข้อมูลจริง
     (แม้ LLM จะ "ขอ" project_id นอกเขตมาก็ตาม)
"""
import base64
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


def _tool_use_block(name: str, args: dict, block_id: str = "toolu_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=args)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _fake_response(blocks):
    return SimpleNamespace(content=blocks)


def test_chatbot_role_gate_forbidden():
    for headers in (LOCAL_EXEC, PUBLIC):
        r = client.post("/chatbot", data={"message": "สวัสดี"}, headers=headers)
        assert r.status_code == 403, headers


def test_chatbot_requires_auth():
    assert client.post("/chatbot", data={"message": "สวัสดี"}).status_code == 401


def test_chatbot_503_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "")
    r = client.post("/chatbot", data={"message": "สวัสดี"}, headers=AUDITOR1)
    assert r.status_code == 503


def test_chatbot_tool_call_round_trip(monkeypatch):
    """1 รอบ tool_use (get_project) แล้วตอบข้อความสุดท้าย — ยืนยัน orchestration ทำงานครบลูป"""
    responses = [
        _fake_response([_tool_use_block("get_project", {"project_id": "MOCK-CON-001"})]),
        _fake_response([_text_block("โครงการนี้ยังไม่พบความเสี่ยงที่ triggered ค่ะ")]),
    ]
    calls = {"n": 0}

    def fake_call_qwen(messages, tools):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_qwen", fake_call_qwen)
    r = client.post("/chatbot", data={"message": "โครงการ MOCK-CON-001 เสี่ยงไหม"}, headers=AUDITOR1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "โครงการนี้ยังไม่พบความเสี่ยงที่ triggered ค่ะ"
    assert body["tool_calls"] == [{"name": "get_project", "args": {"project_id": "MOCK-CON-001"}}]


def test_chatbot_gives_up_after_max_turns(monkeypatch):
    """LLM ที่วน tool-call ไม่เลิก → ต้อง fallback ไม่ loop ไม่รู้จบ (กัน runaway cost)"""

    def fake_call_qwen(messages, tools):
        return _fake_response([_tool_use_block("list_laws", {})])

    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_qwen", fake_call_qwen)
    r = client.post("/chatbot", data={"message": "ทดสอบวน"}, headers=ANALYST1)
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == chatbot_service.FALLBACK_REPLY
    assert len(body["tool_calls"]) == chatbot_service.MAX_TOOL_TURNS


def test_chatbot_rate_limit_429_then_ok_for_other_user(monkeypatch):
    """เกิน limit -> 429 (พร้อมข้อความภาษาไทย), ไม่เกิน -> ปกติ, limit แยกตาม user (issue #32)"""
    from src.rate_limit import SlidingWindowRateLimiter
    from src.routers import chatbot as chatbot_router

    monkeypatch.setattr(chatbot_router, "_rate_limiter", SlidingWindowRateLimiter(max_requests=2, window_seconds=60))
    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_qwen", lambda messages, tools: _fake_response([_text_block("ok")]))

    for _ in range(2):
        r = client.post("/chatbot", data={"message": "สวัสดี"}, headers=AUDITOR1)
        assert r.status_code == 200, r.text

    r_over = client.post("/chatbot", data={"message": "สวัสดี"}, headers=AUDITOR1)
    assert r_over.status_code == 429
    assert "จำกัด" in r_over.json()["detail"]

    r_other_user = client.post("/chatbot", data={"message": "สวัสดี"}, headers=ANALYST1)
    assert r_other_user.status_code == 200, r_other_user.text


def test_chatbot_attachment_forwarded_to_qwen_as_document_block(monkeypatch):
    """แนบไฟล์ PDF มาด้วย — ต้องถูกแปลงเป็น content block ("document", base64) ต่อท้ายข้อความในเทิร์นนี้"""
    captured = {}
    file_bytes = b"%PDF-1.4 fake content"

    def fake_call_qwen(messages, tools):
        captured["messages"] = messages
        return _fake_response([_text_block("สรุปไฟล์ให้แล้วค่ะ")])

    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_service, "_call_qwen", fake_call_qwen)

    r = client.post(
        "/chatbot",
        data={"message": "ไฟล์นี้พูดถึงอะไร"},
        files={"file": ("doc.pdf", file_bytes, "application/pdf")},
        headers=AUDITOR1,
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "สรุปไฟล์ให้แล้วค่ะ"

    last_turn_content = captured["messages"][-1]["content"]
    assert len(last_turn_content) == 2
    assert last_turn_content[0] == {"type": "text", "text": "ไฟล์นี้พูดถึงอะไร"}
    doc_block = last_turn_content[1]
    assert doc_block["type"] == "document"
    assert doc_block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(doc_block["source"]["data"]) == file_bytes


def test_chatbot_attachment_rejects_unsupported_extension(monkeypatch):
    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    r = client.post(
        "/chatbot",
        data={"message": "ดูไฟล์นี้ให้หน่อย"},
        files={"file": ("evidence.docx", b"fake docx bytes", "application/vnd.openxmlformats")},
        headers=AUDITOR1,
    )
    assert r.status_code == 422
    assert "นามสกุล" in r.json()["detail"]


def test_chatbot_attachment_rejects_oversized_file(monkeypatch):
    from src.routers import chatbot as chatbot_router

    monkeypatch.setattr(chatbot_service, "QWEN_API_KEY", "dummy-key-for-test")
    monkeypatch.setattr(chatbot_router, "MAX_ATTACHMENT_SIZE", 10)
    r = client.post(
        "/chatbot",
        data={"message": "ดูไฟล์นี้ให้หน่อย"},
        files={"file": ("small.png", b"0" * 100, "image/png")},
        headers=AUDITOR1,
    )
    assert r.status_code == 413


def test_chatbot_list_projects_tool_searches_by_name():
    """ถามด้วยชื่อโครงการ (ไม่มี project_id) — LLM เรียก list_projects พร้อม project_name ได้"""
    with db_session() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            ("auditor1",),
        ).fetchone()
        auditor1 = dict(row)
        result = chatbot_service._execute_tool(
            conn, auditor1, "list_projects", {"project_name": "ถนน"}
        )
        assert "error" not in result
        projects = result["result"]
        assert projects
        assert all("ถนน" in p["project_name"] for p in projects)


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


def test_chatbot_list_subdistricts_tool_resolves_name_to_id():
    """ผู้ใช้ถามด้วย "ชื่อตำบล" — ต้องมี tool แปลงชื่อ → subdistrict_id ให้ LLM

    กันอาการที่เจอจริงตอน demo: ไม่มี tool นี้ LLM เลยถามรหัสตำบลจากผู้ใช้ ผู้ใช้ตอบ project_id
    (เลข 10+ หลัก) กลับมา → list_projects กรองแล้วได้ 0 แถว → ตอบ "ไม่พบโครงการ" ทั้งที่มีข้อมูลอยู่
    """
    with db_session() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        admin = dict(row)

        result = chatbot_service._execute_tool(conn, admin, "list_subdistricts", {})
        assert "error" not in result
        subs = result["result"]
        assert subs, "admin ต้องเห็นตำบลทั้งหมด"

        by_name = {s["name_th"]: s["subdistrict_id"] for s in subs}
        assert "โยนก" in by_name, f"ไม่พบตำบลโยนกใน {list(by_name)}"

        # รหัสที่ได้ต้องใช้กรอง list_projects ได้จริง (คือ flow ที่พังตอน demo)
        yonok_id = by_name["โยนก"]
        projects = chatbot_service._execute_tool(
            conn, admin, "list_projects", {"subdistrict_id": yonok_id, "risk_level": "high"}
        )
        assert "error" not in projects
        assert projects["result"], "ตำบลโยนกต้องมีโครงการเสี่ยงสูงอย่างน้อย 1 โครงการ"
        assert all(p["subdistrict_id"] == yonok_id for p in projects["result"])


def test_chatbot_list_subdistricts_respects_scope():
    """scope guard ต้องบังคับที่ tool นี้ด้วย — auditor ท่าช้างห้ามเห็นตำบลอื่น"""
    with db_session() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            ("auditor1",),
        ).fetchone()
        auditor1 = dict(row)

        result = chatbot_service._execute_tool(conn, auditor1, "list_subdistricts", {})
        assert "error" not in result
        names = [s["name_th"] for s in result["result"]]
        assert names == ["ท่าช้าง"], f"auditor1 ต้องเห็นแค่ตำบลตัวเอง แต่เห็น {names}"
