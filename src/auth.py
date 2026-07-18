# -*- coding: utf-8 -*-
"""
auth.py — MOCK authentication + role/scope guard

⚠️  นี่เป็น mock สำหรับ demo/dev เท่านั้น:
    - รหัสผ่านทุก user = "password123" (hash แบบ sha256 ธรรมดา ไม่มี salt)
    - "token" ที่คืนให้ = username ตรง ๆ (ไม่ใช่ JWT)
ก่อนขึ้น production ต้องเปลี่ยนเป็น password hashing จริง (bcrypt/argon2) + JWT/session
ดูรายละเอียดใน CLAUDE.md หัวข้อ "Auth (mock)"

Scope rule (ตาม roles.md — สิทธิ์/scope บังคับที่ app layer):
    - admin / regional_supervisor / public_user       : เห็นได้ทุกตำบล
    - local_executive / project_auditor / risk_analyst : เห็นเฉพาะตำบลของตัวเอง
                                                         (subdistrict_id ของ user)
"""
import hashlib
import sqlite3

from fastapi import Depends, Header, HTTPException, status

from .database import get_db

# role ที่เห็นเฉพาะตำบลของตัวเอง (ตาม roles.md) — role อื่น (admin/regional_supervisor/public_user) เห็นทุกตำบล
SCOPED_ROLES = {"local_executive", "project_auditor", "risk_analyst"}


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def verify_login(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    row = conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id, password_hash "
        "FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None or row["password_hash"] != sha256(password):
        return None
    user = dict(row)
    user.pop("password_hash", None)
    return user


def get_current_user(
    x_username: str | None = Header(default=None, alias="X-Username"),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """
    Mock auth dependency: อ่าน username จาก header `X-Username`.
    Production: เปลี่ยนเป็นถอด JWT จาก `Authorization: Bearer <token>`.
    """
    if not x_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ต้องส่ง header X-Username (mock auth)",
        )
    row = conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id "
        "FROM users WHERE username = ?",
        (x_username,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ไม่พบผู้ใช้")
    return dict(row)


def require_roles(*allowed: str):
    """สร้าง dependency ที่อนุญาตเฉพาะบาง role"""

    def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{user['role']}' ไม่มีสิทธิ์ (ต้องเป็น {allowed})",
            )
        return user

    return _guard


def scope_subdistrict_ids(conn: sqlite3.Connection, user: dict) -> list[int] | None:
    """
    คืน list ของ subdistrict_id ที่ user เห็นได้.
    None = เห็นได้ทุกตำบล (ไม่ต้อง filter)
    """
    if user["role"] in SCOPED_ROLES:
        return [user["subdistrict_id"]] if user["subdistrict_id"] is not None else []
    return None  # admin / regional_supervisor / public_user
