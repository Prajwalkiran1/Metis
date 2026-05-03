"""baseline schema for module 1 (users + auth)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03

Tables: colleges, users, roles, permissions, role_permissions, auth_sessions,
user_invites, password_reset_tokens, consents, audit_logs, login_attempts.

Every table that has `updated_at` gets a `set_updated_at` BEFORE UPDATE trigger
(the function is created in revision 0001).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


# Tables that get the set_updated_at trigger (have an updated_at column).
TRIGGERED_TABLES = (
    "colleges",
    "users",
    "roles",
    "permissions",
    "auth_sessions",
    "user_invites",
    "password_reset_tokens",
    "consents",
)


def _attach_updated_at_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER set_{table}_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def _drop_updated_at_trigger(table: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS set_{table}_updated_at ON {table};")


def upgrade() -> None:
    # ── enums ────────────────────────────────────────────────────────────────
    user_role = postgresql.ENUM("student", "teacher", "admin", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)

    user_status = postgresql.ENUM(
        "invited", "active", "suspended", "deleted", name="user_status"
    )
    user_status.create(op.get_bind(), checkfirst=True)

    consent_purpose = postgresql.ENUM(
        "face_enrollment", "face_attendance", "marketing", name="consent_purpose"
    )
    consent_purpose.create(op.get_bind(), checkfirst=True)

    # ── colleges ─────────────────────────────────────────────────────────────
    op.create_table(
        "colleges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("dpdp_data_fiduciary_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_colleges_code"),
    )

    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="user_status", create_type=False),
            nullable=False,
            server_default=sa.text("'invited'"),
        ),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("usn", sa.String(40), nullable=True),
        sa.Column("dob", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_photo_url", sa.Text, nullable=True),
        sa.Column("face_embedding_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("face_key_version", sa.SmallInteger, nullable=True),
        sa.Column("face_enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(email) > 3", name="ck_users_email_min_length"),
    )
    op.create_index("ix_users_college_id", "users", ["college_id"])
    op.create_index("ix_users_usn", "users", ["usn"])
    op.create_index(
        "ix_users_college_role_status", "users", ["college_id", "role", "status"]
    )
    op.create_index(
        "uq_users_college_email_active",
        "users",
        ["college_id", "email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── roles + permissions + role_permissions ───────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_permissions_name"),
    )

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.Integer,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            sa.Integer,
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ── auth_sessions ────────────────────────────────────────────────────────
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.String(128), nullable=False),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"
        ),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    # ── user_invites ─────────────────────────────────────────────────────────
    op.create_table(
        "user_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("otp_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_invites_college_id", "user_invites", ["college_id"])
    op.create_index(
        "uq_user_invites_college_email_active",
        "user_invites",
        ["college_id", "email"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )

    # ── password_reset_tokens ────────────────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("otp_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )

    # ── consents ─────────────────────────────────────────────────────────────
    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purpose",
            postgresql.ENUM(name="consent_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("consent_text_version", sa.String(40), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"])
    op.create_index("ix_consents_user_purpose", "consents", ["user_id", "purpose"])

    # ── audit_logs (append-only) ─────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=True),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_college_id", "audit_logs", ["college_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "ix_audit_logs_college_created", "audit_logs", ["college_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_college_actor", "audit_logs", ["college_id", "actor_user_id"]
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    # ── login_attempts (append-only) ─────────────────────────────────────────
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=True,
        ),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("failure_reason", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_email", "login_attempts", ["email"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])

    # ── attach updated_at triggers ───────────────────────────────────────────
    for table in TRIGGERED_TABLES:
        _attach_updated_at_trigger(table)


def downgrade() -> None:
    for table in TRIGGERED_TABLES:
        _drop_updated_at_trigger(table)

    op.drop_table("login_attempts")
    op.drop_table("audit_logs")
    op.drop_table("consents")
    op.drop_table("password_reset_tokens")
    op.drop_table("user_invites")
    op.drop_table("auth_sessions")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("colleges")

    postgresql.ENUM(name="consent_purpose").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
