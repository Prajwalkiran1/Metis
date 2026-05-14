"""m2 rework — constraint tightening

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-15

Locks down everything 0008 backfilled:

- USN is required for students, must match the BMSCE pattern
  `^1BM\\d{2}[A-Z]{2}\\d{3}$`, and is unique per college (active rows).
- `course_offerings.assessment_scheme_id` gets its FK (pointed at
  `assessment_schemes.id`) now that backfill is done.
- `assessment_scheme_components.aat` weight is capped at 40% per BMSCE.
- One HOD per department (partial unique on the new column).
- `hall_tickets.current_version_id` and `grade_cards.current_version_id`
  get DEFERRABLE INITIALLY DEFERRED FKs so create-and-link can happen in
  one transaction.
- `see_results.is_current` is single-per-enrollment.

The deprecated v1 tables `attendance_overrides` and `grade_rules` are
left in place (their drops are commented at the bottom for a future
cleanup migration once no code references them).
"""
from __future__ import annotations

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. USN required for active students ─────────────────────────────────
    op.execute(
        """
        ALTER TABLE users
        ADD CONSTRAINT users_student_usn_required
        CHECK (role <> 'student' OR usn IS NOT NULL OR deleted_at IS NOT NULL)
        """
    )

    # ── 2. USN format CHECK (BMSCE pattern: 1BM + YY + DD + RRR) ────────────
    op.execute(
        r"""
        ALTER TABLE users
        ADD CONSTRAINT users_usn_format
        CHECK (usn IS NULL OR usn ~ '^1BM\d{2}[A-Z]{2}\d{3}$')
        """
    )

    # ── 3. USN unique per (college_id, usn) when active ─────────────────────
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_usn_per_college_active
        ON users (college_id, usn)
        WHERE usn IS NOT NULL AND deleted_at IS NULL
        """
    )

    # ── 4. FK course_offerings.assessment_scheme_id ─────────────────────────
    op.execute(
        """
        ALTER TABLE course_offerings
        ADD CONSTRAINT fk_offerings_assessment_scheme
        FOREIGN KEY (assessment_scheme_id) REFERENCES assessment_schemes(id)
        """
    )

    # ── 5. AAT weight ≤ 40% ─────────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE assessment_scheme_components
        ADD CONSTRAINT ck_scheme_comp_aat_max_40pct
        CHECK (kind <> 'aat' OR weight_percent <= 40)
        """
    )

    # ── 6. One HOD per department (partial unique on the user column) ──────
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_one_hod_per_dept
        ON users (hod_of_department_id)
        WHERE hod_of_department_id IS NOT NULL AND deleted_at IS NULL
        """
    )

    # ── 7. Deferred FKs for current_version_id pointers ─────────────────────
    op.execute(
        """
        ALTER TABLE hall_tickets
        ADD CONSTRAINT fk_hall_tickets_current_version
        FOREIGN KEY (current_version_id) REFERENCES hall_ticket_versions(id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE grade_cards
        ADD CONSTRAINT fk_grade_cards_current_version
        FOREIGN KEY (current_version_id) REFERENCES grade_card_versions(id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )

    # ── 8. Single current SEE result per enrollment ────────────────────────
    op.execute(
        """
        CREATE UNIQUE INDEX uq_see_results_one_current_per_enrollment
        ON see_results (enrollment_id)
        WHERE is_current = true AND deleted_at IS NULL
        """
    )

    # Deferred (leave commented; do not run yet — v1 tables stay queryable
    # until M3/M4 rework removes the last reader):
    #   DROP TABLE IF EXISTS attendance_overrides CASCADE;
    #   DROP TABLE IF EXISTS grade_rules CASCADE;


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_see_results_one_current_per_enrollment"
    )
    op.execute(
        "ALTER TABLE grade_cards DROP CONSTRAINT IF EXISTS fk_grade_cards_current_version"
    )
    op.execute(
        "ALTER TABLE hall_tickets DROP CONSTRAINT IF EXISTS fk_hall_tickets_current_version"
    )
    op.execute("DROP INDEX IF EXISTS uq_users_one_hod_per_dept")
    op.execute(
        "ALTER TABLE assessment_scheme_components "
        "DROP CONSTRAINT IF EXISTS ck_scheme_comp_aat_max_40pct"
    )
    op.execute(
        "ALTER TABLE course_offerings "
        "DROP CONSTRAINT IF EXISTS fk_offerings_assessment_scheme"
    )
    op.execute("DROP INDEX IF EXISTS uq_users_usn_per_college_active")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_usn_format")
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_student_usn_required"
    )
