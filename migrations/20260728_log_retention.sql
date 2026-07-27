-- Log retention policy tables for access/security audit logs.
-- Run with a database role that can create tables and indexes in the target schema.

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
    archived_count INTEGER NOT NULL,
    deleted_count  INTEGER NOT NULL,
    archive_cutoff TEXT NOT NULL,
    delete_cutoff  TEXT NOT NULL,
    triggered_by   TEXT,
    note           TEXT
);

INSERT INTO app_config (key, value, description)
VALUES
    ('log_retention_hot_days', '90', 'access/security audit logs searchable in hot storage for at least this many days'),
    ('log_retention_archive_days', '365', 'compressed access/security audit log archive retention in days'),
    ('error_debug_log_hot_days', '30', 'recommended maximum hot retention for error/debug logs that may contain sensitive data')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    description = EXCLUDED.description;
