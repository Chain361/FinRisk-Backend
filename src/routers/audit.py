# -*- coding: utf-8 -*-
"""Audit assignments, workflow history, feedback, and access-log endpoints."""
import os
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from ..auth import require_roles, scope_subdistrict_ids
from ..database import Connection, SqliteLikeRow, get_db, rows_to_dicts
from ..log_retention import list_archived_access_logs
from ..notify import create_notification
from ..schemas import (
    AssignmentCreate,
    AssignmentStatusUpdate,
    AssignmentUpdate,
    AttachmentOut,
    AuditorFeedbackIn,
    AuditorFeedbackOut,
    ClarificationCreate,
    ClarificationOut,
)

router = APIRouter(prefix="/audit", tags=["audit"])

# roles ที่เห็น/เขียน audit feedback ได้ (ตาม roles.md — ระดับเดียวกับ /audit/feedback เดิม)
FEEDBACK_ROLES = ("admin", "regional_supervisor", "local_executive", "project_auditor", "risk_analyst")
# roles ที่ปิดเรื่อง (resolve) ได้ — ผู้ตรวจสอบ/แอดมินเท่านั้น ตรงกับ canResolveFeedback ฝั่ง frontend
RESOLVE_ROLES = ("admin", "project_auditor")


def _now_str() -> str:
    """รูปแบบเดียวกับ SQL `now_text()` (UTC, 'YYYY-MM-DD HH:MM:SS')"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _serialize_feedback(row: SqliteLikeRow) -> dict:
    """เติม risk_score (คำนวณจาก likelihood_score × impact_score ไม่เก็บเป็นคอลัมน์แยก)"""
    data = dict(row)
    likelihood = data.get("likelihood_score")
    impact = data.get("impact_score")
    data["risk_score"] = likelihood * impact if likelihood is not None and impact is not None else None
    return data


def _fetch_feedback(conn: Connection, feedback_id: int) -> dict:
    row = conn.execute(
        """SELECT f.*, u.username AS auditor_username, u.display_name AS auditor_name
           FROM auditor_feedback f JOIN users u ON u.user_id = f.user_id
           WHERE f.feedback_id = ?""",
        (feedback_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็น")
    return _serialize_feedback(row)


ASSIGNMENT_STATUSES = {
    "waiting_acceptance",
    "accepted",
    "in_progress",
    "clarification_needed",
    "ready_for_review",
    "under_review",
    "pending_approval",
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
# auditor ตรวจงานแล้วส่งขออนุมัติ (ไม่ปิดงานเองอีกต่อไป — ต้องผ่าน SUPERVISOR_TRANSITIONS)
REVIEWER_TRANSITIONS = {
    "ready_for_review": {"under_review"},
    "under_review": {"revision_requested", "pending_approval"},
}
# regional_supervisor อนุมัติปิดงาน หรือตีกลับให้แก้ (ขั้นอนุมัติสุดท้าย — ดู #14)
SUPERVISOR_TRANSITIONS = {
    "pending_approval": {"completed", "revision_requested"},
}
ASSIGNMENT_SELECT = """
    SELECT a.*, p.project_name, p.subdistrict_id,
           'user' AS assignee_entity_type,
           'user:' || assignee.username AS assignee_user_label,
           assignee.username AS assignee_username,
           assignee.display_name AS assignee_display_name,
           assigner.username AS assigned_by_username,
           assigner.display_name AS assigned_by_display_name
    FROM assignments a
    JOIN projects p ON p.project_id = a.project_id
    JOIN users assignee ON assignee.user_id = a.assigned_to
    JOIN users assigner ON assigner.user_id = a.assigned_by
"""


def _project_in_scope(conn: Connection, project_id: str, user: dict) -> SqliteLikeRow:
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


def _assignment_in_scope(conn: Connection, assignment_id: int, user: dict) -> SqliteLikeRow:
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


ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB — เก็บเป็น BYTEA ตรงๆ ใน Postgres ไม่มี object storage
ATTACHMENT_SELECT = """
    SELECT a.attachment_id, a.assignment_id, a.file_name, a.content_type, a.file_size,
           a.uploaded_by, u.display_name AS uploaded_by_display_name, a.created_at
    FROM assignment_attachments a
    JOIN users u ON u.user_id = a.uploaded_by
"""
CLARIFICATION_SELECT = """
    SELECT c.clarification_id, c.assignment_id, c.message_text,
           c.created_by, u.display_name AS created_by_display_name, c.created_at
    FROM assignment_clarifications c
    JOIN users u ON u.user_id = c.created_by
"""


def _notify_other_party(conn: Connection, assignment: SqliteLikeRow, actor: dict, notif_type: str, message: str) -> None:
    """แจ้งเตือนอีกฝ่ายของ assignment (risk_analyst ↔ project_auditor ที่มอบหมายงาน) ไม่แจ้งตัวเอง"""
    other_user_id = (
        assignment["assigned_by"] if actor["user_id"] == assignment["assigned_to"] else assignment["assigned_to"]
    )
    create_notification(conn, other_user_id, notif_type, message, "assignment", assignment["assignment_id"])


def _fetch_attachment_meta(conn: Connection, attachment_id: int) -> dict:
    row = conn.execute(ATTACHMENT_SELECT + " WHERE a.attachment_id = ?", (attachment_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์แนบ")
    return dict(row)


def _attachment_in_scope(conn: Connection, assignment_id: int, attachment_id: int, user: dict) -> SqliteLikeRow:
    _assignment_in_scope(conn, assignment_id, user)
    row = conn.execute(
        "SELECT * FROM assignment_attachments WHERE attachment_id = ? AND assignment_id = ?",
        (attachment_id, assignment_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์แนบ")
    return row


def _assignee_for_project(conn: Connection, assignee_id: int, project: SqliteLikeRow) -> SqliteLikeRow:
    assignee = conn.execute(
        "SELECT user_id, role, subdistrict_id FROM users WHERE user_id = ?",
        (assignee_id,),
    ).fetchone()
    if assignee is None or assignee["role"] != "risk_analyst":
        raise HTTPException(status_code=422, detail="ผู้รับงานต้องเป็น risk_analyst")
    if assignee["subdistrict_id"] != project["subdistrict_id"]:
        raise HTTPException(status_code=422, detail="ผู้รับงานต้องอยู่ในพื้นที่เดียวกับโครงการ")
    return assignee


def _assignment_detail(conn: Connection, assignment_id: int) -> dict:
    row = conn.execute(
        ASSIGNMENT_SELECT + " WHERE a.assignment_id = ?",
        (assignment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่มอบหมาย")
    return dict(row)


def _visible_assignments(conn: Connection, user: dict) -> list[dict]:
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
    conn: Connection = Depends(get_db),
):
    """Return risk analysts that the current user may assign work to."""
    scope = scope_subdistrict_ids(conn, user)
    where = ["u.role = 'risk_analyst'"]
    params: list = []
    if scope is not None:
        where.append("u.subdistrict_id IN ({})".format(",".join("?" * len(scope)) or "NULL"))
        params.extend(scope)
    rows = conn.execute(
        f"""SELECT u.user_id, u.username, u.display_name, u.role, u.subdistrict_id,
                   'user' AS entity_type,
                   'user:' || u.username AS user_label,
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
    conn: Connection = Depends(get_db),
):
    """Return work visible to the current user; analysts only receive their own work."""
    return _visible_assignments(conn, user)


@router.get("/assignments")
def list_assignments(
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    return _visible_assignments(conn, user)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: AssignmentCreate,
    user: dict = Depends(require_roles("admin", "project_auditor")),
    conn: Connection = Depends(get_db),
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
           VALUES (?,?,?,?,?,?, 'waiting_acceptance')
           RETURNING assignment_id""",
        (payload.project_id, payload.assignee_id, user["user_id"], payload.priority,
         payload.note, payload.due_date),
    )
    assignment_id = cursor.fetchone()["assignment_id"]
    conn.execute(
        """INSERT INTO assignment_status_history
           (assignment_id, old_status, new_status, changed_by, note)
           VALUES (?, NULL, 'waiting_acceptance', ?, ?)""",
        (assignment_id, user["user_id"], "สร้างและมอบหมายงาน"),
    )
    create_notification(
        conn,
        payload.assignee_id,
        "assignment",
        f"คุณได้รับมอบหมายงานตรวจสอบโครงการ {payload.project_id}",
        "assignment",
        assignment_id,
    )
    conn.commit()
    return _assignment_detail(conn, assignment_id)


@router.get("/assignments/{assignment_id}")
def get_assignment(
    assignment_id: int,
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
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
    conn: Connection = Depends(get_db),
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
        f"UPDATE assignments SET {set_clause}, updated_at = now_text() WHERE assignment_id = ?",
        [values[column] for column in columns] + [assignment_id],
    )
    conn.commit()
    return _assignment_detail(conn, assignment_id)


@router.patch("/assignments/{assignment_id}/status")
def update_assignment_status(
    assignment_id: int,
    payload: AssignmentStatusUpdate,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst", "regional_supervisor")),
    conn: Connection = Depends(get_db),
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
    elif user["role"] == "regional_supervisor":
        allowed = SUPERVISOR_TRANSITIONS.get(current_status, set())
    else:
        allowed = ASSIGNMENT_STATUSES - {current_status}
    if next_status not in allowed:
        raise HTTPException(status_code=409, detail=f"ไม่สามารถเปลี่ยนสถานะจาก {current_status} เป็น {next_status} ได้")
    if next_status == "revision_requested" and not (payload.note or "").strip():
        raise HTTPException(status_code=400, detail="ต้องระบุเหตุผลเมื่อตีกลับงาน")
    conn.execute(
        "UPDATE assignments SET status = ?, updated_at = now_text() WHERE assignment_id = ?",
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
    conn: Connection = Depends(get_db),
):
    _assignment_in_scope(conn, assignment_id, user)
    conn.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
    conn.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
    conn.commit()
    return None


@router.post("/assignments/{assignment_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    assignment_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    """แนบไฟล์หลักฐาน (evidence) — เก็บเป็น BYTEA ตรงๆ ใน Postgres (ไม่มี object storage ในระบบ)"""
    assignment = _assignment_in_scope(conn, assignment_id, user)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"ไม่รองรับไฟล์นามสกุล {ext or '(ไม่ทราบ)'}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="ไฟล์ว่างเปล่า")
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="ไฟล์ต้องมีขนาดไม่เกิน 10MB")
    cursor = conn.execute(
        """INSERT INTO assignment_attachments
           (assignment_id, file_name, content_type, file_size, file_content, uploaded_by)
           VALUES (?,?,?,?,?,?)
           RETURNING attachment_id""",
        (
            assignment_id,
            file.filename,
            file.content_type or "application/octet-stream",
            len(content),
            content,
            user["user_id"],
        ),
    )
    attachment_id = cursor.fetchone()["attachment_id"]
    _notify_other_party(
        conn, assignment, user, "attachment",
        f"มีไฟล์หลักฐานใหม่แนบในงานตรวจสอบโครงการ {assignment['project_id']}: {file.filename}",
    )
    conn.commit()
    return _fetch_attachment_meta(conn, attachment_id)


@router.get("/assignments/{assignment_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    assignment_id: int,
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    _assignment_in_scope(conn, assignment_id, user)
    rows = conn.execute(
        ATTACHMENT_SELECT + " WHERE a.assignment_id = ? ORDER BY a.created_at DESC",
        (assignment_id,),
    ).fetchall()
    return rows_to_dicts(rows)


@router.get("/assignments/{assignment_id}/attachments/{attachment_id}/download")
def download_attachment(
    assignment_id: int,
    attachment_id: int,
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    row = _attachment_in_scope(conn, assignment_id, attachment_id, user)
    safe_name = quote(row["file_name"])
    return Response(
        content=bytes(row["file_content"]),
        media_type=row["content_type"],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.delete("/assignments/{assignment_id}/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    assignment_id: int,
    attachment_id: int,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    row = _attachment_in_scope(conn, assignment_id, attachment_id, user)
    if row["uploaded_by"] != user["user_id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="ลบได้เฉพาะไฟล์ที่ตัวเองอัปโหลด")
    conn.execute("DELETE FROM assignment_attachments WHERE attachment_id = ?", (attachment_id,))
    conn.commit()
    return Response(status_code=204)


@router.get("/assignments/{assignment_id}/clarifications", response_model=list[ClarificationOut])
def list_clarifications(
    assignment_id: int,
    user: dict = Depends(require_roles("admin", "regional_supervisor", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    _assignment_in_scope(conn, assignment_id, user)
    rows = conn.execute(
        CLARIFICATION_SELECT + " WHERE c.assignment_id = ? ORDER BY c.clarification_id",
        (assignment_id,),
    ).fetchall()
    return rows_to_dicts(rows)


@router.post("/assignments/{assignment_id}/clarifications", response_model=ClarificationOut, status_code=201)
def create_clarification(
    assignment_id: int,
    payload: ClarificationCreate,
    user: dict = Depends(require_roles("admin", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
):
    assignment = _assignment_in_scope(conn, assignment_id, user)
    cursor = conn.execute(
        """INSERT INTO assignment_clarifications (assignment_id, message_text, created_by)
           VALUES (?,?,?)
           RETURNING clarification_id""",
        (assignment_id, payload.message_text, user["user_id"]),
    )
    clarification_id = cursor.fetchone()["clarification_id"]
    _notify_other_party(
        conn, assignment, user, "clarification",
        f"มีข้อความใหม่ในกระทู้ขอความชัดเจนของงานตรวจสอบโครงการ {assignment['project_id']}",
    )
    conn.commit()
    row = conn.execute(
        CLARIFICATION_SELECT + " WHERE c.clarification_id = ?", (clarification_id,)
    ).fetchone()
    return dict(row)


@router.get("/feedback", response_model=list[AuditorFeedbackOut])
def list_feedback(
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: Connection = Depends(get_db),
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


@router.get("/feedback/{project_id}")
def project_feedback(
    project_id: str,
    _: dict = Depends(require_roles("admin", "regional_supervisor", "local_executive", "project_auditor", "risk_analyst")),
    conn: Connection = Depends(get_db),
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
    conn: Connection = Depends(get_db),
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
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           RETURNING feedback_id""",
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
    feedback_id = cur.fetchone()["feedback_id"]
    conn.commit()
    return _fetch_feedback(conn, feedback_id)


@router.patch("/feedback/{feedback_id}", response_model=AuditorFeedbackOut)
def update_feedback(
    feedback_id: int,
    body: AuditorFeedbackIn,
    user: dict = Depends(require_roles(*FEEDBACK_ROLES)),
    conn: Connection = Depends(get_db),
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
    conn: Connection = Depends(get_db),
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
    conn: Connection = Depends(get_db),
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
    conn: Connection = Depends(get_db),
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
        where.append("created_at < ?")
        params.append((date.fromisoformat(date_to) + timedelta(days=1)).isoformat())
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


@router.get("/access-log/archive")
def access_log_archive(
    _: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    inclusive_date_to = None
    if date_to:
        inclusive_date_to = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
    try:
        return list_archived_access_logs(
            conn,
            username=username,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=inclusive_date_to,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
