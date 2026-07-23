# -*- coding: utf-8 -*-
"""
/audit — งานตรวจสอบ (assignment) และรายงานผล (audit_report / feedback)

Flow (ตาม roles.md):
  project_auditor มอบหมายงาน -> risk_analyst รับงาน -> ส่งรายงานผล
หมายเหตุ: ตาราง audit_assignments / audit_reports ยังว่างใน seed (endpoint สำหรับสองตารางนี้
ยังเป็น scaffold) — auditor_feedback มี CRUD ครบแล้ว (F5: บันทึกความคิดเห็น draft -> submitted -> resolved)
"""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth import require_roles, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts
from ..schemas import AuditorFeedbackIn, AuditorFeedbackOut

router = APIRouter(prefix="/audit", tags=["audit"])

# roles ที่เห็น/เขียน audit feedback ได้ (ตาม roles.md — ระดับเดียวกับ /audit/feedback เดิม)
FEEDBACK_ROLES = ("admin", "regional_supervisor", "local_executive", "project_auditor", "risk_analyst")
# roles ที่ปิดเรื่อง (resolve) ได้ — ผู้ตรวจสอบ/แอดมินเท่านั้น ตรงกับ canResolveFeedback ฝั่ง frontend
RESOLVE_ROLES = ("admin", "project_auditor")


def _now_str() -> str:
    """รูปแบบเดียวกับ sqlite `datetime('now')` (UTC, 'YYYY-MM-DD HH:MM:SS')"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _serialize_feedback(row: sqlite3.Row) -> dict:
    """เติม risk_score (คำนวณจาก likelihood_score × impact_score ไม่เก็บเป็นคอลัมน์แยก)"""
    data = dict(row)
    likelihood = data.get("likelihood_score")
    impact = data.get("impact_score")
    data["risk_score"] = likelihood * impact if likelihood is not None and impact is not None else None
    return data


def _fetch_feedback(conn: sqlite3.Connection, feedback_id: int) -> dict:
    row = conn.execute(
        """SELECT f.*, u.username AS auditor_username, u.display_name AS auditor_name
           FROM auditor_feedback f JOIN users u ON u.user_id = f.user_id
           WHERE f.feedback_id = ?""",
        (feedback_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็น")
    return _serialize_feedback(row)


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


@router.get("/feedback", response_model=list[AuditorFeedbackOut])
def list_feedback(
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """feedback ทั้งหมดที่ user เห็นได้ (scope ตามตำบลเหมือน /projects) — ใช้แสดงสถานะบนรายการโครงการ
    โดยไม่ต้องยิง request แยกทีละโครงการ"""
    allowed = scope_subdistrict_ids(conn, user)
    where_sql = ""
    params: list = []
    if allowed is not None:
        if not allowed:
            return []
        where_sql = f"WHERE p.subdistrict_id IN ({','.join('?' * len(allowed))})"
        params = list(allowed)

    rows = conn.execute(
        f"""SELECT f.*, u.username AS auditor_username, u.display_name AS auditor_name
            FROM auditor_feedback f
            JOIN users u ON u.user_id = f.user_id
            JOIN projects p ON p.project_id = f.project_id
            {where_sql}
            ORDER BY f.updated_at DESC""",
        params,
    ).fetchall()
    return [_serialize_feedback(r) for r in rows]


@router.get("/feedback/{project_id}", response_model=list[AuditorFeedbackOut])
def project_feedback(
    project_id: str,
    # View Public Audit Information ตาม roles.md — public_user ไม่มีสิทธิ์ (ข้อมูลที่ถูกปิดไว้)
    _: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """SELECT f.*, u.username AS auditor_username, u.display_name AS auditor_name
           FROM auditor_feedback f JOIN users u ON u.user_id = f.user_id
           WHERE f.project_id = ? ORDER BY f.updated_at DESC""",
        (project_id,),
    ).fetchall()
    return [_serialize_feedback(r) for r in rows]


@router.post("/feedback", response_model=AuditorFeedbackOut, status_code=201)
def create_feedback(
    body: AuditorFeedbackIn,
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    project = conn.execute(
        "SELECT 1 FROM projects WHERE project_id = ?", (body.project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")

    now = _now_str()
    cur = conn.execute(
        """INSERT INTO auditor_feedback
           (project_id, user_id, feedback_text, concern_level, likelihood_score, impact_score,
            suggestions, status, created_at, updated_at, submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            body.project_id,
            user["user_id"],
            body.feedback_text,
            body.concern_level,
            body.likelihood_score,
            body.impact_score,
            body.suggestions,
            body.status,
            now,
            now,
            now if body.status == "submitted" else None,
        ),
    )
    conn.commit()
    return _fetch_feedback(conn, cur.lastrowid)


@router.patch("/feedback/{feedback_id}", response_model=AuditorFeedbackOut)
def update_feedback(
    feedback_id: int,
    body: AuditorFeedbackIn,
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute(
        "SELECT user_id, status, submitted_at FROM auditor_feedback WHERE feedback_id = ?",
        (feedback_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็น")
    if row["user_id"] != user["user_id"] and user["role"] not in RESOLVE_ROLES:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์แก้ไขความคิดเห็นนี้")
    if row["status"] != "draft":
        raise HTTPException(status_code=409, detail="แก้ไขได้เฉพาะความคิดเห็นที่เป็นฉบับร่างเท่านั้น")

    now = _now_str()
    submitted_at = now if body.status == "submitted" else row["submitted_at"]
    conn.execute(
        """UPDATE auditor_feedback
           SET feedback_text = ?, concern_level = ?, likelihood_score = ?, impact_score = ?,
               suggestions = ?, status = ?, updated_at = ?, submitted_at = ?
           WHERE feedback_id = ?""",
        (
            body.feedback_text,
            body.concern_level,
            body.likelihood_score,
            body.impact_score,
            body.suggestions,
            body.status,
            now,
            submitted_at,
            feedback_id,
        ),
    )
    conn.commit()
    return _fetch_feedback(conn, feedback_id)


@router.delete("/feedback/{feedback_id}", status_code=204)
def delete_feedback(
    feedback_id: int,
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute(
        "SELECT user_id FROM auditor_feedback WHERE feedback_id = ?", (feedback_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็น")
    if row["user_id"] != user["user_id"] and user["role"] not in RESOLVE_ROLES:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ลบความคิดเห็นนี้")

    conn.execute("DELETE FROM auditor_feedback WHERE feedback_id = ?", (feedback_id,))
    conn.commit()
    return Response(status_code=204)


@router.patch("/feedback/{feedback_id}/resolve", response_model=AuditorFeedbackOut)
def resolve_feedback(
    feedback_id: int,
    _: dict = Depends(require_roles(*RESOLVE_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute(
        "SELECT feedback_id FROM auditor_feedback WHERE feedback_id = ?", (feedback_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็น")

    now = _now_str()
    conn.execute(
        "UPDATE auditor_feedback SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE feedback_id = ?",
        (now, now, feedback_id),
    )
    conn.commit()
    return _fetch_feedback(conn, feedback_id)


@router.get("/access-log")
def access_log(
    _: dict = Depends(require_roles("admin")),  # เฉพาะผู้ดูแลระบบ — log การเข้าถึงเป็นข้อมูลอ่อนไหว
    conn: sqlite3.Connection = Depends(get_db),
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: str | None = None,  # 'YYYY-MM-DD' (รวม)
    date_to: str | None = None,    # 'YYYY-MM-DD' (รวมทั้งวัน)
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """บันทึกการเข้าถึงของผู้ใช้ (accountability trail) — กรอง + แบ่งหน้า
    คืน {items, total, limit, offset}; เรียงใหม่สุดก่อน"""
    where: list[str] = []
    params: list = []
    if username:
        where.append("username = ?")
        params.append(username)
    if action:
        where.append("action = ?")
        params.append(action)
    if resource_type:
        where.append("resource_type = ?")
        params.append(resource_type)
    if date_from:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("created_at < date(?, '+1 day')")
        params.append(date_to)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM access_log{clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT log_id, username, role, action, method, path, resource_type,
                   resource_id, status_code, ip, user_agent, created_at
            FROM access_log{clause}
            ORDER BY log_id DESC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    return {
        "items": rows_to_dicts(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ตัวอย่าง endpoint ที่จำกัดสิทธิ์ — เปิดใช้เมื่อพร้อมทำ business logic เขียนข้อมูล
# @router.post("/assignments")
# def create_assignment(user: dict = Depends(require_roles("project_auditor", "admin")), ...):
#     ...
