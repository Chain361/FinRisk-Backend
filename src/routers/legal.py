# -*- coding: utf-8 -*-
"""
/legal + /risk/projects/{project_id}/legal — ชั้นกฎหมาย (legal linkage)

router บางที่สุด: ตรรกะ/scope guard อยู่ใน src/services/legal.py เพื่อให้ chatbot
เรียก service function เดียวกันได้โดยไม่เขียน SQL เอง (legal_linkage_plan §5.1)
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..database import get_db
from ..services import legal as legal_service
from ..services.common import ForbiddenError, NotFoundError

router = APIRouter(prefix="/legal", tags=["legal"])
project_router = APIRouter(prefix="/risk/projects", tags=["legal"])


@router.get("/laws")
def list_laws(
    _: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """กฎหมาย + มาตรา/ข้อ ที่ curate ไว้ทั้งหมด (reference — ไม่มี scope ตำบล)"""
    return legal_service.list_laws(conn)


@project_router.get("/{project_id}/legal")
def project_legal(
    project_id: str,
    only_triggered: bool = Query(default=False, description="คืนเฉพาะข้อบ่งชี้ที่ triggered=1"),
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """ผล risk factor ล่าสุด + `computable` + action_suggestion + legal_refs (payload เดียวจบ)"""
    try:
        return legal_service.project_legal_view(conn, project_id, user, only_triggered)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
