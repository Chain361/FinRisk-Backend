# -*- coding: utf-8 -*-
"""/users — รายชื่อผู้ใช้ + สร้าง/แก้ไข/ลบ (admin เท่านั้น)

ไม่แตะ login/JWT/authentication flow (src/auth.py, src/routers/auth.py) ตาม CLAUDE.md —
router นี้แค่จัดการข้อมูลผู้ใช้ ไม่ยุ่งกับการออก token (create_user hash password เองตอน
สร้างบัญชีใหม่ ผ่าน src/auth.py::hash_password แต่ไม่ออก token ให้)
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import require_roles
from ..database import Connection, get_db
from ..schemas import UserCreate, UserOut, UserUpdate
from ..services import users as user_service
from ..services.common import NotFoundError, ValidationError

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    _: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    return user_service.get_users(conn)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    _: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    try:
        return user_service.create_user(conn, payload.model_dump())
    except ValidationError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    current_user: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    try:
        user_service.delete_user(conn, user_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
