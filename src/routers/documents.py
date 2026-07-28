# -*- coding: utf-8 -*-
"""
/documents/types + /projects/{project_id}/documents — ชั้นเอกสาร (document intelligence)

v1 ข้อมูลเป็น mock/manual (`source='mock'`) ยังไม่มี OCR — เมื่อ OCR จริงมา
จะเขียนลงตารางเดิมด้วย `source='ocr'` โดย endpoint นี้ไม่ต้องแก้
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..database import get_db
from ..services import documents as doc_service
from ..services import retrieval as retrieval_service
from ..services.common import ForbiddenError, NotFoundError, ServiceError

router = APIRouter(prefix="/documents", tags=["documents"])
project_router = APIRouter(prefix="/projects", tags=["documents"])


@router.get("/types")
def list_document_types(
    _: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """ประเภทเอกสาร + `provides` (เอกสารนั้นระบุอะไร) — reference ไม่มี scope ตำบล"""
    return doc_service.list_document_types(conn)


@project_router.get("/{project_id}/documents/search")
def search_project_documents(
    project_id: str,
    q: str = Query(min_length=1, max_length=500, description="ข้อความค้นหา (ภาษาไทยได้)"),
    top_k: int = Query(default=None, ge=1, le=20),
    min_score: float = Query(
        default=None, ge=0, le=1,
        description="override RAG_MIN_SCORE — ใส่ 0 เพื่อดูคะแนนดิบทุก hit ตอน calibrate",
    ),
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """ค้นข้อความจากเนื้อหาเอกสารเต็มของโครงการ (Pinecone) — คืน `score` ดิบมาด้วยเสมอ

    มีไว้เพื่อ (1) ทดสอบชั้น RAG ด้วย curl โดยไม่ผ่าน Gemini แยก "ค้นไม่เจอ" ออกจาก "LLM ตอบไม่ดี"
    และ (2) calibrate `RAG_MIN_SCORE` (แผน §6.6, งาน #4.5)
    scope guard สองชั้นอยู่ใน service — endpoint นี้ไม่ได้ผ่อนอะไรให้เลย
    """
    try:
        return retrieval_service.search_document_text(
            conn, user, q, project_id=project_id, top_k=top_k, min_score=min_score
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ServiceError as exc:  # ยังไม่ได้ตั้ง PINECONE_API_KEY
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@project_router.get("/{project_id}/documents")
def project_documents(
    project_id: str,
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """เอกสารของโครงการ + สถานะ + รายการที่ยังขาด + findings พร้อม legal refs"""
    try:
        return doc_service.project_documents_view(conn, project_id, user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
