# -*- coding: utf-8 -*-
"""
auth.py — JWT authentication + role/scope guard

- รหัสผ่านเก็บเป็น **bcrypt hash** (มี salt ในตัว)
- login ออก **JWT access token** (HS256, อายุ `JWT_EXPIRE_MINUTES`) — endpoint ที่ต้อง auth
  อ่าน token จาก header `Authorization: Bearer <token>`
- ⚠️ ช่วงเปลี่ยนผ่าน: ยังรับ header `X-Username` แบบเดิม (ไม่ verify ลายเซ็น) เป็น fallback
  เพราะ frontend ที่ deploy อยู่ตอนนี้ยังส่ง `X-Username` อยู่ (ดู FinRisk-Frontend issue #28
  ที่จะเปลี่ยนไปส่ง `Authorization: Bearer`) — ลบ fallback นี้ทิ้งได้เมื่อ #28 เสร็จแล้ว

Scope rule (ตาม roles.md — สิทธิ์/scope บังคับที่ app layer):
    - admin / regional_supervisor / public_user       : เห็นได้ทุกตำบล
    - local_executive / project_auditor / risk_analyst : เห็นเฉพาะตำบลของตัวเอง
                                                         (subdistrict_id ของ user)
"""
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from .database import Connection, get_db

log = logging.getLogger("finrisk.auth")

# role ที่เห็นเฉพาะตำบลของตัวเอง (ตาม roles.md) — role อื่น (admin/regional_supervisor/public_user) เห็นทุกตำบล
SCOPED_ROLES = {"local_executive", "project_auditor", "risk_analyst"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["username"],
        "user_id": user["user_id"],
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_login(conn: Connection, username: str, password: str) -> dict | None:
    row = conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id, status, allowed_features, "
        "password_hash FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    user = dict(row)
    user.pop("password_hash", None)
    return user


def _user_by_id(conn: Connection, user_id: int):
    return conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id, status, allowed_features "
        "FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def _user_by_username(conn: Connection, username: str):
    return conn.execute(
        "SELECT user_id, username, display_name, role, subdistrict_id, status, allowed_features "
        "FROM users WHERE username = ?",
        (username,),
    ).fetchone()


def get_current_user(
    authorization: str | None = Header(default=None),
    x_username: str | None = Header(default=None, alias="X-Username"),
    conn: Connection = Depends(get_db),
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token หมดอายุ กรุณาเข้าสู่ระบบใหม่")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token ไม่ถูกต้อง")
        row = _user_by_id(conn, payload["user_id"])
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ไม่พบผู้ใช้")
        return dict(row)

    if x_username:
        # ชั่วคราวระหว่างเปลี่ยนผ่าน — ไม่ verify ลายเซ็น ดูหมายเหตุด้านบนของไฟล์นี้
        log.warning("auth via legacy X-Username header (no signature) — username=%s", x_username)
        row = _user_by_username(conn, x_username)
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ไม่พบผู้ใช้")
        return dict(row)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="ต้องส่ง header Authorization: Bearer <token>",
    )


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


def scope_subdistrict_ids(conn: Connection, user: dict) -> list[int] | None:
    """
    คืน list ของ subdistrict_id ที่ user เห็นได้.
    None = เห็นได้ทุกตำบล (ไม่ต้อง filter)
    """
    if user["role"] in SCOPED_ROLES:
        return [user["subdistrict_id"]] if user["subdistrict_id"] is not None else []
    return None  # admin / regional_supervisor / public_user
