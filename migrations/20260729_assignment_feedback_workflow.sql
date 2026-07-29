-- Assignment begins as in_progress on assignment.  Feedback submission and
-- approval drive the remaining transitions in the application layer.

BEGIN;

UPDATE assignments
SET status = 'in_progress'
WHERE status = 'waiting_acceptance';

ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_status_check;
ALTER TABLE assignments
    ADD CONSTRAINT assignments_status_check
    CHECK (status IN ('in_progress', 'under_review', 'completed'));

COMMIT;
