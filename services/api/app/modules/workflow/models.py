"""SQLAlchemy ORM models for M10 (academic workflow).

M10a covers semester setup + self-publish (this file): SemesterSetup,
ElectiveGroup, ElectiveGroupOption, AdminNotification. The remaining
tables (course_registrations, lab_batches, internal_deadlines, etc.)
get ORM in their respective M10 sub-sessions.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid


class SemesterSetupState(str, enum.Enum):
    draft = "draft"
    published = "published"
    active = "active"
    archived = "archived"


class SemesterSetup(Base, TimestampedMixin, SoftDeleteMixin):
    """An HOD-drafted, HOD-published structure for one (department, term).

    State machine: draft → published → active → archived. Publish flips
    the row from `draft` to `published` and immediately to `active` (the
    term is already running by the time the HOD publishes); both
    timestamps are recorded.
    """

    __tablename__ = "semester_setups"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    academic_term_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=False
    )
    state: Mapped[SemesterSetupState] = mapped_column(
        Enum(
            SemesterSetupState,
            name="semester_setup_state",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default=SemesterSetupState.draft,
    )
    drafted_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index(
            "uq_semester_setups_dept_term_active",
            "college_id",
            "department_id",
            "academic_term_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_semester_setups_state",
            "state",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ElectiveGroup(Base, TimestampedMixin, SoftDeleteMixin):
    """A choose-one bucket within a semester setup.

    Strength rules (`min_enrollment_to_run`) and caps (`max_enrollment`)
    are enforced when M10b's registration window closes, not here.
    """

    __tablename__ = "elective_groups"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    semester_setup_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("semester_setups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    required_credits: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    min_enrollment_to_run: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=5
    )
    max_enrollment: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class ElectiveGroupOption(Base, TimestampedMixin, SoftDeleteMixin):
    """One course option inside a group, with a tentative teacher.

    `is_dissolved` flips when an HOD kills the option in M10b for low
    enrollment. The `migrated_to_option_id` self-reference records which
    surviving option absorbed the dissolved one's registrants.
    """

    __tablename__ = "elective_group_options"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    elective_group_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_groups.id"), nullable=False
    )
    course_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), nullable=False
    )
    tentative_teacher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    is_dissolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dissolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dissolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    dissolved_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    migrated_to_option_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_group_options.id"), nullable=True
    )


class AdminNotification(Base):
    """Append-only feed for admin oversight events.

    Currently populated only by `semester_setup.published` (M10a). M5
    comms will add a writer for cross-dept resource conflicts and
    condonation escalations. Mark-as-read flips `read_at` (M5 wires it).
    """

    __tablename__ = "admin_notifications"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_admin_notifications_college_created",
            "college_id",
            "created_at",
        ),
    )
