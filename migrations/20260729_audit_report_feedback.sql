-- One approved feedback item produces at most one audit report.
ALTER TABLE audit_reports ADD COLUMN IF NOT EXISTS feedback_id INTEGER;
ALTER TABLE audit_reports
    ADD CONSTRAINT audit_reports_feedback_id_fkey
    FOREIGN KEY (feedback_id) REFERENCES auditor_feedback(feedback_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_reports_feedback_unique
    ON audit_reports(feedback_id)
    WHERE feedback_id IS NOT NULL;
