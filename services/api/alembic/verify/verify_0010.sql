-- Run after `alembic upgrade 0010`.

\echo '── admin_notifications table exists ────────────────────────────────'
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'admin_notifications';
-- Expected: 1 row

\echo '── expected columns + types ────────────────────────────────────────'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'admin_notifications'
ORDER BY ordinal_position;
-- Expected columns: id (uuid, NO), college_id (uuid, NO), event_type (varchar, NO),
--                   payload (jsonb, NO), created_at (timestamptz, NO), read_at (timestamptz, YES)

\echo '── FK to colleges in place ─────────────────────────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'admin_notifications'::regclass AND contype = 'f';
-- Expected: 1 row (admin_notifications_college_id_fkey or similar)

\echo '── composite index for feed query ──────────────────────────────────'
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'admin_notifications'
  AND indexname = 'ix_admin_notifications_college_created';
-- Expected: 1 row

\echo '── no orphan rows (FK invariant) ───────────────────────────────────'
SELECT COUNT(*) AS orphans
FROM admin_notifications an
LEFT JOIN colleges c ON c.id = an.college_id
WHERE c.id IS NULL;
-- Expected: 0
