# -*- coding: utf-8 -*-
"""
database.py — ตัวช่วยเชื่อมต่อ SQLite

ใช้ sqlite3 จาก stdlib. เปิด connection ต่อ 1 request (dependency get_db)
คืน row เป็น dict-like (sqlite3.Row) เพื่อ serialize เป็น JSON ได้ง่าย
"""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"ไม่พบฐานข้อมูลที่ {DB_PATH} — รัน `python seed_database.py` ก่อน"
        )
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
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
