# -*- coding: utf-8 -*-
"""
database.py — ตัวช่วยเชื่อมต่อ SQLite

ใช้ sqlite3 จาก stdlib. เปิด connection ต่อ 1 request (dependency get_db)
คืน row เป็น dict-like (sqlite3.Row) เพื่อ serialize เป็น JSON ได้ง่าย
"""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH


def _ensure_assignment_tables(conn: sqlite3.Connection) -> None:
    """Create the assignment workflow tables for databases seeded before this feature."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            assigned_to INTEGER NOT NULL REFERENCES users(user_id),
            assigned_by INTEGER NOT NULL REFERENCES users(user_id),
            priority TEXT NOT NULL DEFAULT 'normal'
                CHECK (priority IN ('low', 'normal', 'high')),
            note TEXT NOT NULL DEFAULT '',
            due_date TEXT,
            budget_hours REAL,
            audit_steps TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'waiting_acceptance'
                CHECK (status IN (
                    'waiting_acceptance', 'accepted', 'in_progress',
                    'clarification_needed', 'ready_for_review', 'under_review',
                    'revision_requested', 'completed'
                )),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_assignments_assignee_status
            ON assignments(assigned_to, status);
        CREATE INDEX IF NOT EXISTS idx_assignments_project
            ON assignments(project_id);

        CREATE TABLE IF NOT EXISTS assignment_status_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(assignment_id),
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by INTEGER NOT NULL REFERENCES users(user_id),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_assignment_history_assignment
            ON assignment_status_history(assignment_id, history_id);
        """
    )
    conn.commit()


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"ไม่พบฐานข้อมูลที่ {DB_PATH} — รัน `python seed_database.py` ก่อน"
        )
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _ensure_assignment_tables(conn)
    return conn


def get_db():
    """FastAPI dependency — yield connection แล้วปิดให้อัตโนมัติ"""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_session():
    """ใช้นอก request context (เช่น script/test)"""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
