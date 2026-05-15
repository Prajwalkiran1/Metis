"""Request/response schemas for the academic module."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.academic.models import (
    AcademicCalendarKind,
    CourseType,
    RoomType,
    TimetableExceptionKind,
)


# ── Pagination ──────────────────────────────────────────────────────────────
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


# ── Departments ─────────────────────────────────────────────────────────────
class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    name: str
    code: str
    head_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    head_user_id: UUID | None = None


class DepartmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    head_user_id: UUID | None = None


# ── Courses ─────────────────────────────────────────────────────────────────
class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    department_id: UUID
    code: str
    title: str
    credits: int
    semester: int
    course_type: CourseType
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CourseCreate(BaseModel):
    department_id: UUID
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    credits: int = Field(ge=0, le=12, default=3)
    semester: int = Field(ge=1, le=12)
    course_type: CourseType = CourseType.theory


class CoursePatch(BaseModel):
    department_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    credits: int | None = Field(default=None, ge=0, le=12)
    semester: int | None = Field(default=None, ge=1, le=12)
    course_type: CourseType | None = None


# ── Batches ─────────────────────────────────────────────────────────────────
class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    department_id: UUID
    name: str
    admission_year: int
    program_duration_years: int
    current_semester: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class BatchCreate(BaseModel):
    department_id: UUID
    name: str = Field(min_length=1, max_length=80)
    admission_year: int = Field(ge=1900, le=2100)
    program_duration_years: int = Field(ge=1, le=8, default=4)
    current_semester: int = Field(ge=1, le=12, default=1)


class BatchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    current_semester: int | None = Field(default=None, ge=1, le=12)


# ── Sections ────────────────────────────────────────────────────────────────
class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    batch_id: UUID
    name: str
    class_teacher_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class SectionCreate(BaseModel):
    batch_id: UUID
    name: str = Field(min_length=1, max_length=10)
    class_teacher_user_id: UUID | None = None


class SectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=10)
    class_teacher_user_id: UUID | None = None


# ── Enrollments ─────────────────────────────────────────────────────────────
class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    college_id: UUID
    student_user_id: UUID
    section_id: UUID
    academic_term: str
    semester: int
    enrolled_at: datetime
    withdrawn_at: datetime | None = None


class EnrollmentsCreate(BaseModel):
    student_user_ids: list[UUID] = Field(min_length=1)
    academic_term: str = Field(min_length=1, max_length=20)
    semester: int = Field(ge=1, le=12)


# ── Rooms ───────────────────────────────────────────────────────────────────
class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    code: str
    building: str | None = None
    floor: int | None = None
    capacity: int | None = None
    room_type: RoomType
    lat: Decimal | None = None
    lon: Decimal | None = None
    gps_radius_m: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class RoomCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    building: str | None = Field(default=None, max_length=80)
    floor: int | None = Field(default=None, ge=-5, le=99)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    room_type: RoomType = RoomType.lecture
    lat: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    lon: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    gps_radius_m: int = Field(ge=10, le=1000, default=100)


class RoomPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    building: str | None = Field(default=None, max_length=80)
    floor: int | None = Field(default=None, ge=-5, le=99)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    room_type: RoomType | None = None
    lat: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    lon: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    gps_radius_m: int | None = Field(default=None, ge=10, le=1000)


# ── Course offerings ────────────────────────────────────────────────────────
class CourseOfferingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    course_id: UUID
    section_id: UUID
    teacher_user_id: UUID
    academic_term: str
    semester: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CourseOfferingCreate(BaseModel):
    course_id: UUID
    section_id: UUID
    teacher_user_id: UUID
    academic_term: str = Field(min_length=1, max_length=20)
    semester: int = Field(ge=1, le=12)


class CourseOfferingPatch(BaseModel):
    is_active: bool | None = None


# ── Timetable slots ─────────────────────────────────────────────────────────
class TimetableSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    course_offering_id: UUID
    room_id: UUID | None = None
    day_of_week: int
    start_time: time
    end_time: time
    effective_from: date
    effective_until: date
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TimetableSlotCreate(BaseModel):
    course_offering_id: UUID
    room_id: UUID | None = None
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    effective_from: date
    effective_until: date


class TimetableSlotPatch(BaseModel):
    room_id: UUID | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    effective_from: date | None = None
    effective_until: date | None = None


# ── Conflict detection ──────────────────────────────────────────────────────
class ConflictCheckRequest(BaseModel):
    """Caller can omit teacher/section IDs to skip those checks."""

    room_id: UUID | None = None
    teacher_user_id: UUID | None = None
    section_id: UUID | None = None
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    effective_from: date
    effective_until: date
    exclude_slot_id: UUID | None = None


class ConflictItem(BaseModel):
    type: str  # "room" | "teacher" | "section"
    slot_id: UUID
    course_offering_id: UUID
    reason: str


class ConflictCheckResponse(BaseModel):
    has_conflicts: bool
    conflicts: list[ConflictItem]


# ── Timetable exceptions ────────────────────────────────────────────────────
class TimetableExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    course_offering_id: UUID
    original_slot_id: UUID | None = None
    exception_date: date
    kind: TimetableExceptionKind
    new_room_id: UUID | None = None
    new_start_time: time | None = None
    new_end_time: time | None = None
    reason: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class TimetableExceptionCreate(BaseModel):
    course_offering_id: UUID
    exception_date: date
    kind: TimetableExceptionKind
    new_room_id: UUID | None = None
    new_start_time: time | None = None
    new_end_time: time | None = None
    reason: str | None = Field(default=None, max_length=200)


# ── Teacher/HOD-scoped ad-hoc class session payloads ────────────────────────
class AdHocExtraCreate(BaseModel):
    """An extra one-off class with no parent recurring slot."""

    exception_date: date
    new_start_time: time
    new_end_time: time
    new_room_id: UUID
    reason: str | None = Field(default=None, max_length=200)


class AdHocRescheduleCreate(BaseModel):
    """A recurring slot's occurrence moved to a different time on a given date.
    The room can optionally change as part of the same reschedule."""

    exception_date: date
    new_start_time: time
    new_end_time: time
    new_room_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=200)


class AdHocRoomChangeCreate(BaseModel):
    """A recurring slot's room swapped on a single date; times unchanged."""

    exception_date: date
    new_room_id: UUID
    reason: str | None = Field(default=None, max_length=200)


# ── Academic calendar ───────────────────────────────────────────────────────
class CalendarEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    entry_date: date
    kind: AcademicCalendarKind
    title: str
    applies_to_department_id: UUID | None = None
    cancels_classes: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CalendarEntryCreate(BaseModel):
    entry_date: date
    kind: AcademicCalendarKind
    title: str = Field(min_length=1, max_length=200)
    applies_to_department_id: UUID | None = None
    cancels_classes: bool = True


class CalendarEntryPatch(BaseModel):
    entry_date: date | None = None
    kind: AcademicCalendarKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    applies_to_department_id: UUID | None = None
    cancels_classes: bool | None = None


# ── Composite views ─────────────────────────────────────────────────────────
class TimetableView(BaseModel):
    """Weekly view for a section: base slots + active exceptions in a date window."""

    section_id: UUID
    slots: list[TimetableSlotOut]
    exceptions: list[TimetableExceptionOut]
