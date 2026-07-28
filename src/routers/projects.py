# -*- coding: utf-8 -*-
"""/projects — โครงการจัดซื้อจัดจ้าง + risk score ล่าสุด

router บาง: ตรรกะ + scope guard อยู่ใน src/services/projects.py เพื่อให้ chatbot
เรียก service function เดียวกันได้โดยไม่เขียน SQL เอง (เหมือน routers/legal.py, routers/documents.py)
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..database import Connection, get_db
from ..services import projects as projects_service
from ..services.common import ForbiddenError, NotFoundError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(
    budget_year: int | None = Query(default=None),
    subdistrict_id: int | None = Query(default=None),
    risk_level: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    return projects_service.list_projects_view(
        conn, user, budget_year=budget_year, subdistrict_id=subdistrict_id, risk_level=risk_level
    )


@router.get("/{project_id}")
def get_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    try:
        return projects_service.project_summary_view(conn, project_id, user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
