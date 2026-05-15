"""SQLAlchemy ORM models for M2 (academic service).

All M2 tables live here: departments, courses, batches, sections, rooms,
course_offerings, timetable_slots, timetable_exceptions, academic_calendar,
enrollments.

Tenant isolation: every table has `college_id` (FK to colleges from M1).
Soft delete (`deleted_at`) on user-facing entities; `enrollments` is
append-mostly so it tracks withdrawal time instead.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid


# ── Enums ────────────────────────────────────────────────────────────────────
class CourseType(str, enum.Enum):
    # M2 rework: BMSCE-aligned values. Old core/elective rows are remapped
    # to 'theory' in migration 0007.
    theory = "theory"
    lab = "lab"
    integrated = "integrated"
    nptel = "nptel"


class RoomType(str, enum.Enum):
    lecture = "lecture"
    lab = "lab"
    seminar = "seminar"
    online = "online"


class TimetableExceptionKind(str, enum.Enum):
    cancel = "cancel"
    reschedule = "reschedule"
    room_change = "room_change"
    extra = "extra"


class AcademicCalendarKind(str, enum.Enum):
    holiday = "holiday"
    exam = "exam"
    event = "event"
    term_start = "term_start"
    term_end = "term_end"


class TermType(str, enum.Enum):
    regular = "regular"
    fast_track = "fast_track"


class AssessmentComponentKind(str, enum.Enum):
    cie = "cie"
    aat = "aat"
    lab = "lab"
    assignment = "assignment"
    see = "see"
    nptel_assignment = "nptel_assignment"
    nptel_final = "nptel_final"


# ── departments ──────────────────────────────────────────────────────────────
class Department(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    head_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_departments_college_code_active",
            "college_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── courses ──────────────────────────────────────────────────────────────────
class Course(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "courses"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    credits: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    course_type: Mapped[CourseType] = mapped_column(
        Enum(CourseType, name="course_type", native_enum=True),
        nullable=False,
        default=CourseType.theory,
    )

    __table_args__ = (
        CheckConstraint("semester BETWEEN 1 AND 12", name="semester_range"),
        CheckConstraint("credits BETWEEN 0 AND 12", name="credits_range"),
        Index(
            "uq_courses_college_code_active",
            "college_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_courses_department_semester", "department_id", "semester"),
    )


# ── batches ──────────────────────────────────────────────────────────────────
class Batch(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "batches"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    program_duration_years: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=4
    )
    current_semester: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("current_semester BETWEEN 1 AND 12", name="current_semester_range"),
        CheckConstraint("admission_year BETWEEN 1900 AND 2100", name="admission_year_range"),
        Index(
            "uq_batches_college_dept_year_active",
            "college_id",
            "department_id",
            "admission_year",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── sections ─────────────────────────────────────────────────────────────────
class Section(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "sections"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    batch_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("batches.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(10), nullable=False)
    class_teacher_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_sections_batch_name_active",
            "batch_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_sections_class_teacher", "class_teacher_user_id"),
    )


# ── rooms ────────────────────────────────────────────────────────────────────
class Room(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "rooms"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    building: Mapped[str | None] = mapped_column(String(80), nullable=True)
    floor: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    capacity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, name="room_type", native_enum=True),
        nullable=False,
        default=RoomType.lecture,
    )
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_radius_m: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)

    __table_args__ = (
        CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)", name="lat_lon_both_or_neither"
        ),
        CheckConstraint("gps_radius_m BETWEEN 10 AND 1000", name="gps_radius_range"),
        Index(
            "uq_rooms_college_code_active",
            "college_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── course_offerings ─────────────────────────────────────────────────────────
class CourseOffering(Base, TimestampedMixin, SoftDeleteMixin):
    """A teacher's binding to teach a course to a section in a term.

    Mutate by soft-delete + new row, not in place — M4 marks will FK this and
    rewriting the teacher silently rewrites every historical assessment.
    """

    __tablename__ = "course_offerings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sections.id"), nullable=False
    )
    teacher_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    academic_term: Mapped[str] = mapped_column(String(20), nullable=False)
    academic_term_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("academic_terms.id"), nullable=True
    )
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # M2 rework — integrated theory↔lab pairing + per-offering assessment scheme.
    parent_offering_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=True
    )
    assessment_scheme_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("assessment_schemes.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_offerings_section_course_term_active",
            "section_id",
            "course_id",
            "academic_term",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_offerings_teacher_term", "teacher_user_id", "academic_term"),
        Index("ix_offerings_section_term", "section_id", "academic_term"),
        Index("ix_offerings_course_term", "course_id", "academic_term"),
    )


# ── timetable_slots ──────────────────────────────────────────────────────────
class TimetableSlot(Base, TimestampedMixin, SoftDeleteMixin):
    """One weekly recurrence rule. Materialised dates = expand
    [effective_from..effective_until] on `day_of_week`, then subtract calendar
    holidays and apply timetable_exceptions.
    """

    __tablename__ = "timetable_slots"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    room_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="end_after_start"),
        CheckConstraint(
            "effective_until >= effective_from", name="effective_until_after_from"
        ),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week_range"),
        Index(
            "ix_slots_room_day",
            "room_id",
            "day_of_week",
            postgresql_where=text("deleted_at IS NULL AND room_id IS NOT NULL"),
        ),
        Index(
            "ix_slots_offering_day",
            "course_offering_id",
            "day_of_week",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_slots_college_dow", "college_id", "day_of_week"),
    )


# ── timetable_exceptions ─────────────────────────────────────────────────────
class TimetableException(Base, TimestampedMixin):
    """One-off deviation from the recurring schedule.

    `kind=cancel`:       drops a single occurrence
    `kind=reschedule`:   moves time on a specific date
    `kind=room_change`:  swaps room on a specific date
    `kind=extra`:        a non-recurring extra class (no parent slot)
    """

    __tablename__ = "timetable_exceptions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    original_slot_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("timetable_slots.id"), nullable=True
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[TimetableExceptionKind] = mapped_column(
        Enum(TimetableExceptionKind, name="timetable_exception_kind", native_enum=True),
        nullable=False,
    )
    new_room_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True
    )
    new_start_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    new_end_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(kind <> 'cancel') OR "
            "(new_room_id IS NULL AND new_start_time IS NULL AND new_end_time IS NULL)",
            name="cancel_has_no_overrides",
        ),
        CheckConstraint(
            "(kind <> 'reschedule') OR "
            "(new_start_time IS NOT NULL AND new_end_time IS NOT NULL)",
            name="reschedule_has_times",
        ),
        CheckConstraint(
            "(kind <> 'room_change') OR (new_room_id IS NOT NULL)",
            name="room_change_has_room",
        ),
        CheckConstraint(
            "(kind <> 'extra') OR "
            "(original_slot_id IS NULL AND new_start_time IS NOT NULL "
            "AND new_end_time IS NOT NULL)",
            name="extra_has_no_parent_and_has_times",
        ),
        CheckConstraint(
            "new_end_time IS NULL OR new_start_time IS NULL "
            "OR new_end_time > new_start_time",
            name="new_end_after_new_start",
        ),
        Index(
            "uq_exceptions_slot_date",
            "original_slot_id",
            "exception_date",
            unique=True,
            postgresql_where=text("original_slot_id IS NOT NULL"),
        ),
        Index("ix_exceptions_date", "exception_date"),
        Index("ix_exceptions_offering_date", "course_offering_id", "exception_date"),
    )


# ── academic_calendar ────────────────────────────────────────────────────────
class AcademicCalendarEntry(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "academic_calendar"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[AcademicCalendarKind] = mapped_column(
        Enum(AcademicCalendarKind, name="academic_calendar_kind", native_enum=True),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    applies_to_department_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    cancels_classes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_calendar_college_date", "college_id", "entry_date"),
    )


# ── enrollments (student ↔ section) ──────────────────────────────────────────
class Enrollment(Base):
    """Append-mostly. Withdrawals set `withdrawn_at` rather than deleting."""

    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sections.id"), nullable=False
    )
    academic_term: Mapped[str] = mapped_column(String(20), nullable=False)
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_enrollments_student_section_term_active",
            "student_user_id",
            "section_id",
            "academic_term",
            unique=True,
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
        Index(
            "ix_enrollments_section_active",
            "section_id",
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
        Index("ix_enrollments_student_term", "student_user_id", "academic_term"),
    )


# ── academic_terms (M2 rework — canonical term entity) ──────────────────────
class AcademicTerm(Base, TimestampedMixin, SoftDeleteMixin):
    """Canonical academic term. Legacy VARCHAR `academic_term` columns on
    course_offerings and enrollments still live, but new code should join
    by `academic_term_id` against this table.
    """

    __tablename__ = "academic_terms"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    term_type: Mapped[TermType] = mapped_column(
        Enum(TermType, name="term_type", native_enum=True, create_type=False),
        nullable=False,
        default=TermType.regular,
    )
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_academic_terms_college_code_active",
            "college_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── assessment_scheme_templates (institutional/dept catalog) ────────────────
class AssessmentSchemeTemplate(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "assessment_scheme_templates"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    owner_department_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    applies_to_course_type: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_rules: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    default_components: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ── assessment_schemes (per-offering instance) ───────────────────────────────
class AssessmentScheme(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "assessment_schemes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False
    )
    template_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("assessment_scheme_templates.id"), nullable=True
    )
    configured_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_reason: Mapped[str | None] = mapped_column(String, nullable=True)


# ── assessment_scheme_components (rows under a scheme) ───────────────────────
class AssessmentSchemeComponent(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "assessment_scheme_components"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    assessment_scheme_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("assessment_schemes.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[AssessmentComponentKind] = mapped_column(
        Enum(
            AssessmentComponentKind,
            name="assessment_component_kind",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_dropped_in_best_of: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
