"""create updated_at trigger function (Postgres-only)

Revision ID: 0001
Revises:
Create Date: 2026-05-03

This migration installs a single Postgres function `set_updated_at()` that
later table migrations attach as a `BEFORE UPDATE FOR EACH ROW` trigger.

Doing this once here means every later schema migration just calls
`op.execute("CREATE TRIGGER set_<table>_updated_at ...")` — no copy-pasted
PL/pgSQL across migrations.
"""
from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


SET_UPDATED_AT_FN = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(SET_UPDATED_AT_FN)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
