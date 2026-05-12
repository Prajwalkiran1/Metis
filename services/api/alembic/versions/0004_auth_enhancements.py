"""auth enhancements — per-college email domain + google_sub

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12

Adds:
- `colleges.email_domain` — exact-match-only domain required for every
  user created under that college (e.g. 'bmsce.ac.in'). Backfilled with
  'bmsce.ac.in' so existing rows keep working.
- `users.google_sub` — Google OAuth `sub` claim, bound on first
  successful Google sign-in. Unique so a Google identity can't map to
  two Metis accounts.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # colleges.email_domain
    op.add_column(
        "colleges",
        sa.Column(
            "email_domain",
            sa.String(80),
            nullable=False,
            server_default=sa.text("'bmsce.ac.in'"),
        ),
    )

    # users.google_sub (nullable + unique). A partial unique index would be
    # ideal here (only enforce uniqueness when non-null), but Postgres
    # treats multiple NULLs as distinct by default — so a plain UNIQUE
    # constraint already allows many NULL rows. Keeping it simple.
    op.add_column("users", sa.Column("google_sub", sa.String(80), nullable=True))
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])


def downgrade() -> None:
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_column("users", "google_sub")
    op.drop_column("colleges", "email_domain")
