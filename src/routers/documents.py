# -*- coding: utf-8 -*-
"""
/documents/types + /projects/{project_id}/documents — ชั้นเอกสาร (document intelligence)

v1 ข้อมูลเป็น mock/manual (`source='mock'`) ยังไม่มี OCR — เมื่อ OCR จริงมา
จะเขียนลงตารางเดิมด้วย `source='ocr'` โดย endpoint นี้ไม่ต้องแก้
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..database import get_db
from ..services import documents as doc_service
from ..services.common import ForbiddenError, NotFoundError

router = APIRouter(prefix="/documents", tags=["documents"])
project_router = APIRouter(prefix="/projects", tags=["documents"])


@router.get("/types")
def list_document_types(
    _: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """ประเภทเอกสาร + `provides` (เอกสารนั้นระบุอะไร) — reference ไม่มี scope ตำบล"""
    return doc_service.list_document_types(conn)


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
