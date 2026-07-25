# -*- coding: utf-8 -*-
"""
database.py — ตัวช่วยเชื่อมต่อ PostgreSQL (psycopg)

Row factory เลียนแบบ sqlite3.Row เดิม (รองรับทั้ง row[0], row["col"], และ
iterate เป็นค่าตามลำดับคอลัมน์) และ Connection/Cursor แปลง `?` placeholder
(สไตล์ sqlite3 ที่ query ทั้งโค้ดเบสเขียนไว้) เป็น `%s` ให้อัตโนมัติ —
เพื่อย้ายจาก SQLite ไป PostgreSQL โดยไม่ต้องแก้ query ทีละจุดทั่วทั้ง repo
"""
from contextlib import contextmanager

import psycopg

from .config import DATABASE_URL


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
    return Connection.connect(
        DATABASE_URL,
        row_factory=_sqlite_row_factory,
        cursor_factory=Cursor,
        autocommit=False,
    )


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
