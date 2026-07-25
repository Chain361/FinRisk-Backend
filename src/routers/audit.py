# -*- coding: utf-8 -*-
"""
/audit — งานตรวจสอบ (assignment) และรายงานผล (audit_report / feedback)

Flow (ตาม roles.md):
  project_auditor มอบหมายงาน -> risk_analyst รับงาน -> ส่งรายงานผล
audit_assignments/audit_reports มี CRUD หลักครบแล้ว (create/list/delete/status/report) — ยังไม่มี:
evidence upload, clarification thread, timesheet, notifications (ไม่มีใน roles.md, ยังไม่มี UI เรียกใช้
— ดูแผนแยกก่อนเพิ่ม) auditor_feedback มี CRUD ครบแล้ว (F5: บันทึกความคิดเห็น draft -> submitted -> resolved)
"""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth import require_roles, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts
from ..schemas import (
    AssignmentAssigneeOut,
    AssignmentCreate,
    AssignmentOut,
    AssignmentStatusUpdate,
    AuditReportCreate,
    AuditReportOut,
    AuditorFeedbackIn,
    AuditorFeedbackOut,
)

router = APIRouter(prefix="/audit", tags=["audit"])

# roles ที่เห็น/เขียน audit feedback ได้ (ตาม roles.md — ระดับเดียวกับ /audit/feedback เดิม)
FEEDBACK_ROLES = ("admin", "regional_supervisor", "local_executive", "project_auditor", "risk_analyst")
# roles ที่ปิดเรื่อง (resolve) ได้ — ผู้ตรวจสอบ/แอดมินเท่านั้น ตรงกับ canResolveFeedback ฝั่ง frontend
RESOLVE_ROLES = ("admin", "project_auditor")
# roles ที่เห็น audit assignment ได้ — mirror ของ ASSIGNMENT_ROLES ฝั่ง frontend (core/auth/roles.ts)
ASSIGNMENT_ROLES = ("admin", "regional_supervisor", "project_auditor", "risk_analyst")
# roles ที่มอบหมาย/ลบ assignment ได้ — ฝั่งผู้ตรวจสอบโครงการเท่านั้น
ASSIGN_ROLES = ("admin", "project_auditor")

_ASSIGNMENT_SELECT = """
    SELECT a.*, p.project_name, p.subdistrict_id,
           au.username AS assignee_username, au.display_name AS assignee_display_name,
           ab.username AS assigned_by_username, ab.display_name AS assigned_by_display_name
    FROM audit_assignments a
    JOIN projects p ON p.project_id = a.project_id
    JOIN users au ON au.user_id = a.assigned_to
    JOIN users ab ON ab.user_id = a.assigned_by
"""


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


def _fetch_assignment(conn: sqlite3.Connection, assignment_id: int) -> dict:
    row = conn.execute(
        _ASSIGNMENT_SELECT + " WHERE a.assignment_id = ?", (assignment_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    return dict(row)


def _require_assignment_access(row: sqlite3.Row | dict, user: dict) -> None:
    """เจ้าของงาน (assignee) หรือผู้มอบหมาย (assigner) หรือ admin เท่านั้นที่แก้ assignment นี้ได้"""
    if user["role"] == "admin":
        return
    if user["user_id"] in (row["assigned_to"], row["assigned_by"]):
        return
    raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์แก้ไขงานนี้")


@router.get("/assignments", response_model=list[AssignmentOut])
def my_assignments(
    user: dict = Depends(require_roles(*ASSIGNMENT_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """risk_analyst เห็นเฉพาะงานที่ได้รับมอบหมาย (View Assigned Projects);
    project_auditor/admin/regional_supervisor เห็นทั้งหมดในขอบเขตตำบลของตน (scope guard)"""
    if user["role"] == "risk_analyst":
        rows = conn.execute(
            _ASSIGNMENT_SELECT + " WHERE a.assigned_to = ? ORDER BY a.created_at DESC",
            (user["user_id"],),
        ).fetchall()
    else:
        scope = scope_subdistrict_ids(conn, user)
        sql = _ASSIGNMENT_SELECT
        params: list = []
        if scope is not None:
            sql += " WHERE p.subdistrict_id IN ({})".format(",".join("?" * len(scope)) or "NULL")
            params = scope
        rows = conn.execute(sql + " ORDER BY a.created_at DESC", params).fetchall()
    return rows_to_dicts(rows)


@router.get("/assignments/assignees", response_model=list[AssignmentAssigneeOut])
def assignment_assignees(
    user: dict = Depends(require_roles("admin", "project_auditor", "regional_supervisor")),
    conn: sqlite3.Connection = Depends(get_db),
):
    """รายชื่อ risk_analyst ที่มอบหมายงานให้ได้ — สโคปตามตำบลเหมือนหน้าจออื่น (scope_subdistrict_ids)
    เติม active_cases = จำนวนงานที่ยังไม่ completed ของแต่ละคน สำหรับ dropdown มอบหมายงาน (F4.1)"""
    scope = scope_subdistrict_ids(conn, user)
    sql = """
        SELECT u.user_id, u.username, u.display_name, u.subdistrict_id,
               (SELECT COUNT(*) FROM audit_assignments a
                WHERE a.assigned_to = u.user_id AND a.status != 'completed') AS active_cases
        FROM users u
        WHERE u.role = 'risk_analyst'
    """
    params: list = []
    if scope is not None:
        if not scope:
            return []
        sql += " AND u.subdistrict_id IN ({})".format(",".join("?" * len(scope)))
        params = list(scope)
    rows = conn.execute(sql + " ORDER BY u.subdistrict_id, u.display_name", params).fetchall()
    return rows_to_dicts(rows)


@router.post("/assignments", response_model=AssignmentOut, status_code=201)
def create_assignment(
    body: AssignmentCreate,
    user: dict = Depends(require_roles(*ASSIGN_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    project = conn.execute(
        "SELECT subdistrict_id FROM projects WHERE project_id = ?", (body.project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")

    # project_auditor มอบหมายได้เฉพาะโครงการในตำบลตัวเอง (ตาม scope เดียวกับ /projects)
    scope = scope_subdistrict_ids(conn, user)
    if scope is not None and project["subdistrict_id"] not in scope:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์มอบหมายงานโครงการนอกตำบลของตน")

    assignee = conn.execute(
        "SELECT role, subdistrict_id FROM users WHERE user_id = ?", (body.assignee_id,)
    ).fetchone()
    if assignee is None or assignee["role"] != "risk_analyst":
        raise HTTPException(status_code=400, detail="ผู้รับมอบหมายต้องเป็นนักวิเคราะห์ (risk_analyst)")
    if assignee["subdistrict_id"] != project["subdistrict_id"]:
        raise HTTPException(status_code=400, detail="ผู้รับมอบหมายต้องอยู่ตำบลเดียวกับโครงการ")

    now = _now_str()
    cur = conn.execute(
        """INSERT INTO audit_assignments
           (project_id, assigned_to, assigned_by, priority, note, due_date, budget_hours,
            audit_steps, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,'waiting_acceptance',?,?)""",
        (
            body.project_id,
            body.assignee_id,
            user["user_id"],
            body.priority,
            body.note,
            body.due_date,
            body.budget_hours,
            body.audit_steps,
            now,
            now,
        ),
    )
    conn.commit()
    return _fetch_assignment(conn, cur.lastrowid)


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(
    assignment_id: int,
    user: dict = Depends(require_roles(*ASSIGN_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute(
        "SELECT assigned_by FROM audit_assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    if row["assigned_by"] != user["user_id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ลบงานที่มอบหมายนี้")

    has_report = conn.execute(
        "SELECT 1 FROM audit_reports WHERE assignment_id = ? LIMIT 1", (assignment_id,)
    ).fetchone()
    if has_report is not None:
        raise HTTPException(
            status_code=409, detail="ลบไม่ได้ — มีรายงานผลตรวจสอบผูกกับงานนี้แล้ว"
        )

    conn.execute("DELETE FROM audit_assignments WHERE assignment_id = ?", (assignment_id,))
    conn.commit()
    return Response(status_code=204)


@router.patch("/assignments/{assignment_id}/status", response_model=AssignmentOut)
def update_assignment_status(
    assignment_id: int,
    body: AssignmentStatusUpdate,
    user: dict = Depends(require_roles(*ASSIGNMENT_ROLES)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """v1: ยอมให้เจ้าของงาน/ผู้มอบหมาย/admin เปลี่ยนสถานะได้อย่างอิสระ (ยังไม่บังคับ state machine
    เพราะยังไม่มี UI เรียกใช้จริง — เพิ่มกติกาการเปลี่ยนสถานะตอน wire หน้า review/my-tasks กลับ)"""
    row = conn.execute(
        "SELECT assigned_to, assigned_by FROM audit_assignments WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    _require_assignment_access(row, user)

    now = _now_str()
    conn.execute(
        "UPDATE audit_assignments SET status = ?, updated_at = ? WHERE assignment_id = ?",
        (body.status, now, assignment_id),
    )
    conn.commit()
    return _fetch_assignment(conn, assignment_id)


@router.post("/assignments/{assignment_id}/report", response_model=AuditReportOut, status_code=201)
def submit_audit_report(
    assignment_id: int,
    body: AuditReportCreate,
    user: dict = Depends(require_roles("risk_analyst", "admin")),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Submit Audit Report (ตาม roles.md) — เฉพาะผู้ถูกมอบหมายงานนี้ (หรือ admin)
    บันทึกลง audit_reports แล้วเลื่อนสถานะ assignment เป็น ready_for_review ให้ในคราวเดียว"""
    row = conn.execute(
        "SELECT assigned_to FROM audit_assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    if row["assigned_to"] != user["user_id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ส่งผลตรวจสอบงานนี้")

    now = _now_str()
    cur = conn.execute(
        """INSERT INTO audit_reports
           (assignment_id, work_process, objective, likelihood, impact, impact_score,
            risk_level, findings, submitted_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            assignment_id,
            body.work_process,
            body.objective,
            body.likelihood,
            body.impact,
            body.impact_score,
            body.risk_level,
            body.findings,
            now,
        ),
    )
    conn.execute(
        "UPDATE audit_assignments SET status = 'ready_for_review', updated_at = ? WHERE assignment_id = ?",
        (now, assignment_id),
    )
    conn.commit()
    report = conn.execute(
        "SELECT * FROM audit_reports WHERE report_id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(report)


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
