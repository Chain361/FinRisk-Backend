# -*- coding: utf-8 -*-
"""/chatbot — ผู้ช่วยตอบคำถาม (Qwen function-calling ผ่าน Anthropic-compatible API) สำหรับ
project_auditor/risk_analyst

router บาง: orchestration + tool dispatch อยู่ใน src/services/chatbot.py ทั้งหมด

รับเป็น multipart form (ไม่ใช่ JSON body) เพราะรองรับไฟล์แนบต่อเทิร์นด้วย — ไฟล์แนบใช้ตอบคำถาม
ของเทิร์นนั้นครั้งเดียวแล้วทิ้ง ไม่บันทึกลง DB/disk เลย (คนละเรื่องกับ document intelligence ของ
โครงการใน src/routers/documents.py ซึ่งมี OCR pipeline คนละชุด)
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import Field, TypeAdapter

from ..auth import require_roles
from ..config import CHATBOT_RATE_LIMIT_PER_MINUTE
from ..database import Connection, get_db
from ..rate_limit import SlidingWindowRateLimiter
from ..schemas import ChatTurn
from ..services import chatbot as chatbot_service
from ..services.common import ServiceError

router = APIRouter(prefix="/chatbot", tags=["chatbot"])

_rate_limiter = SlidingWindowRateLimiter(CHATBOT_RATE_LIMIT_PER_MINUTE, window_seconds=60)

# ประวัติแชทฝั่ง client ถืออยู่ ส่งมาทุกครั้ง — backend ไม่เก็บ conversation state (เดิมอยู่ใน
# ChatMessageRequest.history ก่อนย้าย endpoint นี้มาเป็น multipart form เพื่อรับไฟล์แนบด้วย)
_history_adapter = TypeAdapter(Annotated[list[ChatTurn], Field(max_length=40)])

# ไฟล์แนบในแชท: จำกัดเฉพาะชนิดที่ Qwen (ผ่าน Anthropic-compatible content block) อ่านได้ตรงๆ
# (ไม่ใช่ allowlist เดียวกับ routers/audit.py ที่รับ .docx/.xlsx ด้วย เพราะที่นั่นแค่เก็บไฟล์
# ไม่ได้ส่งให้ LLM อ่าน)
ATTACHMENT_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("")
async def send_message(
    message: str = Form(..., min_length=1, max_length=2000),
    history: str = Form(default="[]"),
    file: UploadFile | None = File(default=None),
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    if not _rate_limiter.allow(user["user_id"]):
        raise HTTPException(
            status_code=429,
            detail=f"ส่งข้อความเร็วเกินไป (จำกัด {CHATBOT_RATE_LIMIT_PER_MINUTE} ข้อความ/นาที) กรุณารอสักครู่แล้วลองใหม่",
        )

    try:
        turns = _history_adapter.validate_json(history)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="history ไม่ถูกต้อง") from exc
    history_dicts = [turn.model_dump() for turn in turns]

    attachment: tuple[bytes, str] | None = None
    if file is not None:
        ext = os.path.splitext(file.filename or "")[1].lower()
        mime = ATTACHMENT_MIME_BY_EXT.get(ext)
        if mime is None:
            raise HTTPException(status_code=422, detail=f"ไม่รองรับไฟล์นามสกุล {ext or '(ไม่ทราบ)'}")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="ไฟล์ว่างเปล่า")
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(status_code=413, detail="ไฟล์ต้องมีขนาดไม่เกิน 10MB")
        attachment = (content, mime)

    try:
        return chatbot_service.handle_message(conn, user, message, history_dicts, attachment=attachment)
    except ServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
