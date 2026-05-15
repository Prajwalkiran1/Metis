"""elective_group_options per-option cap

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-15

The M10b capacity-cap flow targets an option, not a group ("ML can only
fit 50 because the lab fits 50; the other options in this group are
uncapped"). The schema previously only had `elective_groups.max_enrollment`,
which is too coarse. This adds `elective_group_options.max_enrollment`
(smallint NULL — uncapped by default).

Group-level `max_enrollment` stays as a soft total for the group as a
whole; it's informational. The hard cap that the cascade respects lives
on the option row.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "elective_group_options",
        sa.Column("max_enrollment", sa.SmallInteger(), nullable=True),
    )
    op.execute(
        """
        ALTER TABLE elective_group_options
        ADD CONSTRAINT ck_eopt_max_enrollment_positive
        CHECK (max_enrollment IS NULL OR max_enrollment > 0)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE elective_group_options "
        "DROP CONSTRAINT IF EXISTS ck_eopt_max_enrollment_positive"
    )
    op.drop_column("elective_group_options", "max_enrollment")
