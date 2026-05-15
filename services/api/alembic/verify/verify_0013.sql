-- Run after `alembic upgrade 0013`.

\echo '── task_assignments table exists with the right columns ────────────'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'task_assignments'
ORDER BY ordinal_position;
-- Expected: id (uuid), task_id (uuid), assignee_user_id (uuid),
--           status (USER-DEFINED), status_updated_at (timestamp...),
--           decline_reason (text), created_at, updated_at, deleted_at

\echo '── partial unique index on (task_id, assignee_user_id) where active ─'
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'task_assignments'
  AND indexname = 'uq_task_assignments_task_assignee_active';
-- Expected: 1 row with `WHERE (deleted_at IS NULL)` in the index definition

\echo '── tasks lost the per-assignee columns ─────────────────────────────'
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tasks'
  AND column_name IN ('assigned_to_user_id', 'status', 'status_updated_at', 'decline_reason');
-- Expected: 0 rows

\echo '── backfill one row per pre-migration task (counts match) ──────────'
SELECT
    (SELECT COUNT(*) FROM tasks WHERE deleted_at IS NULL) AS task_count,
    (SELECT COUNT(*) FROM task_assignments WHERE deleted_at IS NULL) AS assignment_count;
-- Expected: assignment_count >= task_count (== for vanilla seed; > if
-- the migration ran after a multi-assignee insert).

\echo '── duplicate active assignment is rejected by the unique index ────'
DO $$
DECLARE
    sample_task UUID;
    sample_assignee UUID;
BEGIN
    SELECT task_id, assignee_user_id INTO sample_task, sample_assignee
    FROM task_assignments WHERE deleted_at IS NULL LIMIT 1;
    IF sample_task IS NULL THEN
        RAISE NOTICE 'no rows to test duplicate insert';
        RETURN;
    END IF;
    BEGIN
        INSERT INTO task_assignments (task_id, assignee_user_id)
        VALUES (sample_task, sample_assignee);
        RAISE EXCEPTION 'duplicate insert should have failed';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'duplicate rejected as expected';
    END;
END $$;
