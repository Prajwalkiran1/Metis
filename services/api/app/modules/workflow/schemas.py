"""Pydantic schemas for the M10 workflow module.

M10a surface: semester setup CRUD, course-assignment-within-setup,
elective groups + options, admin-notifications feed.

M10b surface: registration window, student elective registration, HOD
elective enrollment view, dissolve/preview, manual migrate, capacity
cap with redistribute, blast-radius preview.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.academic.models import CourseType
from app.modules.workflow.models import SemesterSetupState


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


# ── Semester setup ───────────────────────────────────────────────────────────
class SemesterSetupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    department_id: UUID
    academic_term_id: UUID
    state: SemesterSetupState
    drafted_by_user_id: UUID
    published_at: datetime | None = None
    archived_at: datetime | None = None
    notes: str | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SemesterSetupCreate(BaseModel):
    department_id: UUID
    academic_term_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class SemesterSetupPatch(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


# ── Course-within-setup ──────────────────────────────────────────────────────
class CourseAssignmentOut(BaseModel):
    """A course offering attached to a setup, with denormalised display fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    course_code: str
    course_title: str
    course_type: CourseType
    section_id: UUID
    section_name: str
    teacher_user_id: UUID | None = None
    teacher_name: str | None = None
    parent_offering_id: UUID | None = None
    assessment_scheme_id: UUID | None = None
    is_active: bool


class CourseAssignmentCreate(BaseModel):
    course_id: UUID
    section_id: UUID
    teacher_user_id: UUID
    parent_offering_id: UUID | None = None


class CourseAssignmentPatch(BaseModel):
    teacher_user_id: UUID | None = None
    parent_offering_id: UUID | None = None


# ── Elective groups + options ────────────────────────────────────────────────
class ElectiveGroupOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    elective_group_id: UUID
    course_id: UUID
    course_code: str
    course_title: str
    tentative_teacher_id: UUID | None = None
    tentative_teacher_name: str | None = None
    is_dissolved: bool


class ElectiveGroupOptionCreate(BaseModel):
    course_id: UUID
    tentative_teacher_id: UUID | None = None


class ElectiveGroupOptionPatch(BaseModel):
    tentative_teacher_id: UUID | None = None


class ElectiveGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    semester_setup_id: UUID
    name: str
    description: str | None = None
    required_credits: int | None = None
    min_enrollment_to_run: int
    max_enrollment: int | None = None
    options: list[ElectiveGroupOptionOut] = []


class ElectiveGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    required_credits: int | None = Field(default=None, ge=0, le=12)
    min_enrollment_to_run: int = Field(default=5, ge=0, le=500)
    max_enrollment: int | None = Field(default=None, ge=1, le=1000)


class ElectiveGroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    required_credits: int | None = Field(default=None, ge=0, le=12)
    min_enrollment_to_run: int | None = Field(default=None, ge=0, le=500)
    max_enrollment: int | None = Field(default=None, ge=1, le=1000)


# ── Full setup detail ────────────────────────────────────────────────────────
class SemesterSetupDetail(SemesterSetupOut):
    """Shape returned by GET /workflow/semester-setups/{id}."""

    department_name: str
    department_code: str
    academic_term_code: str
    courses: list[CourseAssignmentOut] = []
    elective_groups: list[ElectiveGroupOut] = []


# ── Admin notifications ──────────────────────────────────────────────────────
class AdminNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    event_type: str
    payload: dict
    created_at: datetime
    read_at: datetime | None = None


# ── M10b: registration window ───────────────────────────────────────────────
class RegistrationWindowSet(BaseModel):
    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def _check_order(self) -> "RegistrationWindowSet":
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        return self


# ── M10b: student registration view ─────────────────────────────────────────
class RegistrationOptionView(BaseModel):
    option_id: UUID
    course_id: UUID
    course_code: str
    course_title: str
    course_type: CourseType
    tentative_teacher_id: UUID | None = None
    tentative_teacher_name: str | None = None
    current_enrollment: int
    min_enrollment_to_run: int
    max_enrollment: int | None = None
    is_dissolved: bool
    is_full: bool


class RegistrationGroupView(BaseModel):
    elective_group_id: UUID
    name: str
    description: str | None = None
    required_credits: int | None = None
    options: list[RegistrationOptionView]
    chosen_option_id: UUID | None = None  # the student's current pick, if any


class MandatoryCourseView(BaseModel):
    course_offering_id: UUID
    course_id: UUID
    course_code: str
    course_title: str
    course_type: CourseType
    section_name: str
    teacher_name: str | None = None


class WindowStatus(BaseModel):
    is_open: bool
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    reason: Literal[
        "open",
        "not_yet_open",
        "closed",
        "not_published",
        "no_setup",
        "window_not_set",
    ]


class StudentRegistrationView(BaseModel):
    semester_setup_id: UUID | None = None
    academic_term_code: str | None = None
    department_code: str | None = None
    window: WindowStatus
    mandatory_courses: list[MandatoryCourseView] = []
    groups: list[RegistrationGroupView] = []
    migration_alert: dict | None = None  # set when status='migrated' rows exist


class RegistrationChoice(BaseModel):
    elective_group_id: UUID
    elective_group_option_id: UUID


class StudentRegistrationSubmit(BaseModel):
    choices: list[RegistrationChoice]


class RegistrationRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_user_id: UUID
    semester_setup_id: UUID
    elective_group_id: UUID | None = None
    elective_group_option_id: UUID | None = None
    course_id: UUID
    status: str
    is_backlog: bool
    created_at: datetime
    updated_at: datetime


# ── M10b: HOD elective enrollment view ──────────────────────────────────────
class StudentMini(BaseModel):
    student_user_id: UUID
    usn: str | None = None
    name: str
    registered_at: datetime


class OptionEnrollmentView(BaseModel):
    option_id: UUID
    course_id: UUID
    course_code: str
    course_title: str
    tentative_teacher_id: UUID | None = None
    tentative_teacher_name: str | None = None
    is_dissolved: bool
    current_enrollment: int
    status: Literal["under_subscribed", "over_subscribed", "healthy"]
    students: list[StudentMini]


class ElectiveGroupEnrollmentView(BaseModel):
    elective_group_id: UUID
    semester_setup_id: UUID
    name: str
    min_enrollment_to_run: int
    max_enrollment: int | None = None
    options: list[OptionEnrollmentView]


# ── M10b: dissolve + manual migrate + cap ──────────────────────────────────
class DissolveRequest(BaseModel):
    target_option_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    evidence_url: str | None = None


class ManualMigrateRequest(BaseModel):
    student_id: UUID
    from_option_id: UUID
    to_option_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class CapRequest(BaseModel):
    max_enrollment: int = Field(ge=1, le=1000)
    redistribute_to_option_id: UUID | None = None
    redistribute_strategy: Literal["by_registration_order", "manual"] | None = None


# Cascade summary (blast radius). Used both as the preview body and as the
# dissolve / migrate / cap commit response so the UI gets uniform shape.
class CascadeSummary(BaseModel):
    students_migrated: int
    attendance_records_preserved: int
    marks_preserved: int
    lab_batch_memberships_removed: int
    enrollment_rows_mutated: int
    affected_offering_ids: list[UUID]
    per_student: list[dict[str, Any]] = []  # diagnostic per-student detail


class DissolveResponse(BaseModel):
    summary: CascadeSummary
    event: dict


class ManualMigrateResponse(BaseModel):
    summary: CascadeSummary
    event: dict


class DisplacedStudent(BaseModel):
    student_user_id: UUID
    name: str
    usn: str | None = None
    registered_at: datetime


class CapResponse(BaseModel):
    new_max: int
    displaced: list[DisplacedStudent] = []  # only populated when strategy=manual
    summary: CascadeSummary | None = None  # only populated when actually redistributed
