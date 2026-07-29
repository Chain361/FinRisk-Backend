# -*- coding: utf-8 -*-
"""
main.py — FastAPI application entry point

รัน (จาก repo root):
    uvicorn src.main:app --reload
เปิด docs อัตโนมัติที่ http://127.0.0.1:8000/docs
"""
import logging
import os

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask

from .audit_log import record_access, should_log
from .config import (
    API_TITLE,
    API_VERSION,
    CORS_ORIGINS,
    JWT_ALGORITHM,
    JWT_SECRET,
    JWT_SECRET_DEFAULT,
    PINECONE_API_KEY,
    QWEN_API_KEY,
)
from .database import _connect, _pool
from .error_log import record_error_debug
from .routers import (
    admin,
    audit,
    auth,
    chatbot,
    documents,
    financials,
    legal,
    notifications,
    projects,
    public,
    risk,
    subdistricts,
    users,
)

log = logging.getLogger("finrisk.main")
if JWT_SECRET == JWT_SECRET_DEFAULT:
    if os.getenv("VERCEL_ENV") == "production":
        # Vercel ตั้ง VERCEL_ENV=production เองตอน deploy จริง (ต่างจาก preview/development)
        # — fail-fast ตรงนี้กันไม่ให้ deploy ขึ้น prod โดยลืมตั้ง JWT_SECRET แล้วรันเงียบๆ ด้วยค่าที่รู้กันอยู่แล้ว
        raise RuntimeError(
            "JWT_SECRET ยังเป็นค่า default ที่ไม่ปลอดภัย แต่รันอยู่บน production (VERCEL_ENV=production) — "
            "ต้องตั้ง env var JWT_SECRET เป็นค่าสุ่มยาวๆ ก่อน deploy"
        )
    log.warning(
        "JWT_SECRET ยังเป็นค่า default ที่ไม่ปลอดภัย — ตั้ง env var JWT_SECRET เป็นค่าสุ่มยาวๆ ก่อนขึ้น production"
    )
if not QWEN_API_KEY:
    log.warning("QWEN_API_KEY ยังไม่ได้ตั้งค่า — POST /chatbot จะตอบ 503 จนกว่าจะตั้ง env var นี้")
if not PINECONE_API_KEY:
    # feature flag: ไม่มีคีย์ = ไม่ประกาศ tool ค้นเอกสารให้ Qwen เลย (ระบบเดิม tool 5 ตัวทำงานครบ)
    log.warning(
        "PINECONE_API_KEY ยังไม่ได้ตั้งค่า — chatbot จะไม่มี tool ค้นเนื้อหาเอกสารเต็ม "
        "และ GET /projects/{id}/documents/search จะตอบ 503"
    )

app = FastAPI(title=API_TITLE, version=API_VERSION)


def _username_for_log(request: Request) -> str | None:
    """ดึง username สำหรับ access log — รองรับทั้ง JWT (Authorization: Bearer) และ
    X-Username แบบเดิม (ช่วงเปลี่ยนผ่าน ดู src/auth.py)"""
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        try:
            payload = jwt.decode(authorization[7:].strip(), JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload.get("sub")
        except jwt.InvalidTokenError:
            return None
    return request.headers.get("x-username")


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """บันทึกการเข้าถึงของผู้ใช้ที่ login แล้ว (accountability trail) — best-effort ไม่ทำให้ request พัง

    audit access log เขียนเป็น BackgroundTask (รันหลังส่ง response กลับให้ client แล้ว) แทนการ
    await ตรงนี้ — record_access เปิด connection ของตัวเอง + SELECT/INSERT/commit ซึ่งถ้า await
    ตรงนี้จะบวกเวลานั้นเข้าไปใน response time ของทุก request แบบไม่จำเป็น"""
    username = _username_for_log(request)
    try:
        response = await call_next(request)
    except Exception as exc:
        record_error_debug(
            level="error",
            logger_name="finrisk.request",
            message=str(exc),
            method=request.method,
            path=request.url.path,
            status_code=500,
            username=username,
            request_id=request.headers.get("x-request-id"),
            exc=exc,
            connect=_connect,
        )
        raise
    if response.status_code >= 500:
        record_error_debug(
            level="error",
            logger_name="finrisk.request",
            message=f"HTTP {response.status_code} response",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            username=username,
            request_id=request.headers.get("x-request-id"),
            connect=_connect,
        )
    if username and should_log(request.method, request.url.path):
        forwarded = request.headers.get("x-forwarded-for")
        ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else None
        )
        response.background = BackgroundTask(
            record_access,
            username=username,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            connect=_connect,
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # อนุญาต frontend ที่ deploy บน Vercel ทุก subdomain (รวม preview URL) — สำหรับ prototype
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browser จะอ่าน response header นอก CORS safelist ไม่ได้ถ้าไม่ expose ไว้
    # frontend ต้องใช้ชื่อไฟล์จาก Content-Disposition แทน fallback name ตอนดาวน์โหลด export
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(subdistricts.router)
app.include_router(projects.router)
app.include_router(risk.router)
app.include_router(audit.router)
app.include_router(financials.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(notifications.router)
app.include_router(public.router)
# ชั้นกฎหมาย + ชั้นเอกสาร (legal linkage) — endpoint เดิมไม่ถูกแตะ
app.include_router(legal.router)
app.include_router(legal.project_router)
app.include_router(documents.router)
app.include_router(documents.project_router)
app.include_router(chatbot.router)


@app.get("/health", tags=["meta"])
def health():
    try:
        conn = _connect()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return {"status": "ok", "db": "postgresql", "db_connected": True}
    except Exception as exc:  # noqa: BLE001 — health check ต้องไม่ throw, บอกสถานะผ่าน body แทน
        return {"status": "error", "db": "postgresql", "db_connected": False, "detail": str(exc)}


@app.get("/meta", tags=["meta"])
def meta():
    """เมทาดาทาระดับระบบสำหรับแสดง 'ข้อมูล ณ วันที่ …' + ช่วงปีงบที่ครอบคลุม
    (public เหมือน /health — ไม่ต้อง auth) ป้องกัน frontend แสดงวันที่ปัจจุบันของเครื่องผู้ใช้"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = 'data_seeded_at'"
        ).fetchone()
        data_seeded_at = row["value"] if row else None
        span = conn.execute(
            "SELECT MIN(fiscal_year) AS min_y, MAX(fiscal_year) AS max_y FROM financial_statements"
        ).fetchone()
    finally:
        conn.close()
    return {
        "data_seeded_at": data_seeded_at,
        "fiscal_year_min": span["min_y"] if span else None,
        "fiscal_year_max": span["max_y"] if span else None,
    }


@app.get("/", tags=["meta"])
def root():
    return {"service": API_TITLE, "version": API_VERSION, "docs": "/docs"}


@app.on_event("shutdown")
def _close_pool():
    _pool.close()
