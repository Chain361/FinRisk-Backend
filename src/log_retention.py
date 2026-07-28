# -*- coding: utf-8 -*-
"""Retention policy for access/security audit logs."""

from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timedelta, timezone

from .database import Connection, rows_to_dicts

DEFAULT_HOT_DAYS = 90
DEFAULT_ARCHIVE_DAYS = 365
DEFAULT_ERROR_DEBUG_DAYS = 30


RETENTION_DDL = """
CREATE TABLE IF NOT EXISTS access_log_archive (
    archive_id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    original_log_id  INTEGER NOT NULL UNIQUE,
    username         TEXT,
    role             TEXT,
    action           TEXT NOT NULL,
    method           TEXT NOT NULL,
    path             TEXT NOT NULL,
    resource_type    TEXT,
    resource_id      TEXT,
    status_code      INTEGER,
    created_at       TEXT NOT NULL,
    payload_gzip_base64 TEXT NOT NULL,
    compressed_at    TEXT NOT NULL DEFAULT (now_text()),
    delete_after     TEXT NOT NULL,
    archived_by      TEXT
);
CREATE INDEX IF NOT EXISTS idx_access_log_archive_time
    ON access_log_archive(created_at);
CREATE INDEX IF NOT EXISTS idx_access_log_archive_user_time
    ON access_log_archive(username, created_at);

CREATE TABLE IF NOT EXISTS access_log_holds (
    hold_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    log_id         INTEGER NOT NULL UNIQUE,
    reason         TEXT NOT NULL,
    case_reference TEXT,
    created_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (now_text())
);

CREATE TABLE IF NOT EXISTS log_retention_runs (
    run_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at        TEXT NOT NULL DEFAULT (now_text()),
    hot_days      INTEGER NOT NULL,
    archive_days  INTEGER NOT NULL,
    error_debug_days INTEGER NOT NULL DEFAULT 30,
    archived_count INTEGER NOT NULL,
    deleted_count  INTEGER NOT NULL,
    error_debug_deleted_count INTEGER NOT NULL DEFAULT 0,
    archive_cutoff TEXT NOT NULL,
    delete_cutoff  TEXT NOT NULL,
    triggered_by   TEXT,
    note           TEXT
);

CREATE TABLE IF NOT EXISTS error_debug_log (
    log_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    level         TEXT NOT NULL CHECK (level IN ('debug','info','warning','error','critical')),
    logger_name   TEXT,
    message       TEXT NOT NULL,
    error_type    TEXT,
    method        TEXT,
    path          TEXT,
    status_code   INTEGER,
    username      TEXT,
    request_id    TEXT,
    stack_hash    TEXT,
    created_at    TEXT NOT NULL DEFAULT (now_text())
);
CREATE INDEX IF NOT EXISTS idx_error_debug_log_time
    ON error_debug_log(created_at);
CREATE INDEX IF NOT EXISTS idx_error_debug_log_level_time
    ON error_debug_log(level, created_at);

ALTER TABLE log_retention_runs
    ADD COLUMN IF NOT EXISTS error_debug_days INTEGER NOT NULL DEFAULT 30;
ALTER TABLE log_retention_runs
    ADD COLUMN IF NOT EXISTS error_debug_deleted_count INTEGER NOT NULL DEFAULT 0;
"""


def _utc_text(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _compress_payload(row: dict) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.b64encode(gzip.compress(raw)).decode("ascii")


def decompress_payload(payload_gzip_base64: str) -> dict:
    raw = base64.b64decode(payload_gzip_base64.encode("ascii"))
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def ensure_log_retention_schema(conn: Connection) -> None:
    try:
        for statement in [s.strip() for s in RETENTION_DDL.split(";") if s.strip()]:
            conn.execute(statement)
    except Exception as exc:  # noqa: BLE001 - surface a clear migration hint to API callers
        raise RuntimeError(
            "log retention schema is not available; run seed_database.py or "
            "migrations/20260728_log_retention.sql with a database role that can create tables"
        ) from exc


def get_retention_policy(conn: Connection) -> tuple[int, int, int]:
    rows = conn.execute(
        """SELECT key, value FROM app_config
           WHERE key IN (
               'log_retention_hot_days',
               'log_retention_archive_days',
               'error_debug_log_hot_days'
           )"""
    ).fetchall()
    config = {row["key"]: row["value"] for row in rows}
    hot_days = int(config.get("log_retention_hot_days", DEFAULT_HOT_DAYS))
    archive_days = int(config.get("log_retention_archive_days", DEFAULT_ARCHIVE_DAYS))
    error_debug_days = int(config.get("error_debug_log_hot_days", DEFAULT_ERROR_DEBUG_DAYS))
    return hot_days, archive_days, error_debug_days


def run_access_log_retention(
    conn: Connection,
    *,
    triggered_by: str | None = None,
    hot_days: int | None = None,
    archive_days: int | None = None,
    error_debug_days: int | None = None,
    now: datetime | None = None,
) -> dict:
    ensure_log_retention_schema(conn)
    default_hot_days, default_archive_days, default_error_debug_days = get_retention_policy(conn)
    hot_days = hot_days if hot_days is not None else default_hot_days
    archive_days = archive_days if archive_days is not None else default_archive_days
    error_debug_days = error_debug_days if error_debug_days is not None else default_error_debug_days
    if hot_days > archive_days:
        raise ValueError("hot_days must be less than or equal to archive_days")
    if error_debug_days > hot_days:
        raise ValueError("error_debug_days must be less than or equal to hot_days")
    now = now or datetime.now(timezone.utc)

    archive_cutoff = _utc_text(now - timedelta(days=hot_days))
    delete_cutoff = _utc_text(now - timedelta(days=archive_days))
    error_debug_cutoff = _utc_text(now - timedelta(days=error_debug_days))
    delete_after = _utc_text(now + timedelta(days=max(archive_days - hot_days, 0)))

    rows = conn.execute(
        """SELECT log_id, username, role, action, method, path, resource_type,
                  resource_id, status_code, ip, user_agent, created_at
           FROM access_log
           WHERE created_at < ?
           ORDER BY log_id""",
        (archive_cutoff,),
    ).fetchall()

    archived_ids: list[int] = []
    for row in rows_to_dicts(rows):
        payload = _compress_payload(row)
        conn.execute(
            """INSERT INTO access_log_archive
               (original_log_id, username, role, action, method, path, resource_type,
                resource_id, status_code, created_at, payload_gzip_base64,
                delete_after, archived_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (original_log_id) DO NOTHING""",
            (
                row["log_id"],
                row["username"],
                row["role"],
                row["action"],
                row["method"],
                row["path"],
                row["resource_type"],
                row["resource_id"],
                row["status_code"],
                row["created_at"],
                payload,
                delete_after,
                triggered_by,
            ),
        )
        archived_ids.append(row["log_id"])

    if archived_ids:
        placeholders = ",".join("?" * len(archived_ids))
        conn.execute(
            f"DELETE FROM access_log WHERE log_id IN ({placeholders})",
            archived_ids,
        )

    deleted_rows = conn.execute(
        """DELETE FROM access_log_archive
           WHERE created_at < ?
             AND NOT EXISTS (
                 SELECT 1 FROM access_log_holds h
                 WHERE h.log_id = access_log_archive.original_log_id
             )
           RETURNING archive_id""",
        (delete_cutoff,),
    ).fetchall()

    error_debug_deleted_rows = conn.execute(
        "DELETE FROM error_debug_log WHERE created_at < ? RETURNING log_id",
        (error_debug_cutoff,),
    ).fetchall()

    run = conn.execute(
        """INSERT INTO log_retention_runs
           (hot_days, archive_days, error_debug_days,
            archived_count, deleted_count, error_debug_deleted_count,
            archive_cutoff, delete_cutoff, triggered_by, note)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           RETURNING run_id, run_at""",
        (
            hot_days,
            archive_days,
            error_debug_days,
            len(archived_ids),
            len(deleted_rows),
            len(error_debug_deleted_rows),
            archive_cutoff,
            delete_cutoff,
            triggered_by,
            "log retention: access archive/delete and error/debug delete policy",
        ),
    ).fetchone()

    return {
        "run_id": run["run_id"],
        "run_at": run["run_at"],
        "hot_days": hot_days,
        "archive_days": archive_days,
        "error_debug_days": error_debug_days,
        "archive_cutoff": archive_cutoff,
        "delete_cutoff": delete_cutoff,
        "error_debug_cutoff": error_debug_cutoff,
        "archived_count": len(archived_ids),
        "deleted_count": len(deleted_rows),
        "error_debug_deleted_count": len(error_debug_deleted_rows),
    }


def upsert_access_log_hold(
    conn: Connection,
    *,
    log_id: int,
    reason: str,
    case_reference: str | None,
    created_by: str | None,
) -> dict:
    ensure_log_retention_schema(conn)
    row = conn.execute(
        """INSERT INTO access_log_holds (log_id, reason, case_reference, created_by)
           VALUES (?,?,?,?)
           ON CONFLICT (log_id) DO UPDATE
           SET reason = EXCLUDED.reason,
               case_reference = EXCLUDED.case_reference,
               created_by = EXCLUDED.created_by
           RETURNING hold_id, log_id, reason, case_reference, created_by, created_at""",
        (log_id, reason, case_reference, created_by),
    ).fetchone()
    return dict(row)


def list_archived_access_logs(
    conn: Connection,
    *,
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    ensure_log_retention_schema(conn)
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
        params.append(date_to)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM access_log_archive{clause}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT archive_id, original_log_id, payload_gzip_base64,
                   compressed_at, delete_after
            FROM access_log_archive{clause}
            ORDER BY original_log_id DESC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    items = []
    for row in rows_to_dicts(rows):
        payload = decompress_payload(row.pop("payload_gzip_base64"))
        payload.update(
            {
                "archive_id": row["archive_id"],
                "original_log_id": row["original_log_id"],
                "compressed_at": row["compressed_at"],
                "delete_after": row["delete_after"],
            }
        )
        items.append(payload)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
