# -*- coding: utf-8 -*-
"""
targets.py — target function ที่ LangSmith เรียกตอนรัน experiment

**เรียก service ของจริง ไม่ mock อะไรทั้งสิ้น** — เปิด connection จริง, resolve user จริงจาก DB,
แล้วเรียก `chatbot_service.handle_message` เหมือน request ที่มาจาก `POST /chatbot` ทุกประการ
scope guard จึงถูกทดสอบจริง ไม่ใช่แค่ทดสอบ prompt

⚠️ ยิง Gemini + Pinecone จริง = มีค่าใช้จ่าย → ไฟล์นี้ไม่ถูก collect โดย `pytest -q`
   (ดู pytest.ini: testpaths = tests ocr_pipeline/tests)
"""
import sys
from contextlib import contextmanager
from pathlib import Path

# ให้ `python -m evals.run_chatbot_eval` จาก repo root import src ได้
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth import _user_by_username  # noqa: E402
from src.database import db_session  # noqa: E402
from src.services import chatbot as chatbot_service  # noqa: E402


def _collect_section_nos(node, acc: set) -> None:
    """เดินลงไปในผล tool ทั้งก้อน เก็บทุก `section_no` ที่ backend คืนมาจริง

    ชุดนี้คือ "มาตราที่ chatbot มีสิทธิ์อ้างได้" สำหรับ metric M1 — เอามาจากผล tool จริง
    ไม่ใช่จาก dataset ที่คนเขียนไว้ ทำให้ metric ไม่เพี้ยนเวลา legal_refs/*.csv ถูกอัปเดต
    """
    if isinstance(node, dict):
        if node.get("section_no"):
            acc.add(str(node["section_no"]))
        for value in node.values():
            _collect_section_nos(value, acc)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_section_nos(item, acc)


@contextmanager
def _recording_tools():
    """ห่อ `_execute_tool` ชั่วคราวเพื่อบันทึกผลของ tool แต่ละครั้ง

    จำเป็นเพราะ `handle_message` คืนแค่ {reply, tool_calls, citations} ไม่ได้คืนผลดิบของ tool
    ซึ่ง evaluator ต้องใช้ (M1 ต้องรู้ว่า tool คืนมาตราอะไรบ้าง, M2 ต้องรู้ว่า tool error ไหม)

    ห่อจากฝั่ง eval เท่านั้น — **ไม่แตะโค้ด production** และคืนของเดิมเสมอเมื่อออกจาก context
    """
    original = chatbot_service._execute_tool
    records: list[dict] = []

    def recording(conn, user, name, args):
        result = original(conn, user, name, args)
        records.append({"name": name, "args": args, "result": result})
        return result

    chatbot_service._execute_tool = recording
    try:
        yield records
    finally:
        chatbot_service._execute_tool = original


def chatbot_target(inputs: dict) -> dict:
    """dataset example → ผลลัพธ์ที่ evaluator ใช้ให้คะแนน

    inputs: {"message": str, "username": str, "history": [...]?}
    """
    username = inputs["username"]
    with db_session() as conn:
        row = _user_by_username(conn, username)
        if row is None:
            raise RuntimeError(
                f"ไม่พบ mock user '{username}' ในฐานข้อมูล — รัน `python seed_database.py` ก่อน"
            )
        user = dict(row)

        with _recording_tools() as records:
            out = chatbot_service.handle_message(
                conn, user, inputs["message"], inputs.get("history") or []
            )

    section_nos: set = set()
    _collect_section_nos([r["result"] for r in records], section_nos)

    # เนื้อ chunk ที่ RAG คืนมาจริง — judge ชั้น RAG triad (groundedness/context_relevance)
    # ต้องใช้ตัวข้อความ ไม่ใช่แค่ citation metadata ที่ handle_message คืนมา
    retrieved_context = [
        chunk.get("text", "")
        for r in records
        if r["name"] == "search_document_text" and isinstance(r["result"], dict)
        for chunk in (r["result"].get("chunks") or [])
    ]

    return {
        "reply": out.get("reply", ""),
        # เติม `errored` ให้ evaluator M2 ตรวจได้ว่า tool ที่แตะโครงการนอกเขต "error จริง"
        "tool_calls": [
            {
                "name": r["name"],
                "args": r["args"],
                "errored": isinstance(r["result"], dict) and "error" in r["result"],
            }
            for r in records
        ],
        "citations": out.get("citations") or [],
        "available_legal_refs": sorted(section_nos),
        "retrieved_context": retrieved_context,
    }


def retrieval_target(inputs: dict) -> dict:
    """target ของ experiment ชั้น retrieval — เรียก search_document_text ตรงๆ ไม่ผ่าน LLM

    ถูกกว่าและ debug ง่ายกว่ามาก และเป็นตัวที่ใช้ sweep RAG_MIN_SCORE (แผน §3.2)
    `min_score` override ได้ต่อ example เพื่อทำ sweep ในรอบเดียว
    """
    from src.services import retrieval as retrieval_service

    with db_session() as conn:
        row = _user_by_username(conn, inputs["username"])
        if row is None:
            raise RuntimeError(f"ไม่พบ mock user '{inputs['username']}'")
        out = retrieval_service.search_document_text(
            conn,
            dict(row),
            inputs["query"],
            project_id=inputs.get("project_id"),
            top_k=inputs.get("top_k"),
            min_score=inputs.get("min_score"),
        )
    return {
        "chunks": out.get("chunks") or [],
        "chunk_ids": [c.get("chunk_id") for c in (out.get("chunks") or [])],
        "note": out.get("note"),
    }
