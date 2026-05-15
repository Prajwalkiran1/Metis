"""admin_notifications table for HOD publish events

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-15

M10a introduces a self-publish flow for semester setups. The admin needs
to see (but not approve) when an HOD publishes a setup. Rather than
leaking notification-state columns onto `semester_setups`, this table
holds the feed entries.

Mark-as-read is out of scope for M10a — the column exists so M5 (comms)
can wire it without another migration.
"""
from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE admin_notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            college_id UUID NOT NULL REFERENCES colleges(id),
            event_type VARCHAR(50) NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            read_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_admin_notifications_college_created
        ON admin_notifications (college_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_notifications_college_created")
    op.execute("DROP TABLE IF EXISTS admin_notifications")
