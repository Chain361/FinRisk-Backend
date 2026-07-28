-- Error/debug log table and short-retention metadata.
-- Run after 20260728_log_retention.sql with a role that can create/alter tables.

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

INSERT INTO app_config (key, value, description)
VALUES
    ('error_debug_log_hot_days', '30', 'maximum hot retention for masked error/debug logs that may contain sensitive data')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    description = EXCLUDED.description;
