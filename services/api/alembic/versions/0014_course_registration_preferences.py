"""ranked elective preferences — separate intent from committed enrolment

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-15

M10b ships elective registration as one-pick-per-group. Audit B7 calls for
ranked preferences (1st/2nd/3rd) so dissolution cascades can auto-walk a
per-student fallback chain instead of forcing the HOD to pick one target
option for everyone.

This migration:

1. Creates `course_registration_preferences` — append-only intent table.
   One row per (student, group, rank). Rank is 1-3 (CHECK constraint).
   Partial unique indexes keep ranks distinct and prevent the same option
   appearing twice at different ranks within a group.

2. Backfills every existing approved elective registration as rank-1.
   Migrated/cancelled/backlog rows do not backfill (they're audit, not
   intent). The course_registrations table is untouched — it remains the
   committed-enrolment surface, with this new table acting as the wishlist.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the new intent table.
    op.create_table(
        "course_registration_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "semester_setup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("semester_setups.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "elective_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_groups.id"),
            nullable=False,
        ),
        sa.Column(
            "elective_group_option_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_group_options.id"),
            nullable=False,
        ),
        sa.Column(
            "preference_rank",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "preference_rank BETWEEN 1 AND 3",
            name="ck_crp_rank_range",
        ),
    )

    op.create_index(
        "ix_crp_student_setup",
        "course_registration_preferences",
        ["student_user_id", "semester_setup_id"],
    )
    op.create_index(
        "ix_crp_option",
        "course_registration_preferences",
        ["elective_group_option_id"],
    )

    # Rank slot is unique per (student, group); soft-deleted rows are
    # ignored so a re-submission inside the same window can drop & re-write.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_crp_student_group_rank_active
        ON course_registration_preferences
            (student_user_id, semester_setup_id, elective_group_id, preference_rank)
        WHERE deleted_at IS NULL
        """
    )
    # Same option cannot appear twice within a single student's prefs for
    # one group. Defence-in-depth alongside the service-level dedupe.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_crp_student_group_option_active
        ON course_registration_preferences
            (student_user_id, semester_setup_id, elective_group_id, elective_group_option_id)
        WHERE deleted_at IS NULL
        """
    )

    # 2. Backfill: every approved elective registration becomes a rank-1
    #    preference. created_at copied so audit/order remains stable.
    op.execute(
        """
        INSERT INTO course_registration_preferences (
            id, college_id, semester_setup_id, student_user_id,
            elective_group_id, elective_group_option_id,
            preference_rank, created_at, updated_at, deleted_at
        )
        SELECT
            gen_random_uuid(),
            cr.college_id,
            cr.semester_setup_id,
            cr.student_user_id,
            cr.elective_group_id,
            cr.elective_group_option_id,
            1,
            cr.created_at,
            cr.updated_at,
            NULL
        FROM course_registrations cr
        WHERE cr.elective_group_id IS NOT NULL
          AND cr.elective_group_option_id IS NOT NULL
          AND cr.status = 'approved'
          AND cr.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_crp_student_group_option_active",
        table_name="course_registration_preferences",
    )
    op.drop_index(
        "uq_crp_student_group_rank_active",
        table_name="course_registration_preferences",
    )
    op.drop_index(
        "ix_crp_option", table_name="course_registration_preferences"
    )
    op.drop_index(
        "ix_crp_student_setup", table_name="course_registration_preferences"
    )
    op.drop_table("course_registration_preferences")
