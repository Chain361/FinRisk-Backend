# -*- coding: utf-8 -*-
"""
observability.py — ชั้นห่อ LangSmith แบบ optional (ดู docs/langsmith_eval_plan.md)

หลักการเดียวกับ `retrieval.rag_enabled()`: **feature flag ต้องปิดได้จริง**
ไม่ได้ติดตั้งแพ็กเกจ `langsmith` หรือ `LANGSMITH_TRACING` ไม่ใช่ "true"
→ decorator ทุกตัวคืนฟังก์ชันเดิมกลับไปตรงๆ (ไม่เพิ่ม stack frame แม้แต่เฟรมเดียว)
ระบบเดิมจึงทำงานได้ 100% โดยไม่ต้องมี LangSmith และ `pytest -q` ผ่านทั้งสองแบบ

⚠️ ต้อง import `..config` ก่อนอ่าน env เสมอ — `config.py` เป็นตัวที่เรียก `load_dotenv()`
   ถ้าอ่าน os.getenv ตรงๆ โดยไม่ผ่าน config ค่าใน `.env` จะยังไม่ถูกโหลด

⚠️ **redaction**: `@traceable` จะ serialize argument ทุกตัวของฟังก์ชันที่ห่อ ซึ่งรวมถึง
   `conn` (psycopg Connection — serialize ไม่ได้) และ `user` dict (มี username/display_name
   ของเจ้าหน้าที่) จึงต้องส่ง `process_inputs=` ทุกจุดที่ฟังก์ชันรับสองตัวนี้
"""
import logging
import os

from .config import LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING

log = logging.getLogger("finrisk.observability")

TRACING_ENABLED = bool(LANGSMITH_TRACING)

try:
    from langsmith import traceable as _traceable
    from langsmith import wrappers as _wrappers
except ImportError:  # ยังไม่ได้ลง langsmith — เป็นสถานะปกติ ไม่ใช่ error
    _traceable = _wrappers = None
    if TRACING_ENABLED:
        log.warning(
            "LANGSMITH_TRACING=true แต่ยังไม่ได้ติดตั้งแพ็กเกจ langsmith "
            "(pip install -r requirements.txt) — ปิด tracing ไปก่อน"
        )
        TRACING_ENABLED = False

if TRACING_ENABLED and not LANGSMITH_API_KEY:
    log.warning("LANGSMITH_TRACING=true แต่ LANGSMITH_API_KEY ว่าง — trace จะไม่ถูกส่ง")

if TRACING_ENABLED:
    # LangSmith SDK อ่านชื่อ project จาก env เอง — เขียนกลับให้ค่า default ใน config มีผลจริง
    os.environ.setdefault("LANGSMITH_PROJECT", LANGSMITH_PROJECT)


def enabled() -> bool:
    """ให้ที่อื่นเช็คสถานะได้โดยไม่ต้องอ่าน env ซ้ำ (เช่น /health, สคริปต์ eval)"""
    return TRACING_ENABLED


def traceable(**kwargs):
    """decorator ที่เป็น no-op เมื่อปิด tracing

    รับ kwargs เดียวกับ `langsmith.traceable` (run_type, name, process_inputs, process_outputs)
    """

    def _decorate(fn):
        if not TRACING_ENABLED:
            return fn
        return _traceable(**kwargs)(fn)

    return _decorate


def wrap_gemini(client):
    """ห่อ `google.genai.Client` ให้ทุก generate_content ขึ้น LangSmith เป็น run type `llm`
    (ได้ token usage + latency ฟรี)

    ⚠️ `wrap_gemini` ยังเป็น **beta** ตามเอกสาร LangChain — ถ้า SDK เปลี่ยนแล้วพัง
    ให้แก้เฉพาะฟังก์ชันนี้ให้ `return client` แล้ว trace จะเหลือแค่ระดับ chain/tool
    (โครงสร้างยังครบ เสียแค่ token usage) โดยไม่ต้องแตะ chatbot.py
    """
    if not TRACING_ENABLED:
        return client
    try:
        return _wrappers.wrap_gemini(
            client,
            tracing_extra={
                "tags": ["finrisk", "chatbot"],
                "metadata": {"sdk": "google-genai"},
            },
        )
    except Exception as exc:  # noqa: BLE001 — observability ต้องไม่ทำให้ request ของผู้ใช้พัง
        log.warning("wrap_gemini ไม่สำเร็จ (%s) — ใช้ client ดิบแทน", exc)
        return client


# ──────────────────────────────────────────────────────────────────────────────
# process_inputs / process_outputs — ตัด object ที่ serialize ไม่ได้ + ข้อมูลส่วนบุคคลออก
# ──────────────────────────────────────────────────────────────────────────────
def _user_brief(user) -> dict:
    """เก็บเฉพาะสิ่งที่ใช้วิเคราะห์ผลได้ — `username`/`display_name` เป็นข้อมูลส่วนบุคคล
    ของเจ้าหน้าที่ ไม่ควรออกนอกระบบ (`user_id` พอสำหรับจับกลุ่ม ถ้าต้องการ)
    """
    user = user or {}
    return {
        "user_id": user.get("user_id"),
        "role": user.get("role"),
        "subdistrict_id": user.get("subdistrict_id"),
    }


def redact_chat_inputs(inputs: dict) -> dict:
    """handle_message(conn, user, message, history) — ตัด conn ทิ้ง, ย่อ user, ย่อ history"""
    return {
        "message": inputs.get("message"),
        "history_len": len(inputs.get("history") or []),
        "user": _user_brief(inputs.get("user")),
    }


def redact_tool_inputs(inputs: dict) -> dict:
    """_execute_tool(conn, user, name, args) — args ที่ LLM ส่งมาเป็นสิ่งที่อยากเห็นที่สุด"""
    return {
        "name": inputs.get("name"),
        "args": inputs.get("args"),
        "user": _user_brief(inputs.get("user")),
    }


def redact_search_inputs(inputs: dict) -> dict:
    """search_document_text(conn, user, query, project_id, top_k, min_score)"""
    return {
        "query": inputs.get("query"),
        "project_id": inputs.get("project_id"),
        "top_k": inputs.get("top_k"),
        "min_score": inputs.get("min_score"),
        "user": _user_brief(inputs.get("user")),
    }


def redact_verify_inputs(inputs: dict) -> dict:
    """_verify_and_enrich(conn, keys) — `keys` เป็น set ของ tuple ซึ่ง json.dumps ไม่ได้"""
    return {
        "keys": sorted(
            [list(k) for k in (inputs.get("keys") or [])], key=lambda k: (k[0] or "", k[1] or "")
        )
    }


def shape_verify_outputs(outputs) -> dict:
    """คืนค่าเป็น dict ที่ key เป็น tuple → json.dumps ไม่ได้ ต้องแปลงเป็น list ก่อน"""
    outputs = outputs or {}
    return {
        "verified": [
            {"project_id": k[0], "doc_type_code": k[1], **v} for k, v in outputs.items()
        ],
        "count": len(outputs),
    }


def shape_retriever_outputs(outputs) -> dict:
    """แปลง hit ของ Pinecone เป็นรูป document ที่ LangSmith แสดงผลเป็น retriever view ได้

    ⚠️ นี่คือผลลัพธ์ **ก่อน** post-verify — จำนวนที่ต่างจาก chunk สุดท้ายใน trace
    คือ metric `post_verify_drop_rate` ที่ต้องการวัด (ดูแผน §3.2)
    """
    hits = outputs or []
    return {
        "documents": [
            {
                "page_content": h.get("text", ""),
                "metadata": {k: v for k, v in h.items() if k != "text"},
            }
            for h in hits
        ]
    }
