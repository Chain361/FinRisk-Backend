# -*- coding: utf-8 -*-
"""Notification helper — insert-only, ไม่ commit (caller commit พร้อม transaction เดิม)"""
from .database import Connection


def create_notification(
    conn: Connection,
    user_id: int,
    type: str,
    message: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO notifications (user_id, type, message, ref_type, ref_id)
           VALUES (?,?,?,?,?)""",
        (user_id, type, message, ref_type, str(ref_id) if ref_id is not None else None),
    )
