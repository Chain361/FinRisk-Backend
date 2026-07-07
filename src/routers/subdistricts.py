# -*- coding: utf-8 -*-
"""/subdistricts — ข้อมูลตำบล (master + note ความครบถ้วนข้อมูล)"""
import sqlite3

from fastapi import APIRouter, Depends

from ..auth import get_current_user, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/subdistricts", tags=["subdistricts"])


@router.get("")
def list_subdistricts(
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    ids = scope_subdistrict_ids(conn, user)
    if ids is None:
        rows = conn.execute("SELECT * FROM subdistricts ORDER BY subdistrict_id").fetchall()
    elif not ids:
        rows = []
    else:
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM subdistricts WHERE subdistrict_id IN ({ph}) ORDER BY subdistrict_id",
            ids,
        ).fetchall()
    return rows_to_dicts(rows)
