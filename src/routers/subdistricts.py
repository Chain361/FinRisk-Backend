# -*- coding: utf-8 -*-
"""/subdistricts — ข้อมูลตำบล (master + note ความครบถ้วนข้อมูล)"""
from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..database import Connection, get_db
from ..services import subdistricts as subdistricts_service

router = APIRouter(prefix="/subdistricts", tags=["subdistricts"])


@router.get("")
def list_subdistricts(
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    return subdistricts_service.list_subdistricts_view(conn, user)
