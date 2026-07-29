-- Simplify the assignment workflow to four states and migrate active assignments.
-- Legacy status-history rows are deliberately preserved for auditability.

BEGIN;

UPDATE assignments
SET status = CASE status
    WHEN 'accepted' THEN 'in_progress'
    WHEN 'clarification_needed' THEN 'in_progress'
    WHEN 'revision_requested' THEN 'in_progress'
    WHEN 'ready_for_review' THEN 'under_review'
    WHEN 'pending_approval' THEN 'under_review'
    ELSE status
END
WHERE status NOT IN ('waiting_acceptance', 'in_progress', 'under_review', 'completed');

ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_status_check;
ALTER TABLE assignments
    ADD CONSTRAINT assignments_status_check
    CHECK (status IN ('waiting_acceptance', 'in_progress', 'under_review', 'completed'));

COMMIT;
