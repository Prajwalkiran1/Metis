-- Run after `alembic upgrade 0014`.

\echo '── course_registration_preferences table exists with the right columns'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'course_registration_preferences'
ORDER BY ordinal_position;
-- Expected: id (uuid), college_id (uuid), semester_setup_id (uuid),
--           student_user_id (uuid), elective_group_id (uuid),
--           elective_group_option_id (uuid), preference_rank (smallint),
--           created_at, updated_at, deleted_at

\echo '── partial unique indexes are in place (rank slot + option dedupe) ──'
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'course_registration_preferences'
  AND indexname IN (
    'uq_crp_student_group_rank_active',
    'uq_crp_student_group_option_active'
  );
-- Expected: 2 rows, both with `WHERE (deleted_at IS NULL)` in the definition.

\echo '── rank check constraint exists ────────────────────────────────────'
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'public.course_registration_preferences'::regclass
  AND contype = 'c'
  AND conname LIKE '%ck_crp_rank_range%';
-- Expected: 1 row, definition includes `preference_rank` 1..3 bounds.
-- (Alembic prefixes the constraint name with the table; we glob-match.)

\echo '── backfill: rank-1 row per approved elective course_registration ──'
SELECT
    (SELECT COUNT(*)
       FROM course_registrations
       WHERE elective_group_id IS NOT NULL
         AND elective_group_option_id IS NOT NULL
         AND status = 'approved'
         AND deleted_at IS NULL) AS approved_elective_regs,
    (SELECT COUNT(*)
       FROM course_registration_preferences
       WHERE preference_rank = 1 AND deleted_at IS NULL) AS rank_1_prefs;
-- Expected: the two counts match.

\echo '── rank > 3 is rejected by the check constraint ────────────────────'
DO $$
DECLARE
    sample_college UUID;
    sample_setup UUID;
    sample_student UUID;
    sample_group UUID;
    sample_option UUID;
BEGIN
    SELECT college_id, semester_setup_id, student_user_id, elective_group_id, elective_group_option_id
      INTO sample_college, sample_setup, sample_student, sample_group, sample_option
      FROM course_registration_preferences
      WHERE deleted_at IS NULL
      LIMIT 1;
    IF sample_setup IS NULL THEN
        RAISE NOTICE 'no rows to test rank rejection';
        RETURN;
    END IF;
    BEGIN
        INSERT INTO course_registration_preferences
            (college_id, semester_setup_id, student_user_id,
             elective_group_id, elective_group_option_id, preference_rank)
        VALUES
            (sample_college, sample_setup, sample_student,
             sample_group, sample_option, 4);
        RAISE EXCEPTION 'rank=4 insert should have failed';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'rank=4 rejected as expected';
    END;
END $$;

\echo '── duplicate active (student, group, rank) is rejected ─────────────'
DO $$
DECLARE
    sample_college UUID;
    sample_setup UUID;
    sample_student UUID;
    sample_group UUID;
    sample_option UUID;
    sample_rank SMALLINT;
BEGIN
    SELECT college_id, semester_setup_id, student_user_id, elective_group_id, elective_group_option_id, preference_rank
      INTO sample_college, sample_setup, sample_student, sample_group, sample_option, sample_rank
      FROM course_registration_preferences
      WHERE deleted_at IS NULL
      LIMIT 1;
    IF sample_setup IS NULL THEN
        RAISE NOTICE 'no rows to test duplicate rank';
        RETURN;
    END IF;
    BEGIN
        INSERT INTO course_registration_preferences
            (college_id, semester_setup_id, student_user_id,
             elective_group_id, elective_group_option_id, preference_rank)
        VALUES
            (sample_college, sample_setup, sample_student,
             sample_group, sample_option, sample_rank);
        RAISE EXCEPTION 'duplicate rank insert should have failed';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'duplicate rank rejected as expected';
    END;
END $$;
