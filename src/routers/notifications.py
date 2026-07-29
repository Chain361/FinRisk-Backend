# -*- coding: utf-8 -*-
"""แจ้งเตือนของผู้ใช้ที่ล็อกอินอยู่ — เห็นเฉพาะของตัวเอง"""
from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_roles
from ..database import Connection, get_db, rows_to_dicts

router = APIRouter(prefix="/notifications", tags=["notifications"])
NOTIFICATION_ROLES = ("project_auditor", "risk_analyst")


@router.get("")
def list_notifications(
    unread: bool = Query(False),
    user: dict = Depends(require_roles(*NOTIFICATION_ROLES)),
    conn: Connection = Depends(get_db),
):
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    params: list = [user["user_id"]]
    if unread:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    unread_count = conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user["user_id"],),
    ).fetchone()["n"]
    return {"notifications": rows_to_dicts(rows), "unread_count": unread_count}


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    user: dict = Depends(require_roles(*NOTIFICATION_ROLES)),
    conn: Connection = Depends(get_db),
):
    row = conn.execute(
        "SELECT user_id FROM notifications WHERE notification_id = ?",
        (notification_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบการแจ้งเตือน")
    if row["user_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงการแจ้งเตือนนี้")
    conn.execute(
        "UPDATE notifications SET read_at = now_text() WHERE notification_id = ?",
        (notification_id,),
    )
    conn.commit()
    return {"notification_id": notification_id, "read": True}


@router.post("/read-all")
def mark_all_notifications_read(
    user: dict = Depends(require_roles(*NOTIFICATION_ROLES)),
    conn: Connection = Depends(get_db),
):
    conn.execute(
        "UPDATE notifications SET read_at = now_text() WHERE user_id = ? AND read_at IS NULL",
        (user["user_id"],),
    )
    conn.commit()
    return {"marked_read": True}
