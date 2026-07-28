# -*- coding: utf-8 -*-
"""/chatbot — ผู้ช่วยตอบคำถาม (Gemini function-calling) สำหรับ project_auditor/risk_analyst

router บาง: orchestration + tool dispatch อยู่ใน src/services/chatbot.py ทั้งหมด
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_roles
from ..config import CHATBOT_RATE_LIMIT_PER_MINUTE
from ..database import Connection, get_db
from ..rate_limit import SlidingWindowRateLimiter
from ..schemas import ChatMessageRequest
from ..services import chatbot as chatbot_service
from ..services.common import ServiceError

router = APIRouter(prefix="/chatbot", tags=["chatbot"])

_rate_limiter = SlidingWindowRateLimiter(CHATBOT_RATE_LIMIT_PER_MINUTE, window_seconds=60)


@router.post("")
def send_message(
    payload: ChatMessageRequest,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    if not _rate_limiter.allow(user["user_id"]):
        raise HTTPException(
            status_code=429,
            detail=f"ส่งข้อความเร็วเกินไป (จำกัด {CHATBOT_RATE_LIMIT_PER_MINUTE} ข้อความ/นาที) กรุณารอสักครู่แล้วลองใหม่",
        )
    history = [turn.model_dump() for turn in payload.history]
    try:
        return chatbot_service.handle_message(conn, user, payload.message, history)
    except ServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
