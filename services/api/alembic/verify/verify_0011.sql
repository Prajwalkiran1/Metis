-- Run after `alembic upgrade 0011`.

\echo '── new columns exist with TZ-aware timestamp type ──────────────────'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'semester_setups'
  AND column_name IN ('registration_opens_at', 'registration_closes_at')
ORDER BY column_name;
-- Expected: 2 rows, both TIMESTAMPTZ, both nullable YES

\echo '── window-order CHECK in place ─────────────────────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'semester_setups'::regclass
  AND conname = 'ck_semester_setups_window_order';
-- Expected: 1 row

\echo '── existing rows untouched (window cols default NULL) ──────────────'
SELECT COUNT(*) AS rows_with_window_partly_set
FROM semester_setups
WHERE (registration_opens_at IS NULL) <> (registration_closes_at IS NULL);
-- Expected: 0 — both NULL or both set on any given row (pre-migration was all NULL)
