-- Run after `alembic upgrade 0008`.

\echo '── every student has a USN ─────────────────────────────────────────'
SELECT COUNT(*) FILTER (WHERE usn IS NULL) AS missing
FROM users WHERE role = 'student' AND deleted_at IS NULL;
-- Expected: 0

\echo '── USNs match BMSCE pattern (any XX dept rows surface here) ────────'
SELECT id, email, usn FROM users
WHERE role = 'student'
  AND usn IS NOT NULL
  AND usn !~ '^1BM\d{2}[A-Z]{2}\d{3}$'
ORDER BY usn;
-- Expected: empty result.
-- If any rows have 'XX' in chars 6-7, the student has no enrollment and
-- the dept code couldn't be derived; assign manually before 0009.

\echo '── USNs unique per college ─────────────────────────────────────────'
SELECT college_id, usn, COUNT(*) AS cnt
FROM users WHERE usn IS NOT NULL
GROUP BY college_id, usn HAVING COUNT(*) > 1;
-- Expected: empty

\echo '── academic_terms backfilled from VARCHAR codes ────────────────────'
SELECT at.code, COUNT(co.id) AS offerings_linked
FROM academic_terms at
LEFT JOIN course_offerings co ON co.academic_term_id = at.id
GROUP BY at.code ORDER BY at.code;
-- Expected: one row per distinct academic_term VARCHAR; offerings_linked > 0
-- for active terms.

\echo '── every active course_offering linked to an academic_term ─────────'
SELECT COUNT(*) FROM course_offerings
WHERE deleted_at IS NULL AND academic_term_id IS NULL;
-- Expected: 0 (or only the corner case where academic_term VARCHAR was NULL)

\echo '── every active course_offering has an assessment_scheme ───────────'
SELECT COUNT(*) FROM course_offerings co
WHERE co.deleted_at IS NULL
  AND co.assessment_scheme_id IS NULL
  AND EXISTS (
      SELECT 1 FROM grade_rules gr WHERE gr.course_offering_id = co.id
  );
-- Expected: 0 (offerings without grade_rules still won't have a scheme;
-- that's fine — HOD/teacher configures one in M10c).

\echo '── institutional scheme templates (3 per college) ──────────────────'
SELECT c.code, COUNT(t.id) AS templates
FROM colleges c
LEFT JOIN assessment_scheme_templates t
  ON t.college_id = c.id
 AND t.owner_department_id IS NULL
 AND t.is_active = true
 AND t.deleted_at IS NULL
GROUP BY c.code ORDER BY c.code;
-- Expected: each college has 3 (Theory, Integrated, NPTEL)

\echo '── semester_setups generated ───────────────────────────────────────'
SELECT COUNT(*) AS setups,
       COUNT(*) FILTER (WHERE state = 'active') AS active_setups
FROM semester_setups WHERE deleted_at IS NULL;
-- Expected: at least one per (college, dept, term) with offerings; all 'active'.

\echo '── HOD backfill from departments.head_user_id ──────────────────────'
SELECT u.email, u.role, d.code AS hod_dept
FROM users u
JOIN departments d ON d.id = u.hod_of_department_id
WHERE u.deleted_at IS NULL
ORDER BY u.email;
-- Expected: one row per (legacy) head_user_id; role='hod'.

\echo '── attendance_overrides migrated to academic_overrides ─────────────'
SELECT
  (SELECT COUNT(*) FROM attendance_overrides) AS v1_rows,
  (SELECT COUNT(*) FROM academic_overrides
   WHERE override_type = 'attendance_condonation'
     AND target_entity_type = 'attendance_record') AS migrated_rows;
-- Expected: migrated_rows = v1_rows.

\echo '── grade_rules pivoted into assessment_schemes + components ────────'
SELECT
  (SELECT COUNT(DISTINCT course_offering_id) FROM grade_rules) AS v1_offerings,
  (SELECT COUNT(*) FROM assessment_schemes) AS new_schemes,
  (SELECT COUNT(*) FROM assessment_scheme_components) AS new_components;
-- Expected: new_schemes = v1_offerings; new_components ≥ v1_offerings.
