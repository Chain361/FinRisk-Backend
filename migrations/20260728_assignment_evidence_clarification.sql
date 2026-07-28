-- Evidence attachments + clarification thread for audit assignments (issue #18 / #33).
-- PR #34 added these tables to seed_database.py but shipped without a migration file, unlike
-- the log-retention change (see 20260728_log_retention.sql) — any DB seeded before PR #34
-- merged (e.g. the team's shared dev Postgres) is missing these tables and the feature 500s.
-- Run with a database role that can create tables and indexes in the target schema.

CREATE TABLE IF NOT EXISTS assignment_attachments (
    attachment_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(assignment_id),
    file_name     TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    file_size     INTEGER NOT NULL,
    file_content  BYTEA NOT NULL,
    uploaded_by   INTEGER NOT NULL REFERENCES users(user_id),
    created_at    TEXT NOT NULL DEFAULT (now_text())
);

CREATE INDEX IF NOT EXISTS idx_assignment_attachments_assignment
    ON assignment_attachments(assignment_id);

CREATE TABLE IF NOT EXISTS assignment_clarifications (
    clarification_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    assignment_id     INTEGER NOT NULL REFERENCES assignments(assignment_id),
    message_text      TEXT NOT NULL,
    created_by         INTEGER NOT NULL REFERENCES users(user_id),
    created_at         TEXT NOT NULL DEFAULT (now_text())
);

CREATE INDEX IF NOT EXISTS idx_assignment_clarifications_assignment
    ON assignment_clarifications(assignment_id, clarification_id);
