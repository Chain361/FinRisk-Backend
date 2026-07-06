# -*- coding: utf-8 -*-
"""
main.py — FastAPI application entry point

รัน (จาก repo root):
    uvicorn src.main:app --reload
เปิด docs อัตโนมัติที่ http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import API_TITLE, API_VERSION, CORS_ORIGINS, DB_PATH
from .routers import audit, auth, projects, risk, subdistricts

app = FastAPI(title=API_TITLE, version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(subdistricts.router)
app.include_router(projects.router)
app.include_router(risk.router)
app.include_router(audit.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.get("/", tags=["meta"])
def root():
    return {"service": API_TITLE, "version": API_VERSION, "docs": "/docs"}
