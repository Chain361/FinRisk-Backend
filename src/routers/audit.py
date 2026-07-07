# -*- coding: utf-8 -*-
"""
/audit — งานตรวจสอบ (assignment) และรายงานผล (audit_report / feedback)

Flow (ดู สรุป Flow การตรวจสอบคร่าวๆ.md):
  auditor(ผู้ตรวจสอบโครงการ) มอบหมายงาน -> auditor(นักวิเคราะห์) รับงาน -> ส่งรายงานผล
หมายเหตุ: ตาราง audit_assignments / audit_reports / auditor_feedback ยังว่างใน seed
scaffold นี้แค่วาง endpoint โครงไว้ ปรับ business logic ตามจริงภายหลัง
"""
import sqlite3

from fastapi import APIRouter, Depends

from ..auth import get_current_user, require_roles
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/assignments")
def my_assignments(
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """นักวิเคราะห์เห็นเฉพาะงานที่ได้รับมอบหมาย; admin/auditor เห็นทั้งหมด"""
    if user["role"] == "auditor":
        rows = conn.execute(
            """SELECT a.*, p.project_name
               FROM audit_assignments a JOIN projects p ON p.project_id = a.project_id
               WHERE a.assigned_to = ? ORDER BY a.created_at DESC""",
            (user["user_id"],),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT a.*, p.project_name
               FROM audit_assignments a JOIN projects p ON p.project_id = a.project_id
               ORDER BY a.created_at DESC"""
        ).fetchall()
    return rows_to_dicts(rows)


@router.get("/feedback/{project_id}")
def project_feedback(
    project_id: str,
    _: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """SELECT f.*, u.display_name
           FROM auditor_feedback f JOIN users u ON u.user_id = f.user_id
           WHERE f.project_id = ? ORDER BY f.created_at DESC""",
        (project_id,),
    ).fetchall()
    return rows_to_dicts(rows)


# ตัวอย่าง endpoint ที่จำกัดสิทธิ์ — เปิดใช้เมื่อพร้อมทำ business logic เขียนข้อมูล
# @router.post("/assignments")
# def create_assignment(user: dict = Depends(require_roles("auditor", "admin")), ...):
#     ...
