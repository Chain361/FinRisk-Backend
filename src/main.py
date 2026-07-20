# -*- coding: utf-8 -*-
"""
main.py — FastAPI application entry point

รัน (จาก repo root):
    uvicorn src.main:app --reload
เปิด docs อัตโนมัติที่ http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .audit_log import record_access, should_log
from .config import API_TITLE, API_VERSION, CORS_ORIGINS, DB_PATH
from .database import _connect
from .routers import audit, auth, financials, projects, risk, subdistricts

app = FastAPI(title=API_TITLE, version=API_VERSION)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """บันทึกการเข้าถึงของผู้ใช้ที่ login แล้ว (accountability trail) — best-effort ไม่ทำให้ request พัง"""
    response = await call_next(request)
    username = request.headers.get("x-username")
    if username and should_log(request.method, request.url.path):
        forwarded = request.headers.get("x-forwarded-for")
        ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else None
        )
        record_access(
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
)

app.include_router(auth.router)
app.include_router(subdistricts.router)
app.include_router(projects.router)
app.include_router(risk.router)
app.include_router(audit.router)
app.include_router(financials.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.get("/", tags=["meta"])
def root():
    return {"service": API_TITLE, "version": API_VERSION, "docs": "/docs"}
