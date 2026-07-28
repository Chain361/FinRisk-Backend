# -*- coding: utf-8 -*-
"""
users.py (service) — จัดการผู้ใช้ (GET รายชื่อ + แก้ไข status/allowed_features)

เข้าถึงได้เฉพาะ admin (บังคับที่ router ผ่าน require_roles) — ไม่แตะ users.password_hash
และไม่เกี่ยวกับ login/JWT (src/auth.py) เลย ตาม CLAUDE.md
"""
import sqlite3

from .common import NotFoundError, ValidationError

USER_COLUMNS = "user_id, username, display_name, role, subdistrict_id, status, allowed_features"


def get_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {USER_COLUMNS} FROM users ORDER BY user_id").fetchall()
    return [dict(r) for r in rows]


def get_user(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFoundError("ไม่พบผู้ใช้นี้")
    return dict(row)


def update_user(conn: sqlite3.Connection, user_id: int, values: dict) -> dict:
    """แก้ไขข้อมูลผู้ใช้บางส่วน — values มาจาก UserUpdate.model_dump(exclude_unset=True)"""
    get_user(conn, user_id)  # 404 ถ้าไม่พบ ก่อนแก้ไขอะไร

    if "role" in values:
        role_row = conn.execute(
            "SELECT 1 FROM roles WHERE role_code = ?", (values["role"],)
        ).fetchone()
        if role_row is None:
            raise ValidationError(f"role '{values['role']}' ไม่มีอยู่ในระบบ")

    if values.get("subdistrict_id") is not None:
        sub_row = conn.execute(
            "SELECT 1 FROM subdistricts WHERE subdistrict_id = ?", (values["subdistrict_id"],)
        ).fetchone()
        if sub_row is None:
            raise ValidationError(f"subdistrict_id '{values['subdistrict_id']}' ไม่มีอยู่ในระบบ")

    if values:
        columns = list(values)
        set_clause = ", ".join(f"{column} = ?" for column in columns)
        conn.execute(
            f"UPDATE users SET {set_clause} WHERE user_id = ?",
            [values[column] for column in columns] + [user_id],
        )
        conn.commit()

    return get_user(conn, user_id)
