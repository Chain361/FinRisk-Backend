# -*- coding: utf-8 -*-
"""/users — รายชื่อผู้ใช้ + แก้ไข status/allowed_features (admin เท่านั้น)

ไม่แตะ login/JWT/authentication flow (src/auth.py, src/routers/auth.py) ตาม CLAUDE.md —
router นี้แค่อ่าน/แก้ไขข้อมูลผู้ใช้ที่มีอยู่ ไม่ยุ่งกับ password_hash หรือการออก token
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_roles
from ..database import Connection, get_db
from ..schemas import UserOut, UserUpdate
from ..services import users as user_service
from ..services.common import NotFoundError, ValidationError

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    _: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    return user_service.get_users(conn)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    _: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    values = payload.model_dump(exclude_unset=True)
    try:
        return user_service.update_user(conn, user_id, values)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
