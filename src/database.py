# -*- coding: utf-8 -*-
"""
database.py — ตัวช่วยเชื่อมต่อ PostgreSQL (psycopg)

Row factory เลียนแบบ sqlite3.Row เดิม (รองรับทั้ง row[0], row["col"], และ
iterate เป็นค่าตามลำดับคอลัมน์) และ Connection/Cursor แปลง `?` placeholder
(สไตล์ sqlite3 ที่ query ทั้งโค้ดเบสเขียนไว้) เป็น `%s` ให้อัตโนมัติ —
เพื่อย้ายจาก SQLite ไป PostgreSQL โดยไม่ต้องแก้ query ทีละจุดทั่วทั้ง repo
"""
import time
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL

# Neon (serverless Postgres) suspend compute เมื่อไม่มีคนใช้สักพัก — request แรกหลัง idle
# ต้องรอ cold start ถ้าไม่มี retry จะ fail ตรงๆ ครั้งเดียวแล้วครั้งถัดไปถึงจะผ่าน (ดูเหมือนระบบ
# "เปิดติดๆ ดับๆ") ค่าเหล่านี้ retry เฉพาะตอน connect เท่านั้น ไม่ retry query อื่น
_CONNECT_TIMEOUT_SECONDS = 10
_CONNECT_MAX_ATTEMPTS = 3
_CONNECT_RETRY_DELAY_SECONDS = 0.75


class SqliteLikeRow:
    """เลียนแบบ sqlite3.Row: row[0], row["col"], iterate เป็นค่า, dict(row) ใช้ได้หมด"""

    __slots__ = ("_values", "_index")

    def __init__(self, values, index):
        self._values = values
        self._index = index

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._index.keys())


def _sqlite_row_factory(cursor):
    description = cursor.description
    if description is None:  # statement ที่ไม่มี result set (INSERT/UPDATE/DDL โดยไม่มี RETURNING)
        return lambda values: values
    index = {col.name: i for i, col in enumerate(description)}
    return lambda values: SqliteLikeRow(values, index)


class Cursor(psycopg.Cursor):
    def execute(self, query, params=None, **kwargs):
        return super().execute(query.replace("?", "%s"), params, **kwargs)

    def executemany(self, query, params_seq, **kwargs):
        return super().executemany(query.replace("?", "%s"), params_seq, **kwargs)


class Connection(psycopg.Connection):
    def execute(self, query, params=None, **kwargs):
        return super().execute(query.replace("?", "%s"), params, **kwargs)


def _connect() -> Connection:
    last_error: psycopg.OperationalError | None = None
    for attempt in range(1, _CONNECT_MAX_ATTEMPTS + 1):
        try:
            return Connection.connect(
                DATABASE_URL,
                row_factory=_sqlite_row_factory,
                cursor_factory=Cursor,
                autocommit=False,
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            )
        except psycopg.OperationalError as exc:
            last_error = exc
            if attempt < _CONNECT_MAX_ATTEMPTS:
                time.sleep(_CONNECT_RETRY_DELAY_SECONDS * attempt)
    raise last_error


# Pool ของ connection ที่ใช้ซ้ำข้าม request ได้ (module-level — อยู่รอดข้าม warm invocation บน
# Vercel serverless และตลอดอายุ process ตอน uvicorn --reload) แทนที่จะเปิด TCP+TLS ใหม่ไปหา
# Neon (คนละเครือข่าย ไม่ใช่ localhost) ทุกครั้งที่มี request เข้ามาที่ get_db()
_pool = ConnectionPool(
    DATABASE_URL,
    connection_class=Connection,
    kwargs={
        "row_factory": _sqlite_row_factory,
        "cursor_factory": Cursor,
        "autocommit": False,
        "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
    },
    min_size=1,
    max_size=5,
    open=True,
)


def get_db():
    """FastAPI dependency — ยืม connection จาก pool แล้วคืนกลับให้อัตโนมัติ"""
    with _pool.connection() as conn:
        yield conn


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
