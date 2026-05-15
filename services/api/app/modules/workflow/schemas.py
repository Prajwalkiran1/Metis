"""Pydantic schemas for the M10 workflow module.

M10a surface: semester setup CRUD, course-assignment-within-setup,
elective groups + options, admin-notifications feed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
