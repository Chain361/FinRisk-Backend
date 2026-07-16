# -*- coding: utf-8 -*-
"""
/audit — งานตรวจสอบ (assignment) และรายงานผล (audit_report / feedback)

Flow (ตาม roles.md):
  project_auditor มอบหมายงาน -> risk_analyst รับงาน -> ส่งรายงานผล
หมายเหตุ: ตาราง audit_assignments / audit_reports / auditor_feedback ยังว่างใน seed
scaffold นี้แค่วาง endpoint โครงไว้ ปรับ business logic ตามจริงภายหลัง
"""
import sqlite3

from fastapi import APIRouter, Depends

from ..auth import require_roles, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/assignments")
def my_assignments(
    user: dict = Depends(require_roles("admin", "regional_supervisor",
                                       "project_auditor", "risk_analyst")),
    conn: sqlite3.Connection = Depends(get_db),
):
    """risk_analyst เห็นเฉพาะงานที่ได้รับมอบหมาย (View Assigned Projects);
    project_auditor/admin/regional_supervisor เห็นทั้งหมดในขอบเขตตำบลของตน (scope guard)"""
    if user["role"] == "risk_analyst":
        rows = conn.execute(
            """SELECT a.*, p.project_name
               FROM audit_assignments a JOIN projects p ON p.project_id = a.project_id
               WHERE a.assigned_to = ? ORDER BY a.created_at DESC""",
            (user["user_id"],),
        ).fetchall()
    else:
        scope = scope_subdistrict_ids(conn, user)
        sql = """SELECT a.*, p.project_name
                 FROM audit_assignments a JOIN projects p ON p.project_id = a.project_id"""
        params: list = []
        if scope is not None:
            sql += " WHERE p.subdistrict_id IN ({})".format(",".join("?" * len(scope)) or "NULL")
            params = scope
        rows = conn.execute(sql + " ORDER BY a.created_at DESC", params).fetchall()
    return rows_to_dicts(rows)


@router.get("/feedback/{project_id}")
def project_feedback(
    project_id: str,
    # View Public Audit Information ตาม roles.md — public_user ไม่มีสิทธิ์ (ข้อมูลที่ถูกปิดไว้)
    _: dict = Depends(require_roles("admin", "regional_supervisor", "local_executive",
                                    "project_auditor", "risk_analyst")),
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
# def create_assignment(user: dict = Depends(require_roles("project_auditor", "admin")), ...):
#     ...
