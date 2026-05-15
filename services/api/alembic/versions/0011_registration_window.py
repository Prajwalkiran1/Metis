"""semester_setups registration window

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-15

Adds the HOD-controlled registration window to semester_setups. Both
columns are nullable until the HOD calls POST
/workflow/semester-setups/{id}/registration-window. Window-open is a
runtime predicate (state in (published, active) AND now() BETWEEN
opens_at AND closes_at) — no enum/state change required.

Why not on a separate table: there is exactly one window per setup,
the columns are tiny, and joining a registration_windows row on every
student-registration GET would add an unnecessary roundtrip.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "semester_setups",
        sa.Column(
            "registration_opens_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "semester_setups",
        sa.Column(
            "registration_closes_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Sanity CHECK: a closed-window-before-open setup is meaningless.
    # The window itself can be NULL on both ends until the HOD sets it.
    op.execute(
        """
        ALTER TABLE semester_setups
        ADD CONSTRAINT ck_semester_setups_window_order
        CHECK (
            registration_opens_at IS NULL
            OR registration_closes_at IS NULL
            OR registration_closes_at > registration_opens_at
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE semester_setups "
        "DROP CONSTRAINT IF EXISTS ck_semester_setups_window_order"
    )
    op.drop_column("semester_setups", "registration_closes_at")
    op.drop_column("semester_setups", "registration_opens_at")
