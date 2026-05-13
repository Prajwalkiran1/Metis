"""SQLAlchemy ORM models for M1 (users + auth).

All M1 tables live here so the model registry has a single import point.
Schema additions for later modules go in their own module's `models.py`.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid

if TYPE_CHECKING:
    pass


# ── Enums ────────────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"
    parent = "parent"


class UserStatus(str, enum.Enum):
    invited = "invited"
    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class ConsentPurpose(str, enum.Enum):
    face_enrollment = "face_enrollment"
    face_attendance = "face_attendance"
    marketing = "marketing"


# ── Tables ───────────────────────────────────────────────────────────────────
class College(Base, TimestampedMixin):
    __tablename__ = "colleges"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    dpdp_data_fiduciary_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Exact-match-only domain check. Sub-domains do not count: a user with
    # 'foo@student.bmsce.ac.in' is rejected when email_domain='bmsce.ac.in'.
    email_domain: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default=text("'bmsce.ac.in'")
    )


class User(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True), nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        default=UserStatus.invited,
        server_default=text("'invited'"),
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Google OAuth subject (`sub` claim). Bound on first successful Google
    # sign-in if NULL; subsequent logins must match this exact value so a
    # Metis account can't be silently hijacked by re-using the same email
    # on a different Google account.
    google_sub: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    usn: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    dob: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    face_embedding_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    face_key_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    face_enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    college: Mapped[College] = relationship("College", lazy="joined")

    __table_args__ = (
        # Active users: email is unique within a college. Soft-deleted rows are excluded
        # so the address can be recycled if a user is fully removed.
        Index(
            "uq_users_college_email_active",
            "college_id",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_college_role_status", "college_id", "role", "status"),
        CheckConstraint("char_length(email) > 3", name="email_min_length"),
    )


class Role(Base, TimestampedMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Permission(Base, TimestampedMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class AuthSession(Base, TimestampedMixin):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserInvite(Base, TimestampedMixin):
    __tablename__ = "user_invites"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True, create_type=False), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_user_invites_college_email_active",
            "college_id",
            "email",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
    )


class PasswordResetToken(Base, TimestampedMixin):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Consent(Base, TimestampedMixin):
    __tablename__ = "consents"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[ConsentPurpose] = mapped_column(
        Enum(ConsentPurpose, name="consent_purpose", native_enum=True), nullable=False
    )
    consent_text_version: Mapped[str] = mapped_column(String(40), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    __table_args__ = (
        Index("ix_consents_user_purpose", "user_id", "purpose"),
    )


class AuditLog(Base):
    """Append-only log. No `updated_at`; rows are immutable once written."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    college_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=True, index=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_college_created", "college_id", "created_at"),
        Index("ix_audit_logs_college_actor", "college_id", "actor_user_id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )


class LoginAttempt(Base):
    """Persisted login-attempt audit. Lockout itself runs through Redis (TTL)."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    college_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
