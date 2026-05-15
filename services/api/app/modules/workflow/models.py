"""SQLAlchemy ORM models for M10 (academic workflow).

M10a covers semester setup + self-publish: SemesterSetup, ElectiveGroup,
ElectiveGroupOption, AdminNotification.

M10b adds the registration window (cols on SemesterSetup) plus the
cascade-target tables: CourseRegistration, LabBatch, LabBatchMember,
AcademicOverride.

The remaining tables (lab_batch_assignments, internal_deadlines,
cie_schedule, tasks, hall_tickets, grade_cards, see_results,
re_evaluations) get ORM in their respective M10 sub-sessions.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid, utcnow


class SemesterSetupState(str, enum.Enum):
    draft = "draft"
    published = "published"
    active = "active"
    archived = "archived"


class OverrideType(str, enum.Enum):
    """Mirrors the override_type Postgres enum (migration 0007). Only the
    members that M10 actually writes are listed here; the rest become
    relevant when M3/M4 rework lands.
    """

    attendance_condonation = "attendance_condonation"
    eligibility_override = "eligibility_override"
    mark_lock_unlock = "mark_lock_unlock"
    student_migration = "student_migration"
    lab_batch_reassignment = "lab_batch_reassignment"
    assessment_scheme_unlock = "assessment_scheme_unlock"
    see_marks_correction = "see_marks_correction"
    makeup_cie_authorization = "makeup_cie_authorization"


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
    # M10b — HOD-controlled registration window. The "open" predicate is
    # state in (published, active) AND now() between these two; CHECK
    # constraint at the DB level keeps closes_at > opens_at when both set.
    registration_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    # M10b — per-option hard cap (capacity). NULL = uncapped. Group-level
    # max_enrollment stays as a soft total; the cascade respects the
    # per-option value when set.
    max_enrollment: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


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
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
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


# ── course_registrations (M10b — student elective + backlog state) ──────────
class CourseRegistration(Base, TimestampedMixin, SoftDeleteMixin):
    """A student's registered course for a semester setup.

    M10b only writes elective rows (one per elective group per student).
    Mandatory courses are surfaced in the registration UI by reading
    setup.courses minus the courses appearing in elective_group_options;
    they do NOT get a course_registrations row until a future cleanup
    (M9 reports want a single audit-friendly source, but that's deferred).

    Status values: pending | approved | migrated | cancelled | backlog.
    """

    __tablename__ = "course_registrations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    semester_setup_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("semester_setups.id"), nullable=False
    )
    elective_group_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_groups.id"), nullable=True
    )
    elective_group_option_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_group_options.id"), nullable=True
    )
    course_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="approved"
    )
    is_backlog: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backlog_source_term_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=True
    )


# ── course_registration_preferences (audit Session 4 — ranked prefs) ────────
class CourseRegistrationPreference(Base, TimestampedMixin, SoftDeleteMixin):
    """A student's ranked preference (1st/2nd/3rd) for an elective option.

    Sibling of CourseRegistration: the latter is the committed seat, this
    table is the intent / fallback chain. On dissolution, the cascade reads
    these rows in rank order to decide where each affected student lands.

    Invariants (enforced by partial unique indexes from migration 0014):
      - rank 1..3 unique within (student, semester_setup, elective_group)
      - the same option cannot appear at two ranks within one group
    """

    __tablename__ = "course_registration_preferences"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    semester_setup_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("semester_setups.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    elective_group_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_groups.id"), nullable=False
    )
    elective_group_option_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("elective_group_options.id"), nullable=False
    )
    preference_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)


# ── lab_batches + lab_batch_members (the cascade touches the member rows) ──
class LabBatch(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "lab_batches"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sections.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class LabBatchMember(Base):
    """Append-only with a soft `removed_at`. The cascade marks
    `removed_at=NOW()` and `removed_reason='migrated_to_other_offering'`
    instead of deleting, so M3/M4 history calculations still see the
    student in the old batch for the window they were there.
    """

    __tablename__ = "lab_batch_members"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    lab_batch_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_batches.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── internal_deadlines (M10d) ──────────────────────────────────────────────
class DeadlineKind(str, enum.Enum):
    """Mirrors the kind VARCHAR(20) on internal_deadlines.

    institutional_hard   admin owns; one row per (college, term, NULL dept, NULL offering)
    department_soft      HOD owns; one row per (college, term, dept, NULL offering)
    per_course_freeze    teacher owns own offering; one row per (term, dept, offering)
    """

    institutional_hard = "institutional_hard"
    department_soft = "department_soft"
    per_course_freeze = "per_course_freeze"


class InternalDeadline(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "internal_deadlines"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    academic_term_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=False
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    course_offering_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=True
    )
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    set_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    is_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frozen_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── cie_schedule (M10d) ────────────────────────────────────────────────────
class CIESchedule(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "cie_schedule"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    cie_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=60
    )
    room_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── tasks (M10d) ───────────────────────────────────────────────────────────
class TaskType(str, enum.Enum):
    invigilation = "invigilation"
    paper_setting = "paper_setting"
    evaluation = "evaluation"
    makeup_exam = "makeup_exam"
    other = "other"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    completed = "completed"
    cancelled = "cancelled"


# ── M10e: hall_tickets + versions ──────────────────────────────────────────
class HallTicket(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "hall_tickets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    academic_term_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    current_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("hall_ticket_versions.id", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class HallTicketVersion(Base):
    __tablename__ = "hall_ticket_versions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    hall_ticket_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hall_tickets.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    generated_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


# ── M10e: grade_cards + versions ───────────────────────────────────────────
class GradeCard(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "grade_cards"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    academic_term_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=False
    )
    current_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("grade_card_versions.id", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    is_finalised: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GradeCardVersion(Base):
    __tablename__ = "grade_card_versions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    grade_card_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("grade_cards.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    grades_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    generated_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    trigger_reason: Mapped[str] = mapped_column(String(50), nullable=False)


# ── M10e: see_results + re_evaluations ─────────────────────────────────────
class SEEResultKind(str, enum.Enum):
    original = "original"
    re_evaluation = "re_evaluation"
    makeup = "makeup"


class SEEResult(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "see_results"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id"), nullable=False
    )
    kind: Mapped[SEEResultKind] = mapped_column(
        Enum(
            SEEResultKind,
            name="see_result_kind",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    marks_obtained: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    csv_upload_batch_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("see_results.id"), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReEvaluation(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "re_evaluations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id"), nullable=False
    )
    requested_by_student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    request_window_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="requested"
    )
    original_see_result_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("see_results.id"), nullable=False
    )
    revised_see_result_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("see_results.id"), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class Task(Base, TimestampedMixin, SoftDeleteMixin):
    """A task header — what's being asked + by whom + when due. Per-
    assignee execution state lives in TaskAssignment rows; one task
    can have N assignees (paper-setting committee, multi-invigilator
    CIE, etc.)."""

    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    assigned_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(
            TaskType,
            name="task_type",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    related_entity_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskAssignment(Base, TimestampedMixin, SoftDeleteMixin):
    """One row per assignee on a task. State machine matches the v1
    Task: pending → accepted/declined/cancelled, accepted → completed.
    The (task_id, assignee_user_id) WHERE deleted_at IS NULL partial
    unique index ensures only one active assignment per pair."""

    __tablename__ = "task_assignments"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    assignee_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default=TaskStatus.pending,
    )
    status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── lab_batch_assignments (M10c — batch incharges + co-evaluators) ─────────
class LabBatchAssignment(Base):
    """One row per teacher↔batch role binding. Append-only: a fresh row
    represents a new assignment, and removing one sets `unassigned_at`
    plus a reason. The partial unique index pins one active row per
    (batch, teacher, role); the service relies on it to enforce the
    one-incharge-per-batch invariant atomically.
    """

    __tablename__ = "lab_batch_assignments"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    lab_batch_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_batches.id"), nullable=False
    )
    teacher_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="batch_incharge"
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unassigned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── academic_overrides (append-only typed audit of HOD/admin overrides) ────
class AcademicOverride(Base):
    """One row per privileged academic override. Append-only — never
    updated, never soft-deleted. M9 admin analytics reads this table.

    M10b writes `student_migration` rows; M3/M4 rework will start writing
    the rest (attendance_condonation, mark_lock_unlock, etc.).
    """

    __tablename__ = "academic_overrides"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False
    )
    override_type: Mapped[OverrideType] = mapped_column(
        Enum(
            OverrideType,
            name="override_type",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    target_student_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    target_course_offering_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=True
    )
    target_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_entity_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
