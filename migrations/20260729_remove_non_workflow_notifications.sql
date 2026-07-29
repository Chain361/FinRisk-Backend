-- Keep only assignment-workflow notifications in the bell.
-- Clarification and high-risk notices are no longer part of the assignment status workflow.
DELETE FROM notifications
WHERE type IN ('attachment', 'clarification', 'high_risk');
