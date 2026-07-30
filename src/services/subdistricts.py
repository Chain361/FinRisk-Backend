# -*- coding: utf-8 -*-
"""subdistricts (service) — ข้อมูลตำบลที่ user มีสิทธิ์เห็น

แยกออกมาจาก routers/subdistricts.py ตาม "agent tool contract" (ดู services/__init__.py)
เพื่อให้ chatbot เรียก logic + scope guard ตัวเดียวกับที่ frontend เรียกได้ — chatbot ต้องแปลง
"ชื่อตำบล" ที่ผู้ใช้พิมพ์มาเป็น subdistrict_id ก่อนถึงจะกรอง list_projects ได้
"""
import sqlite3

from ..database import rows_to_dicts


def list_subdistricts_view(conn: sqlite3.Connection, user: dict) -> list[dict]:
    """คืนตำบลทั้งหมดที่ user มีสิทธิ์เห็น (admin/regional_supervisor/public_user = ทุกตำบล)"""
    # import ในฟังก์ชันเพื่อเลี่ยง circular import (auth → database → services) — pattern เดียวกับ
    # projects.py/common.py
    from ..auth import scope_subdistrict_ids

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
