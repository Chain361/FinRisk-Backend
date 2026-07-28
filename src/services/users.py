# -*- coding: utf-8 -*-
"""
users.py (service) — จัดการผู้ใช้ (GET รายชื่อ + สร้าง/แก้ไข/ลบ)

เข้าถึงได้เฉพาะ admin (บังคับที่ router ผ่าน require_roles) — ไม่เกี่ยวกับ login/JWT
(src/auth.py) เลย ตาม CLAUDE.md ยกเว้น create_user ที่ต้อง hash password ตอนสร้างบัญชีใหม่
(เรียก hash_password จาก src/auth.py ตรงๆ ไม่ยุ่งกับ token/login flow)
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


def create_user(conn: sqlite3.Connection, values: dict) -> dict:
    """สร้างผู้ใช้ใหม่ — values มาจาก UserCreate.model_dump()"""
    existing = conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (values["username"],)
    ).fetchone()
    if existing is not None:
        raise ValidationError(f"username '{values['username']}' มีอยู่แล้วในระบบ")

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

    from ..auth import hash_password  # import ในฟังก์ชันเลี่ยง circular import เหมือน common.py

    cursor = conn.execute(
        """INSERT INTO users (username, password_hash, display_name, role, subdistrict_id,
                               status, allowed_features)
           VALUES (?,?,?,?,?,?,?)
           RETURNING user_id""",
        (
            values["username"],
            hash_password(values["password"]),
            values.get("display_name"),
            values["role"],
            values.get("subdistrict_id"),
            values.get("status", "active"),
            values.get("allowed_features", []),
        ),
    )
    user_id = cursor.fetchone()["user_id"]
    conn.commit()
    return get_user(conn, user_id)


def delete_user(conn: sqlite3.Connection, user_id: int, current_user: dict) -> None:
    """ลบผู้ใช้ (hard delete) — ห้ามลบบัญชีของตัวเอง"""
    get_user(conn, user_id)  # 404 ถ้าไม่พบ ก่อนลบอะไร

    if user_id == current_user["user_id"]:
        raise ValidationError("ไม่สามารถลบบัญชีของตัวเองได้")

    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
