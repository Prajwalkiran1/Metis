-- Run after `alembic upgrade 0007`. Each query has its expected result.
-- Connect with:   psql "$DATABASE_URL"
-- (or substitute the docker exec form).

\echo '── 22 new tables exist ──────────────────────────────────────────────'
SELECT COUNT(*) AS new_table_count
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'academic_terms',
    'semester_setups', 'elective_groups', 'elective_group_options',
    'course_registrations', 'lab_batches', 'lab_batch_members',
    'lab_batch_assignments', 'assessment_scheme_templates',
    'assessment_schemes', 'assessment_scheme_components',
    'nptel_enrollments', 'internal_deadlines', 'cie_schedule',
    'tasks', 'hall_tickets', 'hall_ticket_versions',
    'grade_cards', 'grade_card_versions', 'see_results',
    're_evaluations', 'academic_overrides', 'eligibility_snapshots',
    'course_drops'
  );
-- Expected: 24

\echo '── 9 new enums exist ───────────────────────────────────────────────'
SELECT typname FROM pg_type
WHERE typname IN (
  'term_type', 'enrollment_state', 'semester_setup_state',
  'assessment_component_kind', 'task_status', 'task_type',
  'override_type', 'grade_status', 'see_result_kind'
)
ORDER BY typname;
-- Expected: 9 rows

\echo '── user_role includes hod ──────────────────────────────────────────'
SELECT enumlabel FROM pg_enum
WHERE enumtypid = 'user_role'::regtype
ORDER BY enumlabel;
-- Expected: includes hod

\echo '── course_type rewritten (theory|lab|integrated|nptel) ─────────────'
SELECT enumlabel FROM pg_enum
WHERE enumtypid = 'course_type'::regtype
ORDER BY enumlabel;
-- Expected: integrated, lab, nptel, theory

\echo '── users new column hod_of_department_id present ───────────────────'
SELECT column_name FROM information_schema.columns
WHERE table_name = 'users' AND column_name = 'hod_of_department_id';
-- Expected: 1 row

\echo '── course_offerings new columns present ────────────────────────────'
SELECT column_name FROM information_schema.columns
WHERE table_name = 'course_offerings'
  AND column_name IN ('parent_offering_id', 'assessment_scheme_id', 'academic_term_id')
ORDER BY column_name;
-- Expected: 3 rows

\echo '── enrollments new columns present ─────────────────────────────────'
SELECT column_name FROM information_schema.columns
WHERE table_name = 'enrollments'
  AND column_name IN ('enrollment_state', 'academic_term_id')
ORDER BY column_name;
-- Expected: 2 rows

\echo '── existing data preserved ─────────────────────────────────────────'
SELECT 'users' AS table_name, COUNT(*) AS rows FROM users
UNION ALL SELECT 'enrollments', COUNT(*) FROM enrollments
UNION ALL SELECT 'course_offerings', COUNT(*) FROM course_offerings
UNION ALL SELECT 'courses', COUNT(*) FROM courses
UNION ALL SELECT 'attendance_records', COUNT(*) FROM attendance_records
UNION ALL SELECT 'marks', COUNT(*) FROM marks
ORDER BY table_name;
-- Expected: row counts unchanged from pre-migration snapshot.
