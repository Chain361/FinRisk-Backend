# -*- coding: utf-8 -*-
"""/chatbot — ผู้ช่วยตอบคำถาม (Gemini function-calling) สำหรับ project_auditor/risk_analyst

router บาง: orchestration + tool dispatch อยู่ใน src/services/chatbot.py ทั้งหมด
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_roles
from ..database import Connection, get_db
from ..schemas import ChatMessageRequest
from ..services import chatbot as chatbot_service
from ..services.common import ServiceError

router = APIRouter(prefix="/chatbot", tags=["chatbot"])


@router.post("")
def send_message(
    payload: ChatMessageRequest,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    history = [turn.model_dump() for turn in payload.history]
    try:
        return chatbot_service.handle_message(conn, user, payload.message, history)
    except ServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
