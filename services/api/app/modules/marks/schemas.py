"""Request/response schemas for the marks module."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.marks.models import (
    AssessmentState,
    AssessmentType,
    GuardianRelationship,
    MarkState,
)


# ── Pagination ──────────────────────────────────────────────────────────────
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


# ── Assessments ─────────────────────────────────────────────────────────────
class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    course_offering_id: UUID
    type: AssessmentType
    name: str
    max_marks: Decimal
    weight_percent: Decimal | None = None
    scheduled_date: date | None = None
    state: AssessmentState
    locked_at: datetime | None = None
    locked_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class AssessmentCreate(BaseModel):
    course_offering_id: UUID
    type: AssessmentType
    name: str = Field(min_length=1, max_length=200)
    max_marks: Decimal = Field(ge=0, le=1000)
    weight_percent: Decimal | None = Field(default=None, ge=0, le=100)
    scheduled_date: date | None = None


class AssessmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    max_marks: Decimal | None = Field(default=None, ge=0, le=1000)
    weight_percent: Decimal | None = Field(default=None, ge=0, le=100)
    scheduled_date: date | None = None


class AssessmentLockRequest(BaseModel):
    lock: bool
    reason: str | None = Field(default=None, max_length=400)


# ── Marks ───────────────────────────────────────────────────────────────────
class MarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    assessment_id: UUID
    student_user_id: UUID
    marks_obtained: Decimal | None = None
    is_absent: bool
    state: MarkState
    entered_by_user_id: UUID
    last_modified_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class MarkEntry(BaseModel):
    marks_obtained: Decimal | None = Field(default=None, ge=0, le=1000)
    is_absent: bool = False
    reason: str | None = Field(default=None, max_length=400)


class BulkError(BaseModel):
    row_number: int
    student_uid: str | None = None
    code: str
    message: str


class MarkBulkResponse(BaseModel):
    committed: int
    errors: list[BulkError]
    dry_run: bool


# ── Stats ───────────────────────────────────────────────────────────────────
class AssessmentStats(BaseModel):
    assessment_id: UUID
    count: int
    absent_count: int
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    min: float | None = None
    max: float | None = None
    max_marks: float
    locked: bool


# ── Student history ─────────────────────────────────────────────────────────
class AssessmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_offering_id: UUID
    course_code: str
    course_title: str
    type: AssessmentType
    name: str
    max_marks: Decimal
    weight_percent: Decimal | None = None
    scheduled_date: date | None = None
    state: AssessmentState


class StudentMarkItem(BaseModel):
    assessment: AssessmentSummary
    mark: MarkOut | None
    class_mean: float | None
    class_stddev: float | None


class StudentMarksHistory(BaseModel):
    student_user_id: UUID
    items: list[StudentMarkItem]


# ── Grade rules ─────────────────────────────────────────────────────────────
class GradeRuleEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessment_type: AssessmentType
    weight_percent: Decimal = Field(ge=0, le=100)
    passing_threshold_percent: Decimal = Field(default=Decimal("40.0"), ge=0, le=100)


class GradeRuleSet(BaseModel):
    course_offering_id: UUID
    rules: list[GradeRuleEntry]


# ── Mark audit ──────────────────────────────────────────────────────────────
class MarkAuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mark_id: UUID
    assessment_id: UUID
    student_user_id: UUID
    action: str
    old_value: dict | None = None
    new_value: dict | None = None
    reason: str | None = None
    actor_user_id: UUID
    created_at: datetime


# ── Parent / guardian ───────────────────────────────────────────────────────
class StudentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    usn: str | None = None


class AssessmentRosterRow(BaseModel):
    student_user_id: UUID
    name: str
    usn: str | None = None
    mark_id: UUID | None = None
    marks_obtained: Decimal | None = None
    is_absent: bool = False
    state: MarkState | None = None


class ParentChildView(BaseModel):
    student: StudentSummary
    relationship: GuardianRelationship
    history: StudentMarksHistory


class ParentMarksView(BaseModel):
    children: list[ParentChildView]


class GuardianLinkCreate(BaseModel):
    parent_email: str = Field(min_length=3, max_length=255)
    parent_name: str = Field(min_length=1, max_length=200)
    student_user_id: UUID
    relationship: GuardianRelationship


class GuardianLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    parent_user_id: UUID
    student_user_id: UUID
    relationship: GuardianRelationship
    verified_at: datetime | None = None
    created_at: datetime
