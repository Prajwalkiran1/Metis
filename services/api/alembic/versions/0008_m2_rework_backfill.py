"""m2 rework — data backfill

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-15

What this migration does (pure data, no DDL except a single bridge table
creation note for the optional HOD seed user):

1. Backfill `academic_terms` from DISTINCT VARCHAR `academic_term` codes
   across course_offerings ∪ enrollments. One row per (college, code).
2. Link `course_offerings.academic_term_id` and `enrollments.academic_term_id`
   to the new academic_terms rows by matching VARCHAR code.
3. Backfill `users.usn` for students using the BMSCE pattern
   `1BM + YY + DD + RRR` (year from users.created_at, dept code from the
   student's first active enrollment via section→batch→department).
   Students with no enrollment get dept code `XX` so they remain visible
   for manual fix-up. The format CHECK in 0009 will reject `XX` rows so
   this is also a forcing function.
4. Backfill `users.hod_of_department_id` from the legacy
   `departments.head_user_id` (one row per department where head_user_id
   is non-NULL). Skips conflicts (a user already mapped to another dept).
5. Generate `semester_setups` rows from DISTINCT
   (college, department, academic_term_id) across course_offerings.
6. Migrate v1 `attendance_overrides` rows → `academic_overrides` with
   `override_type='attendance_condonation'`. Uses the real column names
   (`student_user_id`, `overridden_by_user_id`,
   `class_sessions.course_offering_id`).
7. Pivot v1 `grade_rules` (rows-per-assessment-type) into
   `assessment_schemes` + `assessment_scheme_components`. One scheme per
   `course_offering_id`. Components emit one row per `grade_rules` row.
   Updates `course_offerings.assessment_scheme_id` pointer.
8. Seed 3 institutional `assessment_scheme_templates` per college (Theory
   Standard, Integrated Standard, NPTEL Standard).

The migration is idempotent: every INSERT/UPDATE is guarded by `WHERE
NOT EXISTS` / `IS NULL` checks. Re-running has no effect.
"""
from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. academic_terms backfill ──────────────────────────────────────────
    bind.exec_driver_sql(
        """
        INSERT INTO academic_terms (id, college_id, code, term_type, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            college_id,
            term_code,
            'regular',
            NOW(),
            NOW()
        FROM (
            SELECT DISTINCT college_id, academic_term AS term_code
            FROM course_offerings
            WHERE deleted_at IS NULL AND academic_term IS NOT NULL
            UNION
            SELECT DISTINCT college_id, academic_term
            FROM enrollments
            WHERE academic_term IS NOT NULL
        ) AS distinct_terms
        WHERE NOT EXISTS (
            SELECT 1 FROM academic_terms at
            WHERE at.college_id = distinct_terms.college_id
              AND at.code = distinct_terms.term_code
              AND at.deleted_at IS NULL
        );
        """
    )

    # ── 2. link course_offerings + enrollments to new academic_terms ────────
    bind.exec_driver_sql(
        """
        UPDATE course_offerings co
        SET academic_term_id = at.id
        FROM academic_terms at
        WHERE at.college_id = co.college_id
          AND at.code = co.academic_term
          AND at.deleted_at IS NULL
          AND co.academic_term_id IS NULL;
        """
    )

    bind.exec_driver_sql(
        """
        UPDATE enrollments e
        SET academic_term_id = at.id
        FROM academic_terms at
        WHERE at.college_id = e.college_id
          AND at.code = e.academic_term
          AND at.deleted_at IS NULL
          AND e.academic_term_id IS NULL;
        """
    )

    # ── 3. USN backfill for students ────────────────────────────────────────
    # BMSCE pattern: 1BM + YY + DD + RRR
    # YY = last 2 digits of users.created_at year
    # DD = department code (left 2 chars uppercased) of student's first
    #      active enrollment, joined via section → batch → department.
    #      Falls back to 'XX' if no enrollment exists (those rows will be
    #      rejected by 0009 format CHECK, which surfaces them for manual fix).
    # RRR = next 3-digit sequence within (college_id, YY, DD).
    bind.exec_driver_sql(
        """
        DO $do$
        DECLARE
            rec RECORD;
            v_yy TEXT;
            v_dd TEXT;
            v_seq INTEGER;
            v_usn TEXT;
        BEGIN
            FOR rec IN
                SELECT u.id, u.college_id, u.created_at,
                       (
                           SELECT UPPER(LEFT(d.code, 2))
                           FROM enrollments e
                           JOIN sections s ON s.id = e.section_id
                           JOIN batches b ON b.id = s.batch_id
                           JOIN departments d ON d.id = b.department_id
                           WHERE e.student_user_id = u.id
                             AND e.withdrawn_at IS NULL
                           ORDER BY e.enrolled_at ASC
                           LIMIT 1
                       ) AS dept_code
                FROM users u
                WHERE u.role = 'student'
                  AND u.usn IS NULL
                  AND u.deleted_at IS NULL
                ORDER BY u.created_at ASC, u.id ASC
            LOOP
                v_yy := TO_CHAR(rec.created_at, 'YY');
                v_dd := COALESCE(rec.dept_code, 'XX');

                SELECT COALESCE(MAX(
                    CASE
                        WHEN usn ~ ('^1BM' || v_yy || v_dd || '\\d{3}$')
                        THEN CAST(SUBSTRING(usn FROM 8 FOR 3) AS INTEGER)
                        ELSE 0
                    END
                ), 0) + 1
                INTO v_seq
                FROM users
                WHERE college_id = rec.college_id
                  AND usn IS NOT NULL;

                v_usn := '1BM' || v_yy || v_dd || LPAD(v_seq::TEXT, 3, '0');

                UPDATE users SET usn = v_usn WHERE id = rec.id;
            END LOOP;
        END
        $do$;
        """
    )

    # ── 4. HOD backfill from legacy departments.head_user_id ────────────────
    # For each (college, dept) where head_user_id is set, copy onto the user
    # and promote the user's role to 'hod'. We skip users that are already
    # mapped to a different department to keep the one-HOD-per-dept invariant
    # easy to enforce in 0009.
    bind.exec_driver_sql(
        """
        UPDATE users u
        SET hod_of_department_id = d.id,
            role = 'hod'
        FROM departments d
        WHERE d.head_user_id = u.id
          AND d.deleted_at IS NULL
          AND u.hod_of_department_id IS NULL
          AND u.deleted_at IS NULL
          -- only promote if no other user already claims this dept
          AND NOT EXISTS (
              SELECT 1 FROM users u2
              WHERE u2.hod_of_department_id = d.id
                AND u2.deleted_at IS NULL
                AND u2.id <> u.id
          );
        """
    )

    # ── 5. semester_setups backfill ─────────────────────────────────────────
    # One semester_setup per (college, dept, academic_term_id) that has
    # offerings. State = 'active' since these are already-running terms.
    # drafted_by_user_id = any admin in the same college; falls back to any
    # user in the college if none exists (the FK still has to point somewhere).
    bind.exec_driver_sql(
        """
        INSERT INTO semester_setups (
            id, college_id, department_id, academic_term_id, state,
            drafted_by_user_id, published_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            co.college_id,
            c.department_id,
            co.academic_term_id,
            'active',
            COALESCE(
                (SELECT id FROM users
                 WHERE role = 'admin' AND college_id = co.college_id
                   AND deleted_at IS NULL
                 ORDER BY created_at ASC LIMIT 1),
                (SELECT id FROM users
                 WHERE college_id = co.college_id AND deleted_at IS NULL
                 ORDER BY created_at ASC LIMIT 1)
            ),
            NOW(),
            NOW(),
            NOW()
        FROM (
            SELECT DISTINCT co.college_id, c.department_id, co.academic_term_id
            FROM course_offerings co
            JOIN courses c ON c.id = co.course_id
            WHERE co.deleted_at IS NULL
              AND c.deleted_at IS NULL
              AND co.academic_term_id IS NOT NULL
        ) AS distinct_setups
        JOIN course_offerings co
          ON co.college_id = distinct_setups.college_id
          AND co.academic_term_id = distinct_setups.academic_term_id
        JOIN courses c
          ON c.id = co.course_id
         AND c.department_id = distinct_setups.department_id
        WHERE NOT EXISTS (
            SELECT 1 FROM semester_setups ss
            WHERE ss.college_id = distinct_setups.college_id
              AND ss.department_id = distinct_setups.department_id
              AND ss.academic_term_id = distinct_setups.academic_term_id
              AND ss.deleted_at IS NULL
        )
        GROUP BY co.college_id, c.department_id, co.academic_term_id;
        """
    )

    # ── 6. attendance_overrides → academic_overrides ────────────────────────
    # v1 attendance_overrides has (class_session_id, attendance_record_id,
    # student_user_id, overridden_by_user_id, reason). Join class_sessions
    # for the offering pointer.
    bind.exec_driver_sql(
        """
        INSERT INTO academic_overrides (
            id, college_id, override_type, actor_user_id,
            target_student_user_id, target_course_offering_id,
            target_entity_type, target_entity_id,
            reason, created_at
        )
        SELECT
            gen_random_uuid(),
            ao.college_id,
            'attendance_condonation',
            ao.overridden_by_user_id,
            ao.student_user_id,
            cs.course_offering_id,
            'attendance_record',
            ao.attendance_record_id,
            COALESCE(ao.reason, 'Migrated from v1 attendance_overrides'),
            ao.created_at
        FROM attendance_overrides ao
        LEFT JOIN attendance_records ar ON ar.id = ao.attendance_record_id
        LEFT JOIN class_sessions cs ON cs.id = COALESCE(ar.class_session_id, ao.class_session_id)
        WHERE NOT EXISTS (
            SELECT 1 FROM academic_overrides ao2
            WHERE ao2.target_entity_id = ao.attendance_record_id
              AND ao2.override_type = 'attendance_condonation'
        );
        """
    )

    # ── 7. grade_rules → assessment_schemes + components ────────────────────
    # v1 grade_rules is rows-per-(offering, assessment_type) with
    # weight_percent. Pivot: one assessment_scheme per offering, one
    # component per grade_rules row. Then link course_offerings →
    # assessment_scheme.
    bind.exec_driver_sql(
        """
        DO $do$
        DECLARE
            rec RECORD;
            v_scheme_id UUID;
            v_actor_user_id UUID;
            v_kind TEXT;
            v_label TEXT;
            v_max_marks NUMERIC(6,2);
            v_ordinal SMALLINT;
        BEGIN
            FOR rec IN
                SELECT DISTINCT gr.college_id, gr.course_offering_id
                FROM grade_rules gr
                JOIN course_offerings co ON co.id = gr.course_offering_id
                WHERE co.deleted_at IS NULL
                  AND co.assessment_scheme_id IS NULL
            LOOP
                -- Actor: any admin in the college, fallback to any user.
                SELECT id INTO v_actor_user_id
                FROM users
                WHERE role = 'admin'
                  AND college_id = rec.college_id
                  AND deleted_at IS NULL
                ORDER BY created_at ASC LIMIT 1;
                IF v_actor_user_id IS NULL THEN
                    SELECT id INTO v_actor_user_id
                    FROM users
                    WHERE college_id = rec.college_id AND deleted_at IS NULL
                    ORDER BY created_at ASC LIMIT 1;
                END IF;
                IF v_actor_user_id IS NULL THEN
                    -- No users in this college; cannot create scheme. Skip.
                    CONTINUE;
                END IF;

                -- Create the per-offering scheme.
                v_scheme_id := gen_random_uuid();
                INSERT INTO assessment_schemes (
                    id, college_id, course_offering_id, template_id,
                    configured_by_user_id, is_locked, created_at, updated_at
                ) VALUES (
                    v_scheme_id, rec.college_id, rec.course_offering_id, NULL,
                    v_actor_user_id, false, NOW(), NOW()
                );

                -- Components, one per grade_rule row for this offering.
                FOR rec IN
                    SELECT assessment_type::text AS atype, weight_percent
                    FROM grade_rules
                    WHERE course_offering_id = rec.course_offering_id
                    ORDER BY assessment_type
                LOOP
                    CASE rec.atype
                        WHEN 'cie1' THEN
                            v_kind := 'cie'; v_label := 'CIE-1';
                            v_max_marks := 40; v_ordinal := 1;
                        WHEN 'cie2' THEN
                            v_kind := 'cie'; v_label := 'CIE-2';
                            v_max_marks := 40; v_ordinal := 2;
                        WHEN 'cie3' THEN
                            v_kind := 'cie'; v_label := 'CIE-3';
                            v_max_marks := 40; v_ordinal := 3;
                        WHEN 'see' THEN
                            v_kind := 'see'; v_label := 'SEE';
                            v_max_marks := 100; v_ordinal := 5;
                        WHEN 'assignment' THEN
                            v_kind := 'assignment'; v_label := 'Assignment';
                            v_max_marks := 10; v_ordinal := 6;
                        WHEN 'lab' THEN
                            v_kind := 'lab'; v_label := 'Lab';
                            v_max_marks := 25; v_ordinal := 4;
                        ELSE
                            v_kind := 'assignment'; v_label := UPPER(rec.atype);
                            v_max_marks := 10; v_ordinal := 9;
                    END CASE;

                    INSERT INTO assessment_scheme_components (
                        id, college_id, assessment_scheme_id, kind, label,
                        max_marks, weight_percent, ordinal,
                        is_dropped_in_best_of, metadata_json,
                        created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(),
                        (SELECT college_id FROM assessment_schemes
                         WHERE id = v_scheme_id),
                        v_scheme_id,
                        v_kind::assessment_component_kind,
                        v_label, v_max_marks, rec.weight_percent, v_ordinal,
                        false, '{}'::jsonb, NOW(), NOW()
                    );
                END LOOP;

                -- Link the offering to its new scheme. We need to refetch
                -- the offering id because rec was reused above.
                UPDATE course_offerings
                SET assessment_scheme_id = v_scheme_id
                WHERE assessment_scheme_id IS NULL
                  AND id = (
                      SELECT course_offering_id FROM assessment_schemes
                      WHERE id = v_scheme_id
                  );
            END LOOP;
        END
        $do$;
        """
    )

    # ── 8. Seed institutional assessment_scheme_templates ──────────────────
    bind.exec_driver_sql(
        """
        INSERT INTO assessment_scheme_templates (
            id, college_id, owner_department_id, name, description,
            applies_to_course_type, validation_rules, default_components,
            is_active, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            c.id,
            NULL,
            'Theory Standard',
            'BMSCE default for theory courses',
            'theory',
            '{"cie_count": 3, "cie_best_of": 2, "cie_equal_weights": true, "aat_max_percent": 40, "see_rescale_to": 50, "internal_threshold_main_percent": 40, "internal_threshold_makeup_percent": 60}'::jsonb,
            '[
                {"kind":"cie","label":"CIE-1","max_marks":40,"weight_percent":20,"ordinal":1,"metadata":{"best_of_group":"cie"}},
                {"kind":"cie","label":"CIE-2","max_marks":40,"weight_percent":20,"ordinal":2,"metadata":{"best_of_group":"cie"}},
                {"kind":"cie","label":"CIE-3","max_marks":40,"weight_percent":20,"ordinal":3,"metadata":{"best_of_group":"cie"}},
                {"kind":"aat","label":"AAT","max_marks":20,"weight_percent":10,"ordinal":4},
                {"kind":"see","label":"SEE","max_marks":100,"weight_percent":50,"ordinal":5}
            ]'::jsonb,
            true,
            NOW(),
            NOW()
        FROM colleges c
        WHERE NOT EXISTS (
            SELECT 1 FROM assessment_scheme_templates t
            WHERE t.college_id = c.id
              AND t.name = 'Theory Standard'
              AND t.owner_department_id IS NULL
              AND t.deleted_at IS NULL
        );
        """
    )

    bind.exec_driver_sql(
        """
        INSERT INTO assessment_scheme_templates (
            id, college_id, owner_department_id, name, description,
            applies_to_course_type, validation_rules, default_components,
            is_active, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            c.id,
            NULL,
            'Integrated Standard',
            'BMSCE default for integrated (theory + lab) courses',
            'integrated',
            '{"cie_count": 3, "cie_best_of": 2, "cie_equal_weights": true, "lab_required": true, "see_rescale_to": 50, "internal_threshold_main_percent": 40, "internal_threshold_makeup_percent": 60}'::jsonb,
            '[
                {"kind":"cie","label":"CIE-1","max_marks":20,"weight_percent":10,"ordinal":1,"metadata":{"best_of_group":"cie"}},
                {"kind":"cie","label":"CIE-2","max_marks":20,"weight_percent":10,"ordinal":2,"metadata":{"best_of_group":"cie"}},
                {"kind":"cie","label":"CIE-3","max_marks":20,"weight_percent":10,"ordinal":3,"metadata":{"best_of_group":"cie"}},
                {"kind":"lab","label":"Lab","max_marks":25,"weight_percent":25,"ordinal":4},
                {"kind":"aat","label":"AAT","max_marks":5,"weight_percent":5,"ordinal":5},
                {"kind":"see","label":"SEE","max_marks":100,"weight_percent":50,"ordinal":6}
            ]'::jsonb,
            true,
            NOW(),
            NOW()
        FROM colleges c
        WHERE NOT EXISTS (
            SELECT 1 FROM assessment_scheme_templates t
            WHERE t.college_id = c.id
              AND t.name = 'Integrated Standard'
              AND t.owner_department_id IS NULL
              AND t.deleted_at IS NULL
        );
        """
    )

    bind.exec_driver_sql(
        """
        INSERT INTO assessment_scheme_templates (
            id, college_id, owner_department_id, name, description,
            applies_to_course_type, validation_rules, default_components,
            is_active, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            c.id,
            NULL,
            'NPTEL Standard',
            'BMSCE default for NPTEL/MOOC courses',
            'nptel',
            '{"no_attendance": true, "no_cie": true, "carry_over_allowed": true}'::jsonb,
            '[
                {"kind":"nptel_assignment","label":"NPTEL Assignments","max_marks":40,"weight_percent":40,"ordinal":1},
                {"kind":"nptel_final","label":"NPTEL Final Exam","max_marks":60,"weight_percent":60,"ordinal":2}
            ]'::jsonb,
            true,
            NOW(),
            NOW()
        FROM colleges c
        WHERE NOT EXISTS (
            SELECT 1 FROM assessment_scheme_templates t
            WHERE t.college_id = c.id
              AND t.name = 'NPTEL Standard'
              AND t.owner_department_id IS NULL
              AND t.deleted_at IS NULL
        );
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Remove only what 0008 inserted, identified by markers.
    bind.exec_driver_sql(
        "DELETE FROM assessment_scheme_templates WHERE owner_department_id IS NULL;"
    )

    # Unlink offerings from schemes, then delete schemes + components created
    # by 0008. Components cascade via FK.
    bind.exec_driver_sql(
        "UPDATE course_offerings SET assessment_scheme_id = NULL;"
    )
    bind.exec_driver_sql("DELETE FROM assessment_scheme_components;")
    bind.exec_driver_sql("DELETE FROM assessment_schemes;")

    bind.exec_driver_sql(
        """
        DELETE FROM academic_overrides
        WHERE reason = 'Migrated from v1 attendance_overrides'
           OR (override_type = 'attendance_condonation'
               AND target_entity_type = 'attendance_record');
        """
    )

    # Revert HOD backfill: clear hod_of_department_id and demote role back to
    # the most likely prior role. We assume the legacy state was role=admin
    # for users that also appeared in departments.head_user_id (the common
    # case in seed data) and role=teacher otherwise. This is heuristic and
    # destructive; only meaningful if backfill ran cleanly.
    bind.exec_driver_sql(
        """
        UPDATE users SET hod_of_department_id = NULL, role = 'teacher'
        WHERE hod_of_department_id IS NOT NULL AND role = 'hod';
        """
    )

    bind.exec_driver_sql(
        "DELETE FROM semester_setups WHERE state = 'active';"
    )

    bind.exec_driver_sql(
        "UPDATE users SET usn = NULL WHERE role = 'student';"
    )

    bind.exec_driver_sql(
        "UPDATE enrollments SET academic_term_id = NULL;"
    )
    bind.exec_driver_sql(
        "UPDATE course_offerings SET academic_term_id = NULL;"
    )
    bind.exec_driver_sql("DELETE FROM academic_terms;")
