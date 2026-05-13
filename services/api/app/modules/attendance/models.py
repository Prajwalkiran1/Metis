"""SQLAlchemy ORM models for M3 (attendance service).

Five tables: class_sessions, qr_tokens, attendance_records, device_logs,
attendance_overrides. All tenant-scoped on `college_id`.

State machines:
- class_sessions.state:        pending → open → closed
- attendance_records.state:    submitted → verified → recorded
                                         ↘ flagged → (override) → recorded

`updated_at` only on the two tables that mutate after insert; the rest
are append-only.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid


# ── Enums ────────────────────────────────────────────────────────────────────
class ClassSessionState(str, enum.Enum):
    pending = "pending"
    open = "open"
    closed = "closed"


class ClassSessionSource(str, enum.Enum):
    materialised = "materialised"
    extra = "extra"
    on_demand = "on_demand"


class AttendanceRecordState(str, enum.Enum):
    submitted = "submitted"
    verified = "verified"
    recorded = "recorded"
    flagged = "flagged"


# ── class_sessions ───────────────────────────────────────────────────────────
class ClassSession(Base, TimestampedMixin, SoftDeleteMixin):
    """A concrete instance of a timetable slot on a specific date.

    Materialised idempotently from `timetable_slots` minus
    `academic_calendar` holidays and `timetable_exceptions`, plus
    `kind='extra'` exception rows. The partial unique on
    `(course_offering_id, scheduled_date, start_time) WHERE deleted_at
    IS NULL` enforces the idempotency: re-running the materialiser
    upserts existing rows instead of inserting duplicates.
    """

    __tablename__ = "class_sessions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    room_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    state: Mapped[ClassSessionState] = mapped_column(
        Enum(ClassSessionState, name="class_session_state", native_enum=True),
        nullable=False,
        default=ClassSessionState.pending,
    )
    source: Mapped[ClassSessionSource] = mapped_column(
        Enum(ClassSessionSource, name="class_session_source", native_enum=True),
        nullable=False,
        default=ClassSessionSource.materialised,
    )
    origin_slot_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("timetable_slots.id"), nullable=True
    )
    origin_exception_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("timetable_exceptions.id"), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "end_time > start_time", name="end_after_start"
        ),
        Index(
            "ix_class_sessions_offering_date",
            "course_offering_id",
            "scheduled_date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_class_sessions_college_date",
            "college_id",
            "scheduled_date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_class_sessions_offering_date_start_active",
            "course_offering_id",
            "scheduled_date",
            "start_time",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── qr_tokens ────────────────────────────────────────────────────────────────
class QRToken(Base):
    """Issued QR tokens. The JWT itself is what the client scans; this row
    exists so we can (a) revoke tokens before exp, (b) audit which jti a
    student submitted, and (c) have an explicit DB-level anti-replay check
    in addition to the JWT signature."""

    __tablename__ = "qr_tokens"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    class_session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    jti: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, unique=True
    )
    centroid_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    centroid_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    issued_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "valid_until > valid_from", name="valid_window"
        ),
        CheckConstraint(
            "(centroid_lat IS NULL) = (centroid_lon IS NULL)",
            name="centroid_both_or_neither",
        ),
        Index(
            "ix_qr_tokens_session_valid",
            "class_session_id",
            "valid_until",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


# ── device_logs ──────────────────────────────────────────────────────────────
class DeviceLog(Base):
    """One row per (session, device) — the anti-replay guard for the
    'same student submits twice from the same phone' case AND the
    'one student lends their phone to another' case."""

    __tablename__ = "device_logs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    class_session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    submitted_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    device_fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_device_logs_session_fingerprint",
            "class_session_id",
            "device_fingerprint_hash",
            unique=True,
        ),
    )


# ── attendance_records ───────────────────────────────────────────────────────
class AttendanceRecord(Base, TimestampedMixin):
    __tablename__ = "attendance_records"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    class_session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    state: Mapped[AttendanceRecordState] = mapped_column(
        Enum(
            AttendanceRecordState,
            name="attendance_record_state",
            native_enum=True,
        ),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    flagged_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gps_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    face_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    qr_token_jti: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    device_log_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("device_logs.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "face_confidence BETWEEN 0 AND 1",
            name="face_conf_range",
        ),
        CheckConstraint(
            "(gps_lat IS NULL) = (gps_lon IS NULL)",
            name="gps_both_or_neither",
        ),
        Index(
            "uq_attendance_records_session_student",
            "class_session_id",
            "student_user_id",
            unique=True,
        ),
        Index(
            "ix_attendance_records_student_session",
            "student_user_id",
            "class_session_id",
        ),
    )


# ── attendance_overrides ─────────────────────────────────────────────────────
class AttendanceOverride(Base):
    """Append-only audit trail for teacher overrides. The actual mutation
    happens on the linked `AttendanceRecord` row; this table records the
    who/why/when. `from_state` is NULL when the override creates a record
    that didn't exist (e.g., teacher marking a student present manually)."""

    __tablename__ = "attendance_overrides"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    class_session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("class_sessions.id"), nullable=False
    )
    attendance_record_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("attendance_records.id"), nullable=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_state: Mapped[AttendanceRecordState | None] = mapped_column(
        Enum(
            AttendanceRecordState,
            name="attendance_record_state",
            native_enum=True,
            create_type=False,
        ),
        nullable=True,
    )
    to_state: Mapped[AttendanceRecordState] = mapped_column(
        Enum(
            AttendanceRecordState,
            name="attendance_record_state",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    overridden_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_attendance_overrides_session", "class_session_id"
        ),
        Index(
            "ix_attendance_overrides_record", "attendance_record_id"
        ),
    )
