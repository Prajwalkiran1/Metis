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


# ── M10c: lab batches ───────────────────────────────────────────────────────
class LabBatchAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lab_batch_id: UUID
    teacher_user_id: UUID
    teacher_name: str | None = None
    role: str
    assigned_at: datetime
    unassigned_at: datetime | None = None
    unassigned_reason: str | None = None


class LabBatchMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lab_batch_id: UUID
    student_user_id: UUID
    student_name: str
    usn: str | None = None
    added_at: datetime


class LabBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_offering_id: UUID
    section_id: UUID
    name: str
    display_order: int
    member_count: int
    incharge: LabBatchAssignmentOut | None = None
    co_evaluators: list[LabBatchAssignmentOut] = []


class LabBatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    display_order: int = Field(default=1, ge=1, le=99)


class LabBatchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    display_order: int | None = Field(default=None, ge=1, le=99)


class LabBatchMembersAdd(BaseModel):
    student_user_ids: list[UUID] = Field(min_length=1, max_length=200)


class LabBatchMemberRemove(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class LabBatchAutoCompose(BaseModel):
    batch_count: int = Field(ge=1, le=20)
    name_prefix: str = Field(default="Batch", min_length=1, max_length=20)


class OfferingRosterEntry(BaseModel):
    student_user_id: UUID
    name: str
    usn: str | None = None


class LabBatchAutoComposeResult(BaseModel):
    batches_created: int
    batches_total: int
    students_assigned: int
    students_skipped: int
    distribution: dict[str, int]  # batch name → student count
    event: dict


class LabBatchAssignmentCreate(BaseModel):
    teacher_user_id: UUID
    role: Literal["batch_incharge", "co_evaluator"] = "batch_incharge"


class LabBatchAssignmentRemove(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# ── M10c: per-offering scheme picker ────────────────────────────────────────
class SchemeComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    label: str
    max_marks: float
    weight_percent: float
    ordinal: int
    is_dropped_in_best_of: bool
    metadata_json: dict


class SchemeOut(BaseModel):
    id: UUID
    course_offering_id: UUID
    template_id: UUID | None = None
    template_name: str | None = None
    configured_by_user_id: UUID
    is_locked: bool
    locked_at: datetime | None = None
    locked_reason: str | None = None
    components: list[SchemeComponentOut] = []
    aat_total_percent: float
    weight_total_percent: float
    # When this offering inherits from a parent (integrated lab side),
    # `inherited_from_offering_id` is set and the components above are
    # taken from the parent. Writes return a 400 with code='scheme_inherited'.
    inherited_from_offering_id: UUID | None = None


class SchemeComponentInput(BaseModel):
    kind: Literal[
        "cie", "aat", "lab", "assignment", "see", "nptel_assignment", "nptel_final"
    ]
    label: str = Field(min_length=1, max_length=50)
    max_marks: float = Field(ge=0, le=1000)
    weight_percent: float = Field(ge=0, le=100)
    ordinal: int = Field(default=1, ge=1, le=20)
    is_dropped_in_best_of: bool = False
    metadata_json: dict = Field(default_factory=dict)


class SchemeReplace(BaseModel):
    """Three ways to land on a new scheme:
      1. template_id only — instantiate that template's default_components
      2. clone_from_offering_id — copy components from a sibling offering
      3. components only — fully custom shape
    Exactly one of the three input modes must be supplied.
    """

    template_id: UUID | None = None
    clone_from_offering_id: UUID | None = None
    components: list[SchemeComponentInput] | None = None
    lock_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_source(self) -> "SchemeReplace":
        sources = sum(
            1
            for v in (self.template_id, self.clone_from_offering_id, self.components)
            if v is not None
        )
        if sources != 1:
            raise ValueError(
                "supply exactly one of template_id, clone_from_offering_id, components"
            )
        return self


class SchemeComponentPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=50)
    max_marks: float | None = Field(default=None, ge=0, le=1000)
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    ordinal: int | None = Field(default=None, ge=1, le=20)
    is_dropped_in_best_of: bool | None = None


class SchemeLockRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class SchemeUnlockRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


# ── M10c: department scheme templates ───────────────────────────────────────
class SchemeTemplateComponentInput(BaseModel):
    kind: Literal[
        "cie", "aat", "lab", "assignment", "see", "nptel_assignment", "nptel_final"
    ]
    label: str = Field(min_length=1, max_length=50)
    max_marks: float = Field(ge=0, le=1000)
    weight_percent: float = Field(ge=0, le=100)
    ordinal: int = Field(default=1, ge=1, le=20)
    metadata: dict = Field(default_factory=dict)


class SchemeTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_department_id: UUID | None = None
    owner_department_code: str | None = None
    name: str
    description: str | None = None
    applies_to_course_type: str
    validation_rules: dict
    default_components: list[dict]
    is_active: bool
    is_institutional: bool
    usage_count: int = 0


class SchemeTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    applies_to_course_type: Literal["theory", "lab", "integrated", "nptel"]
    validation_rules: dict = Field(default_factory=dict)
    default_components: list[SchemeTemplateComponentInput] = Field(min_length=1, max_length=20)


class SchemeTemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    validation_rules: dict | None = None
    default_components: list[SchemeTemplateComponentInput] | None = None
    is_active: bool | None = None


# ── M10c: HOD dashboard scheme-readiness card ───────────────────────────────
class SchemeReadinessOffering(BaseModel):
    course_offering_id: UUID
    course_code: str
    course_title: str
    course_type: str
    section_name: str
    is_locked: bool
    has_scheme: bool
    aat_total_percent: float


class SchemeReadinessOut(BaseModel):
    total_offerings: int
    with_scheme: int
    locked: int
    unlocked: int
    offerings: list[SchemeReadinessOffering] = []


# ── M10d: internal deadlines ────────────────────────────────────────────────
class DeadlineKind(BaseModel):
    pass  # placeholder


class InternalDeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    academic_term_id: UUID
    academic_term_code: str | None = None
    department_id: UUID | None = None
    department_code: str | None = None
    course_offering_id: UUID | None = None
    course_code: str | None = None
    deadline_at: datetime
    kind: Literal["institutional_hard", "department_soft", "per_course_freeze"]
    set_by_user_id: UUID
    set_by_name: str | None = None
    is_frozen: bool
    frozen_at: datetime | None = None
    frozen_by_user_id: UUID | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class InternalDeadlineCreate(BaseModel):
    academic_term_id: UUID
    deadline_at: datetime
    kind: Literal["institutional_hard", "department_soft", "per_course_freeze"]
    department_id: UUID | None = None  # required for department_soft and per_course_freeze
    course_offering_id: UUID | None = None  # required for per_course_freeze
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _kind_targets(self) -> "InternalDeadlineCreate":
        if self.kind == "institutional_hard" and (
            self.department_id is not None or self.course_offering_id is not None
        ):
            raise ValueError("institutional_hard must not target a dept or offering")
        if self.kind == "department_soft":
            if self.department_id is None or self.course_offering_id is not None:
                raise ValueError("department_soft needs department_id and no offering_id")
        if self.kind == "per_course_freeze":
            if self.course_offering_id is None:
                raise ValueError("per_course_freeze needs course_offering_id")
        return self


class InternalDeadlinePatch(BaseModel):
    deadline_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class InternalDeadlineFreezeRequest(BaseModel):
    is_frozen: bool
    notes: str | None = Field(default=None, max_length=2000)


# ── M10d: CIE schedule ──────────────────────────────────────────────────────
class CIEScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_offering_id: UUID
    cie_number: int
    scheduled_at: datetime
    duration_minutes: int
    room_id: UUID | None = None
    room_code: str | None = None
    notes: str | None = None
    is_published: bool
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CIEScheduleCreate(BaseModel):
    cie_number: int = Field(ge=1, le=3)
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=300)
    room_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CIESchedulePatch(BaseModel):
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=300)
    room_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CIEPublishRequest(BaseModel):
    publish: bool = True


# ── M10d: tasks ─────────────────────────────────────────────────────────────
class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assigned_by_user_id: UUID
    assigned_by_name: str | None = None
    assigned_to_user_id: UUID
    assigned_to_name: str | None = None
    task_type: Literal[
        "invigilation", "paper_setting", "evaluation", "makeup_exam", "other"
    ]
    title: str
    description: str | None = None
    related_entity_type: str | None = None
    related_entity_id: UUID | None = None
    due_at: datetime | None = None
    status: Literal[
        "pending", "accepted", "declined", "completed", "cancelled"
    ]
    status_updated_at: datetime | None = None
    decline_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    assigned_to_user_id: UUID
    task_type: Literal[
        "invigilation", "paper_setting", "evaluation", "makeup_exam", "other"
    ]
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    related_entity_type: str | None = Field(default=None, max_length=50)
    related_entity_id: UUID | None = None
    due_at: datetime | None = None


class TaskStatusUpdate(BaseModel):
    status: Literal["accepted", "declined", "completed", "cancelled"]
    decline_reason: str | None = Field(default=None, max_length=2000)


# ── M10d: deadline freeze status (helper view) ─────────────────────────────
class OfferingFreezeStatus(BaseModel):
    course_offering_id: UUID
    is_frozen: bool
    frozen_by_kind: Literal[
        "institutional_hard", "department_soft", "per_course_freeze"
    ] | None = None
    deadline_at: datetime | None = None
    frozen_at: datetime | None = None
    notes: str | None = None


# ── M10e: hall tickets ──────────────────────────────────────────────────────
class HallTicketSubjectStatus(BaseModel):
    course_offering_id: UUID
    course_code: str
    course_title: str
    course_type: str
    attendance_percent: float
    cie_percent: float | None = None
    attendance_eligible: bool
    cie_eligible: bool
    overall_eligible: bool
    reason: str | None = None


class HallTicketVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hall_ticket_id: UUID
    version_number: int
    generated_at: datetime
    generated_by_user_id: UUID
    pdf_url: str
    eligibility_snapshot: dict


class HallTicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_user_id: UUID
    student_name: str | None = None
    usn: str | None = None
    academic_term_id: UUID
    academic_term_code: str | None = None
    generated_at: datetime
    approved_at: datetime | None = None
    approved_by_user_id: UUID | None = None
    current_version_id: UUID | None = None
    is_active: bool
    eligible_subject_count: int = 0
    ineligible_subject_count: int = 0
    versions: list[HallTicketVersionOut] = []


class HallTicketBatchRequest(BaseModel):
    academic_term_id: UUID


class HallTicketApproveRequest(BaseModel):
    hall_ticket_ids: list[UUID] = Field(min_length=1, max_length=1000)


class HallTicketBatchResult(BaseModel):
    generated: int
    regenerated: int
    skipped: int
    hall_ticket_ids: list[UUID]


# ── M10e: SEE results ──────────────────────────────────────────────────────
class SEEResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enrollment_id: int
    student_user_id: UUID | None = None
    usn: str | None = None
    student_name: str | None = None
    kind: Literal["original", "re_evaluation", "makeup"]
    marks_obtained: float | None = None
    max_marks: float
    uploaded_at: datetime | None = None
    uploaded_by_user_id: UUID | None = None
    notes: str | None = None
    is_current: bool


class SEEUploadRow(BaseModel):
    usn: str = Field(min_length=1, max_length=40)
    marks_obtained: float = Field(ge=0, le=1000)
    notes: str | None = None


class SEEUploadRequest(BaseModel):
    course_offering_id: UUID
    max_marks: float = Field(default=100, ge=0, le=1000)
    rows: list[SEEUploadRow] = Field(min_length=1, max_length=2000)


class SEEUploadResult(BaseModel):
    course_offering_id: UUID
    batch_id: UUID
    inserted: int
    skipped: list[dict]
    csv_upload_batch_id: UUID


# ── M10e: re-evaluation ────────────────────────────────────────────────────
class ReEvalRequestCreate(BaseModel):
    course_offering_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class ReEvalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enrollment_id: int
    student_user_id: UUID
    student_name: str | None = None
    usn: str | None = None
    course_offering_id: UUID | None = None
    course_code: str | None = None
    requested_at: datetime
    status: Literal["requested", "processing", "completed", "rejected"]
    original_marks: float | None = None
    revised_marks: float | None = None
    outcome: Literal["improved", "held", "rejected"] | None = None
    reason: str | None = None
    resolved_at: datetime | None = None


class ReEvalUploadRow(BaseModel):
    usn: str = Field(min_length=1, max_length=40)
    revised_marks: float = Field(ge=0, le=1000)


class ReEvalUploadRequest(BaseModel):
    course_offering_id: UUID
    rows: list[ReEvalUploadRow] = Field(min_length=1, max_length=500)


class ReEvalUploadResult(BaseModel):
    processed: int
    improved: int
    held: int
    rejected: list[dict]


# ── M10e: makeup ────────────────────────────────────────────────────────────
class MakeupAuthorizeRequest(BaseModel):
    course_offering_id: UUID
    enrollment_ids: list[int] = Field(min_length=1, max_length=2000)


class MakeupUploadRow(BaseModel):
    usn: str = Field(min_length=1, max_length=40)
    marks_obtained: float = Field(ge=0, le=1000)


class MakeupUploadRequest(BaseModel):
    course_offering_id: UUID
    max_marks: float = Field(default=100, ge=0, le=1000)
    rows: list[MakeupUploadRow] = Field(min_length=1, max_length=2000)


class MakeupUploadResult(BaseModel):
    processed: int
    skipped: list[dict]


# ── M10e: grade cards ──────────────────────────────────────────────────────
class GradeCardVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grade_card_id: UUID
    version_number: int
    generated_at: datetime
    generated_by_user_id: UUID
    trigger_reason: str
    pdf_url: str


class GradeCardSubjectGrade(BaseModel):
    course_offering_id: UUID
    course_code: str
    course_title: str
    course_type: str
    credits: int
    internal_marks: float | None = None
    see_marks: float | None = None
    total_percent: float | None = None
    grade: str
    is_pending: bool
    is_backlog: bool


class GradeCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_user_id: UUID
    student_name: str | None = None
    usn: str | None = None
    academic_term_id: UUID
    academic_term_code: str | None = None
    is_finalised: bool
    current_version_id: UUID | None = None
    versions: list[GradeCardVersionOut] = []
    subjects: list[GradeCardSubjectGrade] = []
    sgpa: float | None = None


class GradeCardGenerateRequest(BaseModel):
    academic_term_id: UUID
    student_user_ids: list[UUID] | None = None  # None → whole department
