# -*- coding: utf-8 -*-
"""Audit assignments, workflow history, feedback, and access-log endpoints."""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_roles, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts
from ..schemas import AssignmentCreate, AssignmentStatusUpdate, AssignmentUpdate

router = APIRouter(prefix="/audit", tags=["audit"])

ASSIGNMENT_STATUSES = {
    "waiting_acceptance",
    "accepted",
    "in_progress",
    "clarification_needed",
    "ready_for_review",
    "under_review",
    "revision_requested",
    "completed",
}
ANALYST_TRANSITIONS = {
    "waiting_acceptance": {"accepted"},
    "accepted": {"in_progress"},
    "in_progress": {"clarification_needed", "ready_for_review"},
    "clarification_needed": {"in_progress"},
    "revision_requested": {"in_progress"},
}
REVIEWER_TRANSITIONS = {
    "ready_for_review": {"under_review"},
    "under_review": {"revision_requested", "completed"},
}
ASSIGNMENT_SELECT = """
    SELECT a.*, p.project_name, p.subdistrict_id,
           assignee.username AS assignee_username,
           assignee.display_name AS assignee_display_name,
           assigner.username AS assigned_by_username,
           assigner.display_name AS assigned_by_display_name
    FROM assignments a
    JOIN projects p ON p.project_id = a.project_id
    JOIN users assignee ON assignee.user_id = a.assigned_to
    JOIN users assigner ON assigner.user_id = a.assigned_by
"""


def _project_in_scope(conn: sqlite3.Connection, project_id: str, user: dict) -> sqlite3.Row:
    project = conn.execute(
        "SELECT project_id, subdistrict_id FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")
    scope = scope_subdistrict_ids(conn, user)
    if scope is not None and project["subdistrict_id"] not in scope:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงโครงการนอกพื้นที่ของคุณ")
    return project


def _assignment_in_scope(conn: sqlite3.Connection, assignment_id: int, user: dict) -> sqlite3.Row:
    assignment = conn.execute(
        """SELECT a.*, p.subdistrict_id
           FROM assignments a JOIN projects p ON p.project_id = a.project_id
           WHERE a.assignment_id = ?""",
        (assignment_id,),
    ).fetchone()
    if assignment is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    if user["role"] == "risk_analyst":
        if assignment["assigned_to"] != user["user_id"]:
            raise HTTPException(status_code=403, detail="เห็นได้เฉพาะงานที่ได้รับมอบหมาย")
        return assignment
    scope = scope_subdistrict_ids(conn, user)
    if scope is not None and assignment["subdistrict_id"] not in scope:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงงานนอกพื้นที่ของคุณ")
    return assignment


def _assignee_for_project(conn: sqlite3.Connection, assignee_id: int, project: sqlite3.Row) -> sqlite3.Row:
    assignee = conn.execute(
        "SELECT user_id, role, subdistrict_id FROM users WHERE user_id = ?",
        (assignee_id,),
    ).fetchone()
    if assignee is None or assignee["role"] != "risk_analyst":
        raise HTTPException(status_code=422, detail="ผู้รับงานต้องเป็น risk_analyst")
    if assignee["subdistrict_id"] != project["subdistrict_id"]:
        raise HTTPException(status_code=422, detail="ผู้รับงานต้องอยู่ในพื้นที่เดียวกับโครงการ")
    return assignee


def _assignment_detail(conn: sqlite3.Connection, assignment_id: int) -> dict:
    row = conn.execute(
        ASSIGNMENT_SELECT + " WHERE a.assignment_id = ?",
        (assignment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    return dict(row)


def _visible_assignments(conn: sqlite3.Connection, user: dict) -> list[dict]:
    if user["role"] == "risk_analyst":
        rows = conn.execute(
            ASSIGNMENT_SELECT + " WHERE a.assigned_to = ? ORDER BY a.created_at DESC",
            (user["user_id"],),
        ).fetchall()
        return rows_to_dicts(rows)
    scope = scope_subdistrict_ids(conn, user)
    sql = ASSIGNMENT_SELECT
    params: list = []
    if scope is not None:
        sql += " WHERE p.subdistrict_id IN ({})".format(",".join("?" * len(scope)) or "NULL")
        params = scope
    rows = conn.execute(sql + " ORDER BY a.created_at DESC", params).fetchall()
    return rows_to_dicts(rows)


@router.get("/assignments/assignees")
def assignment_assignees(
    user: dict = Depends(require_roles("admin", "project_auditor")),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Return risk analysts that the current user may assign work to."""
    scope = scope_subdistrict_ids(conn, user)
    where = ["u.role = 'risk_analyst'"]
    params: list = []
    if scope is not None:
        where.append("u.subdistrict_id IN ({})".format(",".join("?" * len(scope)) or "NULL"))
        params.extend(scope)
    rows = conn.execute(
        f"""SELECT u.user_id, u.username, u.display_name, u.subdistrict_id,
                   COUNT(a.assignment_id) AS active_cases
            FROM users u
            LEFT JOIN assignments a ON a.assigned_to = u.user_id
                AND a.status != 'completed'
            WHERE {' AND '.join(where)}
            GROUP BY u.user_id
            ORDER BY u.display_name, u.username""",
        params,
    ).fetchall()
    return rows_to_dicts(rows)


@router.get("/assignments/my")
def my_assignments(
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Return work visible to the current user; analysts only receive their own work."""
    return _visible_assignments(conn, user)


@router.get("/assignments")
def list_assignments(
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: sqlite3.Connection = Depends(get_db),
):
    return _visible_assignments(conn, user)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: AssignmentCreate,
    user: dict = Depends(require_roles("admin", "project_auditor")),
    conn: sqlite3.Connection = Depends(get_db),
):
    project = _project_in_scope(conn, payload.project_id, user)
    _assignee_for_project(conn, payload.assignee_id, project)
    duplicate = conn.execute(
        "SELECT assignment_id FROM assignments WHERE project_id = ? AND status != 'completed'",
        (payload.project_id,),
    ).fetchone()
    if duplicate:
        raise HTTPException(status_code=409, detail="โครงการนี้มีงานที่ยังไม่เสร็จสิ้นอยู่แล้ว")
    cursor = conn.execute(
        """INSERT INTO assignments
           (project_id, assigned_to, assigned_by, priority, note, due_date, status)
           VALUES (?,?,?,?,?,?, 'waiting_acceptance')""",
        (payload.project_id, payload.assignee_id, user["user_id"], payload.priority,
         payload.note, payload.due_date),
    )
    assignment_id = cursor.lastrowid
    conn.execute(
        """INSERT INTO assignment_status_history
           (assignment_id, old_status, new_status, changed_by, note)
           VALUES (?, NULL, 'waiting_acceptance', ?, ?)""",
        (assignment_id, user["user_id"], "สร้างและมอบหมายงาน"),
    )
    conn.commit()
    return _assignment_detail(conn, assignment_id)


@router.get("/assignments/{assignment_id}")
def get_assignment(
    assignment_id: int,
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: sqlite3.Connection = Depends(get_db),
):
    _assignment_in_scope(conn, assignment_id, user)
    history = conn.execute(
        """SELECT h.*, u.username AS changed_by_username,
                  u.display_name AS changed_by_display_name
           FROM assignment_status_history h
           JOIN users u ON u.user_id = h.changed_by
           WHERE h.assignment_id = ? ORDER BY h.history_id DESC""",
        (assignment_id,),
    ).fetchall()
    return {"assignment": _assignment_detail(conn, assignment_id), "status_history": rows_to_dicts(history)}


@router.patch("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    user: dict = Depends(require_roles("admin", "project_auditor")),
    conn: sqlite3.Connection = Depends(get_db),
):
    assignment = _assignment_in_scope(conn, assignment_id, user)
    if assignment["status"] != "waiting_acceptance":
        raise HTTPException(status_code=409, detail="แก้ไขรายละเอียดหรือย้ายผู้รับผิดชอบได้ก่อนผู้รับงานตอบรับเท่านั้น")
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return _assignment_detail(conn, assignment_id)
    if "assignee_id" in values:
        project = _project_in_scope(conn, assignment["project_id"], user)
        _assignee_for_project(conn, values["assignee_id"], project)
        values["assigned_to"] = values.pop("assignee_id")
    columns = list(values)
    set_clause = ", ".join(f"{column} = ?" for column in columns)
    conn.execute(
        f"UPDATE assignments SET {set_clause}, updated_at = datetime('now') WHERE assignment_id = ?",
        [values[column] for column in columns] + [assignment_id],
    )
    conn.commit()
    return _assignment_detail(conn, assignment_id)


@router.patch("/assignments/{assignment_id}/status")
def update_assignment_status(
    assignment_id: int,
    payload: AssignmentStatusUpdate,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: sqlite3.Connection = Depends(get_db),
):
    assignment = _assignment_in_scope(conn, assignment_id, user)
    current_status = assignment["status"]
    next_status = payload.status
    if current_status == next_status:
        return _assignment_detail(conn, assignment_id)
    if user["role"] == "risk_analyst":
        allowed = ANALYST_TRANSITIONS.get(current_status, set())
    elif user["role"] == "project_auditor":
        allowed = REVIEWER_TRANSITIONS.get(current_status, set())
    else:
        allowed = ASSIGNMENT_STATUSES - {current_status}
    if next_status not in allowed:
        raise HTTPException(status_code=409, detail=f"ไม่สามารถเปลี่ยนสถานะจาก {current_status} เป็น {next_status} ได้")
    conn.execute(
        "UPDATE assignments SET status = ?, updated_at = datetime('now') WHERE assignment_id = ?",
        (next_status, assignment_id),
    )
    conn.execute(
        """INSERT INTO assignment_status_history
           (assignment_id, old_status, new_status, changed_by, note)
           VALUES (?,?,?,?,?)""",
        (assignment_id, current_status, next_status, user["user_id"], payload.note),
    )
    conn.commit()
    return _assignment_detail(conn, assignment_id)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    user: dict = Depends(require_roles("admin")),
    conn: sqlite3.Connection = Depends(get_db),
):
    _assignment_in_scope(conn, assignment_id, user)
    conn.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
    conn.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
    conn.commit()
    return None


@router.get("/feedback/{project_id}")
def project_feedback(
    project_id: str,
    _: dict = Depends(require_roles("admin", "regional_supervisor", "local_executive", "project_auditor", "risk_analyst")),
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
    _: dict = Depends(require_roles("admin")),
    conn: sqlite3.Connection = Depends(get_db),
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
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
    total = conn.execute(f"SELECT COUNT(*) FROM access_log{clause}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT log_id, username, role, action, method, path, resource_type,
                   resource_id, status_code, ip, user_agent, created_at
            FROM access_log{clause}
            ORDER BY log_id DESC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    return {"items": rows_to_dicts(rows), "total": total, "limit": limit, "offset": offset}
