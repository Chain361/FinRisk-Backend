# -*- coding: utf-8 -*-
"""
common.py — ตัวช่วยที่ service function ใช้ร่วมกัน

ข้อสำคัญ: service ไม่ raise HTTPException เอง (จะถูกเรียกจาก agent tool ด้วย)
→ raise domain error แล้วให้ router แปลงเป็น HTTP status
"""
import json
import sqlite3


class ServiceError(Exception):
    """base ของ error ที่ router ต้องแปลงเป็น HTTP response"""


class NotFoundError(ServiceError):
    pass


class ForbiddenError(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


def latest_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT run_id FROM assessment_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


def load_project_in_scope(
    conn: sqlite3.Connection, project_id: str, user: dict
) -> sqlite3.Row:
    """
    หาโครงการ + บังคับ scope guard ตาม role (roles.md)

    NotFoundError  → 404 (ไม่พบ project_id)
    ForbiddenError → 403 (โครงการอยู่นอกตำบลที่ user เห็นได้ หรือไม่ใช่งานที่ได้รับมอบหมาย)
    """
    # import ในฟังก์ชันเพื่อเลี่ยง circular import (auth → database → services)
    from ..auth import scope_subdistrict_ids

    row = conn.execute(
        "SELECT project_id, project_name, subdistrict_id, project_type, "
        "       purchase_method_group, budget_amount, reference_price, contract_value, "
        "       dept_name, data_quality_note "
        "FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("ไม่พบโครงการ")

    allowed = scope_subdistrict_ids(conn, user)
    if allowed is not None and row["subdistrict_id"] not in allowed:
        raise ForbiddenError("ไม่มีสิทธิ์เข้าถึงโครงการนอกตำบลของคุณ")
    if user["role"] == "risk_analyst":
        assignment = conn.execute(
            "SELECT 1 FROM assignments WHERE project_id = ? AND assigned_to = ? LIMIT 1",
            (project_id, user["user_id"]),
        ).fetchone()
        if assignment is None:
            raise ForbiddenError("นักวิเคราะห์เห็นได้เฉพาะโครงการที่ได้รับมอบหมาย")
    return row


def parse_json(text: str | None, default):
    """แปลงคอลัมน์ที่เก็บ JSON เป็น object — ข้อมูลเสียหายไม่ควรทำ endpoint ล้ม"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default
