-- Run after `alembic upgrade 0009`.

\echo '── all USN constraints in place ────────────────────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'users'::regclass
  AND conname IN ('users_student_usn_required', 'users_usn_format')
ORDER BY conname;
-- Expected: 2 rows

\echo '── USN uniqueness index in place ───────────────────────────────────'
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
      'uq_users_usn_per_college_active',
      'uq_users_one_hod_per_dept',
      'uq_see_results_one_current_per_enrollment'
  )
ORDER BY indexname;
-- Expected: 3 rows

\echo '── FK offerings → assessment_schemes in place ──────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'course_offerings'::regclass
  AND conname = 'fk_offerings_assessment_scheme';
-- Expected: 1 row

\echo '── AAT cap CHECK in place ──────────────────────────────────────────'
SELECT conname FROM pg_constraint
WHERE conrelid = 'assessment_scheme_components'::regclass
  AND conname = 'ck_scheme_comp_aat_max_40pct';
-- Expected: 1 row

\echo '── deferred FKs for hall_ticket + grade_card current_version_id ────'
SELECT conname, condeferrable, condeferred
FROM pg_constraint
WHERE conname IN (
    'fk_hall_tickets_current_version',
    'fk_grade_cards_current_version'
)
ORDER BY conname;
-- Expected: 2 rows, both condeferrable=t condeferred=t

\echo '── invariants still hold ───────────────────────────────────────────'
SELECT 'students_missing_usn' AS name, COUNT(*) AS n
FROM users WHERE role = 'student' AND usn IS NULL AND deleted_at IS NULL
UNION ALL
SELECT 'usn_format_violations', COUNT(*)
FROM users WHERE usn IS NOT NULL AND usn !~ '^1BM\d{2}[A-Z]{2}\d{3}$'
UNION ALL
SELECT 'duplicate_hod_per_dept', COUNT(*) - COUNT(DISTINCT hod_of_department_id)
FROM users WHERE hod_of_department_id IS NOT NULL AND deleted_at IS NULL;
-- Expected: all 0
