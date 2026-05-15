-- Run after `alembic upgrade 0012`.

\echo '── max_enrollment column on elective_group_options ─────────────────'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'elective_group_options'
  AND column_name = 'max_enrollment';
-- Expected: 1 row, smallint, YES

\echo '── positive-cap CHECK in place ─────────────────────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'elective_group_options'::regclass
  AND conname = 'ck_eopt_max_enrollment_positive';
-- Expected: 1 row

\echo '── existing rows untouched ─────────────────────────────────────────'
SELECT COUNT(*) AS rows_with_cap
FROM elective_group_options
WHERE max_enrollment IS NOT NULL;
-- Expected: 0 (pre-migration all NULL)
