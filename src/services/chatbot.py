# -*- coding: utf-8 -*-
"""
chatbot.py (service) — chatbot orchestration (Qwen function-calling ผ่าน Anthropic-compatible API)

ตอบคำถามของ project_auditor/risk_analyst โดยเรียก service function เดิม
(projects/legal/documents + retrieval) เป็น "tool" — ไม่เขียน SQL เอง และไม่ให้ LLM กำหนด scope เอง
(conn/user inject จากฝั่งเราเสมอ ผูกกับ JWT ที่ authenticate ไปแล้วตอนต้น request)
ต่อให้ LLM พยายามขอโครงการนอกตำบล ก็โดน ForbiddenError จาก scope_subdistrict_ids
ที่ service ชั้นล่างบังคับอยู่แล้ว — scope guard จึง deterministic ไม่พึ่ง prompt guardrail
(ดู docs/legal_linkage_plan.md §5.1 "agent ไม่เขียน SQL เอง เพราะ access control ต้อง deterministic")
"""
import base64
import json
import logging
import sqlite3

from anthropic import Anthropic, APIError

from ..config import (
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MAX_TOKENS,
    QWEN_MODEL,
    QWEN_THINKING_BUDGET_TOKENS,
)
from . import documents as documents_service
from . import legal as legal_service
from . import projects as projects_service
from . import retrieval as retrieval_service
from . import subdistricts as subdistricts_service
from .common import ForbiddenError, NotFoundError, ServiceError

log = logging.getLogger("finrisk.chatbot")

MAX_TOOL_TURNS = 5

FALLBACK_REPLY = (
    "ขอโทษค่ะ ระบบไม่สามารถประมวลผลคำถามนี้ได้ในขณะนี้ กรุณาลองถามใหม่อีกครั้งหรือติดต่อผู้ดูแลระบบ"
)

SYSTEM_PROMPT = """\
คุณคือผู้ช่วยตอบคำถามของระบบ FinRisk สำหรับผู้ตรวจสอบโครงการและนักวิเคราะห์ความเสี่ยงขององค์กรปกครองส่วนท้องถิ่น
กติกาที่ต้องทำตามอย่างเคร่งครัด:
1. ตอบจากผลลัพธ์ที่ได้จากเครื่องมือ (tool) เท่านั้น ห้ามเดา แต่งข้อมูล หรือคาดเดาตัวเลข/ข้อกฎหมายเอง
2. ถ้าผลลัพธ์ของ factor ใดมี legal_refs ว่างเปล่า ให้ตอบตาม legal_ref_note ที่ได้รับมาตรงๆ
   (เช่น "ข้อบ่งชี้นี้ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ") ห้ามอ้างมาตรากฎหมายที่ไม่มีอยู่ใน legal_refs เด็ดขาด
3. ถ้า field ใดมี computable=0 ให้บอกผู้ใช้ว่า "ข้อมูลไม่พอสำหรับประเมินข้อนี้"
   อย่าตีความปนกับ "ไม่พบความเสี่ยง" (triggered=0 ตอนที่ computable=1 เท่านั้น)
4. ถ้าเครื่องมือคืน error (เช่น ไม่พบโครงการ หรือไม่มีสิทธิ์เข้าถึง) ให้แจ้งผู้ใช้ตรงไปตรงมาว่าไม่พบ/ไม่มีสิทธิ์
   ห้ามพยายามหาทางตอบคำถามด้วยข้อมูลอื่นแทน
5. ตอบเป็นภาษาไทย กระชับ ตรงประเด็น เหมาะกับผู้ใช้ที่เป็นเจ้าหน้าที่ราชการ
6. ผลจาก search_document_text คือ "ข้อความที่คัดมาจากเอกสารจริง" — ตอบโดยอ้างอิงเฉพาะข้อความใน chunk
   ที่ได้รับเท่านั้น ห้ามเติมเนื้อหาที่ไม่ได้อยู่ใน chunk และทุกครั้งที่อ้างเนื้อหาเอกสาร
   ต้องระบุอ้างอิงถึงเอกสารและหน้าอย่างเป็นธรรมชาติ เช่น "จากเอกสาร ปร.4-เดโม-001 หน้า 1" หรือ "(เอกสาร ปร.4-เดโม-001 หน้า 1)"
   โดยใช้ข้อมูล doc_no และ page_no ที่ได้รับจากเครื่องมือ ห้ามพิมพ์ชื่อฟิลด์ metadata หรือรูปแบบ key-value
   (เช่น ห้ามแสดง doc_type_code:, doc_no:, page_no: ในคำตอบเด็ดขาด)
7. ถ้า search_document_text คืนผลว่าง ให้ตอบว่าไม่พบข้อความที่เกี่ยวข้องในเอกสารที่มีในระบบ
   ห้ามใช้ summary_text หรือความรู้ทั่วไปมาตอบแทน
8. ถ้าผู้ใช้แนบไฟล์มาในข้อความนี้ (PDF/รูปภาพ) ไฟล์นั้นเป็นข้อมูลที่ผู้ใช้ส่งมาเอง ไม่ใช่ผลจาก tool —
   อ่านและตอบจากเนื้อหาไฟล์นั้นได้โดยตรง แต่ห้ามเอาเนื้อหาในไฟล์ไปอ้างแทนผลของ tool อื่น (เช่น risk score
   หรือ legal_refs ของโครงการในระบบ ต้องมาจาก tool เท่านั้นตามกติกาข้อ 1-2 เดิม)
9. ถ้าผู้ใช้ถามถึงโครงการโดยเรียก "ชื่อโครงการ" ไม่ใช่รหัส project_id ให้เรียก list_projects พร้อม
   project_name ก่อนเสมอเพื่อหา project_id ที่ตรงกัน โดยใส่ project_name เป็นคำสำคัญสั้นๆ ไม่กี่คำ
   ไม่ใช่ทั้งประโยคที่ผู้ใช้พิมพ์มา ถ้าค้นครั้งแรกไม่เจอ ให้ลองอีกครั้งด้วยคำที่น้อยลง/เฉพาะเจาะจงน้อยลง
   ก่อนสรุปว่าไม่พบ เมื่อเจอ project_id แล้วค่อยเรียก get_project/get_project_legal/get_project_documents
   ต่อ ถ้าค้นแล้วยังไม่เจอหรือเจอมากกว่า 1 โครงการที่ชื่อคล้ายกัน ให้ถามผู้ใช้กลับให้ระบุให้ชัดเจนขึ้น
   (เช่น ขอ project_id หรือชื่อเต็ม) ห้ามเดาว่าเป็นโครงการไหน
10. ถ้าผู้ใช้อ้างถึงตำบลด้วย "ชื่อตำบล" (เช่น "ตำบลท่าช้าง" "ในตำบลโยนก") ให้เรียก list_subdistricts
   ก่อนเสมอเพื่อหา subdistrict_id ที่ตรงกับชื่อนั้น แล้วค่อยส่ง subdistrict_id ที่ได้ไปให้ list_projects
   **ห้ามถามรหัสตำบลจากผู้ใช้ และห้ามเดารหัสเอง** — ผู้ใช้ไม่รู้รหัสภายในของระบบ
   ถ้าชื่อที่ผู้ใช้พิมพ์ไม่ตรงกับตำบลใดใน list_subdistricts ให้บอกว่าไม่พบตำบลนั้นในสิทธิ์ที่เข้าถึงได้
   พร้อมบอกรายชื่อตำบลที่มีให้เลือก ถ้าชื่อคล้ายกันหลายตำบลให้ถามกลับให้ระบุชัดเจน
"""

TOOL_DECLARATIONS = [
    {
        "name": "list_subdistricts",
        "description": (
            "แสดงรายชื่อตำบลที่ user มีสิทธิ์เห็น พร้อม subdistrict_id (รหัสตำบลที่ใช้จริงในระบบ) "
            "ใช้เมื่อผู้ใช้อ้างถึงตำบลด้วย 'ชื่อ' (เช่น 'ตำบลท่าช้าง') เพื่อหา subdistrict_id "
            "ก่อนส่งต่อให้ list_projects — ห้ามเดารหัสตำบลเอง และห้ามขอรหัสจากผู้ใช้"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_projects",
        "description": (
            "แสดงรายการโครงการที่ user มีสิทธิ์เห็น กรองตามตำบล/ระดับความเสี่ยง/ชื่อโครงการได้ "
            "ใช้เมื่อต้องค้นหาโครงการโดยยังไม่รู้ project_id — ถ้าผู้ใช้ถามถึงโครงการด้วย 'ชื่อ' "
            "(เช่น 'โครงการซ่อมถนนหมู่ 3 เสี่ยงไหม') ให้เรียก tool นี้ก่อนโดยใส่ project_name เป็น "
            "คำสำคัญสั้นๆ 1-3 คำที่เด่นที่สุด (อย่าใส่ทั้งประโยคยาว เพราะชื่อโครงการจริงมักมีคำแทรก "
            "เช่น 'หมู่ที่ 9' คั่นอยู่ — ยิ่งใส่คำน้อยและเฉพาะเจาะจง ยิ่งมีโอกาสเจอ) เพื่อหา project_id "
            "แล้วค่อยเรียก get_project/get_project_legal/get_project_documents ต่อ"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subdistrict_id": {
                    "type": "integer",
                    "description": (
                        "รหัสตำบลในระบบ (เลขจำนวนเต็มน้อยๆ) — ต้องได้มาจาก list_subdistricts เท่านั้น "
                        "ห้ามเดาเอง และห้ามใช้ project_id (เลขยาว 10+ หลัก) มาใส่ช่องนี้เด็ดขาด"
                    ),
                },
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "project_name": {
                    "type": "string",
                    "description": (
                        "คำสำคัญค้นชื่อโครงการ คั่นด้วยช่องว่างได้หลายคำ ทุกคำต้องปรากฏในชื่อโครงการ "
                        "(ไม่สนลำดับ/ตัวพิมพ์เล็กใหญ่) — ใช้คำน้อยๆ ที่เฉพาะเจาะจง เช่น 'ถนน บ้านป่ายาง' "
                        "แทนการพิมพ์ทั้งประโยคที่ผู้ใช้ถามมา"
                    ),
                },
            },
        },
    },
    {
        "name": "get_project",
        "description": "ดูรายละเอียดโครงการ + risk score ล่าสุด + ผล risk factor รายตัว จาก project_id",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "get_project_legal",
        "description": (
            "ดูผล risk factor พร้อมข้อกฎหมาย/ระเบียบที่เกี่ยวข้อง (legal_refs) และ action_suggestion "
            "ของโครงการ — ใช้ตอบคำถามเรื่องกฎหมาย/ระเบียบ/ความเสี่ยง"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "only_triggered": {
                    "type": "boolean",
                    "description": "true = คืนเฉพาะข้อบ่งชี้ที่ triggered เท่านั้น",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_project_documents",
        "description": (
            "ดูเอกสารของโครงการ สถานะ เอกสารที่ยังขาด และข้อสังเกตที่พบในเอกสาร (findings) "
            "พร้อมข้อกฎหมายที่เกี่ยวข้อง"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "list_laws",
        "description": "ดูรายการกฎหมาย/ระเบียบ/ประกาศ และมาตรา/ข้อทั้งหมดที่มีในระบบ (reference)",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# tool ค้นข้อความในเอกสาร (เอกสาร/แผนเรียกว่า "tool ตัวที่ 6") — ประกาศเฉพาะเมื่อเปิดใช้ RAG (ดู _tools())
# description ที่บอก "เมื่อไรไม่ควรใช้" สำคัญพอๆ กับบอกว่าเมื่อไรควรใช้ ไม่งั้น Qwen จะเริ่มเอา RAG
# ไปตอบคำถามที่ structured query ตอบแม่นกว่า ซึ่งเป็นการถอยหลังจากจุดแข็งเดิมของระบบ (แผน §6.5)
SEARCH_DOC_DECLARATION = {
    "name": "search_document_text",
    "description": (
        "ค้นหาข้อความจากเนื้อหาเอกสารเต็มของโครงการ (ปร.4/ปร.5/ปร.6) — ใช้เมื่อผู้ใช้ถามถึง"
        "รายละเอียดที่อยู่ในตัวเอกสาร เช่น 'ปร.5 ระบุอะไรบ้าง' 'ในเอกสารเขียนว่าอย่างไร' "
        "อย่าใช้เครื่องมือนี้ถามเรื่องสถานะเอกสารขาด/ไม่ขาด หรือ risk score (ใช้ get_project_documents "
        "และ get_project แทน ซึ่งแม่นยำกว่าเพราะอ่านจากข้อมูลที่ตรวจสอบแล้ว)"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "ข้อความค้นหาเป็นภาษาไทย"},
            "project_id": {"type": "string", "description": "จำกัดเฉพาะโครงการนี้ (แนะนำให้ระบุเสมอถ้ารู้)"},
        },
        "required": ["query"],
    },
}


def _tools() -> list[dict]:
    """ประกาศ tool ตามที่เปิดใช้จริง — PINECONE_API_KEY ว่าง = Qwen ไม่เห็น tool ค้นเอกสารเลย
    (feature flag ต้องปิดได้จริง ไม่ใช่แค่ให้ tool คืน error)"""
    decls = list(TOOL_DECLARATIONS)
    if retrieval_service.rag_enabled():
        decls.append(SEARCH_DOC_DECLARATION)
    return decls


def _tool_list_subdistricts(conn: sqlite3.Connection, user: dict, args: dict):
    return subdistricts_service.list_subdistricts_view(conn, user)


def _tool_list_projects(conn: sqlite3.Connection, user: dict, args: dict):
    return projects_service.list_projects_view(
        conn,
        user,
        subdistrict_id=args.get("subdistrict_id"),
        risk_level=args.get("risk_level"),
        project_name=args.get("project_name"),
    )


def _tool_get_project(conn: sqlite3.Connection, user: dict, args: dict):
    return projects_service.project_summary_view(conn, args["project_id"], user)


def _tool_get_project_legal(conn: sqlite3.Connection, user: dict, args: dict):
    return legal_service.project_legal_view(
        conn, args["project_id"], user, args.get("only_triggered", False)
    )


def _tool_get_project_documents(conn: sqlite3.Connection, user: dict, args: dict):
    return documents_service.project_documents_view(conn, args["project_id"], user)


def _tool_list_laws(conn: sqlite3.Connection, user: dict, args: dict):
    return legal_service.list_laws(conn)


def _tool_search_document_text(conn: sqlite3.Connection, user: dict, args: dict):
    """scope guard อยู่ใน service (สองชั้น) — args["project_id"] ที่ LLM ส่งมาไม่ได้ผ่อนสิทธิ์อะไรเลย"""
    return retrieval_service.search_document_text(
        conn, user, args["query"], project_id=args.get("project_id")
    )


TOOL_DISPATCH = {
    "list_subdistricts": _tool_list_subdistricts,
    "list_projects": _tool_list_projects,
    "get_project": _tool_get_project,
    "get_project_legal": _tool_get_project_legal,
    "get_project_documents": _tool_get_project_documents,
    "list_laws": _tool_list_laws,
    "search_document_text": _tool_search_document_text,
}


def _execute_tool(conn: sqlite3.Connection, user: dict, name: str, args: dict) -> dict:
    """dispatch tool เดียว — ไม่ raise ออกไปหา LLM (แปลง domain error เป็น {"error": ...} แทน)"""
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return {"error": f"ไม่รู้จักเครื่องมือ '{name}'"}
    try:
        result = handler(conn, user, args or {})
    except NotFoundError as exc:
        return {"error": str(exc)}
    except ForbiddenError as exc:
        return {"error": str(exc)}
    except KeyError as exc:  # LLM ส่ง args ไม่ครบตาม schema
        return {"error": f"ขาดพารามิเตอร์ที่จำเป็น: {exc}"}
    except ServiceError as exc:  # เช่น เรียก search_document_text ตอน PINECONE_API_KEY ว่าง
        return {"error": str(exc)}
    return result if isinstance(result, dict) else {"result": result}


def _collect_citations(result: dict, citations: list[dict]) -> None:
    """เก็บ citation จากผล search_document_text (dedup) — frontend ใช้ชี้ว่าคำตอบมาจากเอกสารหน้าไหน

    ระบบนี้บังคับ guardrail ว่า "ห้ามอ้างมาตราที่ไม่มีใน legal_refs" เพราะผู้ใช้ต้องเปิดเอกสารจริง
    ไปยืนยันได้ — RAG ที่ยกข้อความมาตอบโดยไม่บอกหน้า ขัดหลักเดียวกัน (แผน §8)
    """
    seen = {(c["project_id"], c["doc_type_code"], c["chunk_no"]) for c in citations}
    for chunk in result.get("chunks") or []:
        key = (chunk.get("project_id"), chunk.get("doc_type_code"), chunk.get("chunk_no"))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "project_id": chunk.get("project_id"),
                "doc_type_code": chunk.get("doc_type_code"),
                "doc_no": chunk.get("doc_no"),
                "page_no": chunk.get("page_no"),
                "chunk_no": chunk.get("chunk_no"),
            }
        )


def _history_to_messages(history: list[dict]) -> list[dict]:
    # ChatTurn.role ฝั่ง schema/frontend ยังเป็น "user"/"model" เดิม (ไม่แก้ frontend) — แปลงเป็น
    # "assistant" เฉพาะตอนสร้าง message ให้ Anthropic-compatible API ซึ่งไม่รู้จัก role "model"
    return [
        {"role": "assistant" if turn["role"] == "model" else "user", "content": turn["text"]}
        for turn in history
    ]


def _call_qwen(messages: list[dict], tools: list[dict]):
    """แยกออกมาต่างหากเพื่อ monkeypatch ในเทสต์ได้ (ไม่ยิง Qwen API จริงใน pytest)"""
    client = Anthropic(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    return client.messages.create(
        model=QWEN_MODEL,
        max_tokens=QWEN_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=tools,
        thinking={"type": "enabled", "budget_tokens": QWEN_THINKING_BUDGET_TOKENS},
        messages=messages,
    )


def handle_message(
    conn: sqlite3.Connection,
    user: dict,
    message: str,
    history: list[dict],
    attachment: tuple[bytes, str] | None = None,
) -> dict:
    """คืน {"reply": str, "tool_calls": [...], "citations": [...]}

    `citations` เป็น field ที่เพิ่มเข้ามาทีหลัง (additive — client เก่าเมินไปเฉยๆ ไม่พัง)
    ว่างเสมอถ้าไม่ได้เรียก search_document_text

    `attachment` (ถ้ามี) คือ (bytes, mime_type) ของไฟล์ที่ผู้ใช้แนบมา "เฉพาะเทิร์นนี้" — ใช้ตอบ
    คำถามครั้งเดียวแล้วทิ้ง ไม่ถูกเก็บเข้า `history` ที่ client เก็บ/ส่งกลับมาในเทิร์นถัดไป จึงไม่ต้อง
    แบก byte เดิมซ้ำทุกครั้ง และไม่บันทึกลง DB/disk ที่ไหนเลย
    """
    if not QWEN_API_KEY:
        raise ServiceError("ยังไม่ได้ตั้งค่า chatbot (QWEN_API_KEY ว่าง)")

    messages = _history_to_messages(history)
    turn_content: list[dict] = [{"type": "text", "text": message}]
    if attachment is not None:
        data, mime_type = attachment
        b64 = base64.b64encode(data).decode("ascii")
        block_type = "document" if mime_type == "application/pdf" else "image"
        turn_content.append(
            {"type": block_type, "source": {"type": "base64", "media_type": mime_type, "data": b64}}
        )
    messages.append({"role": "user", "content": turn_content})

    tools = _tools()
    tool_calls: list[dict] = []
    citations: list[dict] = []
    for _ in range(MAX_TOOL_TURNS):
        try:
            response = _call_qwen(messages, tools)
        except APIError as exc:
            log.warning("Qwen API error: %s", exc)
            raise ServiceError("เรียกใช้บริการ chatbot ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง") from exc

        blocks = response.content or []
        if not blocks:
            return {"reply": FALLBACK_REPLY, "tool_calls": tool_calls, "citations": citations}

        tool_use_blocks = [b for b in blocks if b.type == "tool_use"]
        if not tool_use_blocks:
            text = "".join(b.text for b in blocks if b.type == "text")
            return {
                "reply": text.strip() or FALLBACK_REPLY,
                "tool_calls": tool_calls,
                "citations": citations,
            }

        messages.append({"role": "assistant", "content": blocks})  # รวม thinking/tool_use block เดิม
        tool_result_content = []
        for block in tool_use_blocks:
            args = dict(block.input or {})
            result = _execute_tool(conn, user, block.name, args)
            tool_calls.append({"name": block.name, "args": args})
            if block.name == "search_document_text":
                _collect_citations(result, citations)
            tool_result_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_result_content})

    log.warning("chatbot เกิน MAX_TOOL_TURNS (%d) — ตอบ fallback", MAX_TOOL_TURNS)
    return {"reply": FALLBACK_REPLY, "tool_calls": tool_calls, "citations": citations}
