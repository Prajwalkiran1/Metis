"""HTTP surface for M10 workflow.

Three routers ship out of this module:

- `hod_router`    — `/hod/*`     (legacy dashboard placeholder)
- `workflow_router` — `/workflow/*` (HOD-driven semester setup CRUD)
- `admin_notifications_router` — `/admin/notifications` (read-only feed)

Service-layer errors raise WorkflowError; the helper below maps them to
HTTPException so each handler stays a one-liner.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.core.db import SessionDep
from app.core.deps import (
    CurrentUser,
    require_admin,
    require_hod,
    require_hod_or_admin,
    require_student,
    require_teacher_hod_or_admin,
)
from app.modules.academic.models import (
    Course,
    CourseOffering,
    Department,
    Section,
)
from app.modules.users.models import User
from app.modules.workflow import (
    service,
    service_m10b,
    service_m10c,
    service_m10d,
    service_m10e,
)
from app.modules.workflow.models import SemesterSetup, SemesterSetupState
from app.modules.workflow.schemas import (
    AdminNotificationOut,
    CapRequest,
    CapResponse,
    CascadeSummary,
    CourseAssignmentCreate,
    CourseAssignmentOut,
    CourseAssignmentPatch,
    DisplacedStudent,
    DissolveRequest,
    DissolveResponse,
    ElectiveGroupCreate,
    ElectiveGroupEnrollmentView,
    ElectiveGroupOptionCreate,
    ElectiveGroupOptionOut,
    ElectiveGroupOptionPatch,
    ElectiveGroupOut,
    ElectiveGroupPatch,
    LabBatchAssignmentCreate,
    LabBatchAssignmentOut,
    LabBatchAssignmentRemove,
    LabBatchAutoCompose,
    LabBatchAutoComposeResult,
    LabBatchCreate,
    LabBatchMemberRemove,
    LabBatchMembersAdd,
    LabBatchOut,
    LabBatchPatch,
    CIEPublishRequest,
    CIEScheduleCreate,
    CIESchedulePatch,
    CIEScheduleOut,
    GradeCardGenerateRequest,
    GradeCardOut,
    HallTicketApproveRequest,
    HallTicketBatchRequest,
    HallTicketBatchResult,
    HallTicketOut,
    InternalDeadlineCreate,
    MakeupAuthorizeRequest,
    MakeupUploadRequest,
    MakeupUploadResult,
    ReEvalOut,
    ReEvalRequestCreate,
    ReEvalUploadRequest,
    ReEvalUploadResult,
    SEEResultOut,
    SEEUploadRequest,
    SEEUploadResult,
    InternalDeadlineFreezeRequest,
    InternalDeadlineOut,
    InternalDeadlinePatch,
    OfferingFreezeStatus,
    OfferingRosterEntry,
    TaskCreate,
    TaskOut,
    TaskStatusUpdate,
    ManualMigrateRequest,
    ManualMigrateResponse,
    Page,
    RegistrationChoice,
    RegistrationRowOut,
    RegistrationWindowSet,
    SchemeComponentPatch,
    SchemeLockRequest,
    SchemeOut,
    SchemeReadinessOut,
    SchemeReplace,
    SchemeTemplateCreate,
    SchemeTemplateOut,
    SchemeTemplatePatch,
    SchemeUnlockRequest,
    SemesterSetupCreate,
    SemesterSetupDetail,
    SemesterSetupOut,
    SemesterSetupPatch,
    StudentRegistrationSubmit,
    StudentRegistrationView,
)


def _to_http(exc: service.WorkflowError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


# ── /hod/* (legacy dashboard placeholder) ───────────────────────────────────
hod_router = APIRouter(prefix="/hod", tags=["hod"])


class TeachingOfferingOut(BaseModel):
    id: UUID
    course_code: str
    course_title: str
    section_name: str
    academic_term: str


class HodDashboardOut(BaseModel):
    department: dict[str, Any]
    teaching_offerings: list[TeachingOfferingOut]
    current_term_setup: dict[str, Any] | None
    electives_summary: dict[str, Any] | None
    placeholder: dict[str, Any]


@hod_router.get("/dashboard", response_model=HodDashboardOut)
async def hod_dashboard(
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> HodDashboardOut:
    if actor.hod_of_department_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "hod_dept_missing",
                "message": "HOD user has no department assignment",
            },
        )
    dept = await session.get(Department, actor.hod_of_department_id)
    if dept is None or dept.deleted_at is not None:
        raise HTTPException(
            status_code=404,
            detail={"code": "dept_not_found", "message": "department not found"},
        )

    rows = (
        await session.execute(
            select(
                CourseOffering.id,
                Course.code,
                Course.title,
                Section.name,
                CourseOffering.academic_term,
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .where(
                and_(
                    CourseOffering.teacher_user_id == actor.id,
                    CourseOffering.deleted_at.is_(None),
                    CourseOffering.is_active.is_(True),
                )
            )
            .order_by(CourseOffering.academic_term.desc(), Course.code)
        )
    ).all()

    teaching = [
        TeachingOfferingOut(
            id=r.id,
            course_code=r.code,
            course_title=r.title,
            section_name=r.name,
            academic_term=r.academic_term,
        )
        for r in rows
    ]

    dept_offering_count = (
        await session.execute(
            select(func.count(CourseOffering.id))
            .join(Course, Course.id == CourseOffering.course_id)
            .where(
                Course.department_id == dept.id,
                CourseOffering.deleted_at.is_(None),
                CourseOffering.is_active.is_(True),
            )
        )
    ).scalar_one()

    # Surface the most recent setup for this department so the dashboard can
    # nudge HODs toward draft/publish without needing a second roundtrip.
    latest = (
        await session.execute(
            select(SemesterSetup)
            .where(
                SemesterSetup.college_id == actor.college_id,
                SemesterSetup.department_id == dept.id,
                SemesterSetup.deleted_at.is_(None),
            )
            .order_by(SemesterSetup.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    current_setup: dict[str, Any] | None = None
    if latest is not None:
        current_setup = {
            "id": str(latest.id),
            "academic_term_id": str(latest.academic_term_id),
            "state": latest.state.value,
            "published_at": latest.published_at.isoformat()
            if latest.published_at
            else None,
        }

    # M10b — count under-subscribed elective options on the current setup so
    # the dashboard can link to /hod/electives with a hot-spot callout.
    electives_summary: dict[str, Any] | None = None
    if latest is not None:
        from app.modules.workflow.models import (  # local — avoids cycles
            CourseRegistration as _CR,
            ElectiveGroup as _EG,
            ElectiveGroupOption as _EGO,
        )

        eg_rows = (
            await session.execute(
                select(_EG.id, _EG.min_enrollment_to_run).where(
                    _EG.semester_setup_id == latest.id,
                    _EG.deleted_at.is_(None),
                )
            )
        ).all()
        under = 0
        total_options = 0
        for eg_id, min_run in eg_rows:
            options = (
                await session.execute(
                    select(_EGO.id).where(
                        _EGO.elective_group_id == eg_id,
                        _EGO.deleted_at.is_(None),
                        _EGO.is_dissolved.is_(False),
                    )
                )
            ).all()
            for (opt_id,) in options:
                total_options += 1
                count = (
                    await session.execute(
                        select(func.count(_CR.id)).where(
                            _CR.elective_group_option_id == opt_id,
                            _CR.status == "approved",
                            _CR.deleted_at.is_(None),
                        )
                    )
                ).scalar_one()
                if int(count) < min_run:
                    under += 1
        electives_summary = {
            "under_subscribed_count": under,
            "total_options": total_options,
        }

    return HodDashboardOut(
        department={"id": str(dept.id), "code": dept.code, "name": dept.name},
        teaching_offerings=teaching,
        current_term_setup=current_setup,
        electives_summary=electives_summary,
        placeholder={
            "message": "M10 will populate this dashboard with department analytics.",
            "department_active_offerings": int(dept_offering_count),
        },
    )


# ── /workflow/* ─────────────────────────────────────────────────────────────
workflow_router = APIRouter(prefix="/workflow", tags=["workflow"])


@workflow_router.get(
    "/semester-setups", response_model=list[SemesterSetupOut]
)
async def list_semester_setups(
    session: SessionDep,
    actor: CurrentUser,
    department_id: UUID | None = Query(default=None),
    academic_term_id: UUID | None = Query(default=None),
    state: SemesterSetupState | None = Query(default=None),
) -> list[SemesterSetupOut]:
    try:
        rows = await service.list_setups(
            session,
            actor=actor,
            department_id=department_id,
            academic_term_id=academic_term_id,
            state=state,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [SemesterSetupOut.model_validate(r) for r in rows]


@workflow_router.get(
    "/semester-setups/{setup_id}", response_model=SemesterSetupDetail
)
async def get_semester_setup(
    setup_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> SemesterSetupDetail:
    try:
        d = await service.get_setup_detail(
            session, actor=actor, setup_id=setup_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SemesterSetupDetail.model_validate(d)


@workflow_router.post(
    "/semester-setups", response_model=SemesterSetupOut, status_code=201
)
async def create_semester_setup(
    payload: SemesterSetupCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SemesterSetupOut:
    try:
        setup = await service.create_setup(session, actor=actor, payload=payload)
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SemesterSetupOut.model_validate(setup)


@workflow_router.patch(
    "/semester-setups/{setup_id}", response_model=SemesterSetupOut
)
async def patch_semester_setup(
    setup_id: UUID,
    payload: SemesterSetupPatch,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SemesterSetupOut:
    try:
        setup = await service.patch_setup(
            session, actor=actor, setup_id=setup_id, payload=payload
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SemesterSetupOut.model_validate(setup)


@workflow_router.delete("/semester-setups/{setup_id}", status_code=204)
async def delete_semester_setup(
    setup_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> None:
    try:
        await service.delete_setup(session, actor=actor, setup_id=setup_id)
    except service.WorkflowError as e:
        raise _to_http(e) from e


class PublishResponse(BaseModel):
    setup: SemesterSetupOut
    event: dict[str, Any]


@workflow_router.post(
    "/semester-setups/{setup_id}/publish", response_model=PublishResponse
)
async def publish_semester_setup(
    setup_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> PublishResponse:
    try:
        setup, payload = await service.publish_setup(
            session, actor=actor, setup_id=setup_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return PublishResponse(
        setup=SemesterSetupOut.model_validate(setup), event=payload
    )


# ── Course assignments within a setup ──────────────────────────────────────
@workflow_router.post(
    "/semester-setups/{setup_id}/courses",
    response_model=CourseAssignmentOut,
    status_code=201,
)
async def add_course_to_setup(
    setup_id: UUID,
    payload: CourseAssignmentCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> CourseAssignmentOut:
    try:
        offering = await service.add_course(
            session, actor=actor, setup_id=setup_id, payload=payload
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    # Re-load denormalised display fields so the client's table updates
    # without an extra fetch.
    row = (
        await session.execute(
            select(
                CourseOffering,
                Course.code,
                Course.title,
                Course.course_type,
                Section.name.label("section_name"),
                User.name.label("teacher_name"),
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .join(User, User.id == CourseOffering.teacher_user_id, isouter=True)
            .where(CourseOffering.id == offering.id)
        )
    ).one()
    off = row[0]
    return CourseAssignmentOut.model_validate(
        {
            "id": off.id,
            "course_id": off.course_id,
            "course_code": row.code,
            "course_title": row.title,
            "course_type": row.course_type,
            "section_id": off.section_id,
            "section_name": row.section_name,
            "teacher_user_id": off.teacher_user_id,
            "teacher_name": row.teacher_name,
            "parent_offering_id": off.parent_offering_id,
            "assessment_scheme_id": off.assessment_scheme_id,
            "is_active": off.is_active,
        }
    )


@workflow_router.patch(
    "/semester-setups/{setup_id}/courses/{offering_id}",
    response_model=CourseAssignmentOut,
)
async def patch_course_in_setup(
    setup_id: UUID,
    offering_id: UUID,
    payload: CourseAssignmentPatch,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> CourseAssignmentOut:
    try:
        offering = await service.patch_course(
            session,
            actor=actor,
            setup_id=setup_id,
            offering_id=offering_id,
            payload=payload,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    row = (
        await session.execute(
            select(
                CourseOffering,
                Course.code,
                Course.title,
                Course.course_type,
                Section.name.label("section_name"),
                User.name.label("teacher_name"),
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .join(User, User.id == CourseOffering.teacher_user_id, isouter=True)
            .where(CourseOffering.id == offering.id)
        )
    ).one()
    off = row[0]
    return CourseAssignmentOut.model_validate(
        {
            "id": off.id,
            "course_id": off.course_id,
            "course_code": row.code,
            "course_title": row.title,
            "course_type": row.course_type,
            "section_id": off.section_id,
            "section_name": row.section_name,
            "teacher_user_id": off.teacher_user_id,
            "teacher_name": row.teacher_name,
            "parent_offering_id": off.parent_offering_id,
            "assessment_scheme_id": off.assessment_scheme_id,
            "is_active": off.is_active,
        }
    )


@workflow_router.delete(
    "/semester-setups/{setup_id}/courses/{offering_id}", status_code=204
)
async def remove_course_from_setup(
    setup_id: UUID,
    offering_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> None:
    try:
        await service.remove_course(
            session, actor=actor, setup_id=setup_id, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


# ── Elective groups + options ──────────────────────────────────────────────
@workflow_router.post(
    "/semester-setups/{setup_id}/elective-groups",
    response_model=ElectiveGroupOut,
    status_code=201,
)
async def add_elective_group(
    setup_id: UUID,
    payload: ElectiveGroupCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ElectiveGroupOut:
    try:
        eg = await service.add_elective_group(
            session, actor=actor, setup_id=setup_id, payload=payload
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return ElectiveGroupOut.model_validate(
        {
            "id": eg.id,
            "semester_setup_id": eg.semester_setup_id,
            "name": eg.name,
            "description": eg.description,
            "required_credits": eg.required_credits,
            "min_enrollment_to_run": eg.min_enrollment_to_run,
            "max_enrollment": eg.max_enrollment,
            "options": [],
        }
    )


@workflow_router.patch(
    "/semester-setups/{setup_id}/elective-groups/{eg_id}",
    response_model=ElectiveGroupOut,
)
async def patch_elective_group(
    setup_id: UUID,
    eg_id: UUID,
    payload: ElectiveGroupPatch,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ElectiveGroupOut:
    try:
        eg = await service.patch_elective_group(
            session,
            actor=actor,
            setup_id=setup_id,
            eg_id=eg_id,
            payload=payload,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return ElectiveGroupOut.model_validate(
        {
            "id": eg.id,
            "semester_setup_id": eg.semester_setup_id,
            "name": eg.name,
            "description": eg.description,
            "required_credits": eg.required_credits,
            "min_enrollment_to_run": eg.min_enrollment_to_run,
            "max_enrollment": eg.max_enrollment,
            "options": [],
        }
    )


@workflow_router.delete(
    "/semester-setups/{setup_id}/elective-groups/{eg_id}", status_code=204
)
async def delete_elective_group(
    setup_id: UUID,
    eg_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> None:
    try:
        await service.delete_elective_group(
            session, actor=actor, setup_id=setup_id, eg_id=eg_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


@workflow_router.post(
    "/semester-setups/{setup_id}/elective-groups/{eg_id}/options",
    response_model=ElectiveGroupOptionOut,
    status_code=201,
)
async def add_elective_option(
    setup_id: UUID,
    eg_id: UUID,
    payload: ElectiveGroupOptionCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ElectiveGroupOptionOut:
    try:
        opt = await service.add_elective_option(
            session,
            actor=actor,
            setup_id=setup_id,
            eg_id=eg_id,
            payload=payload,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    course = await session.get(Course, opt.course_id)
    teacher_name = None
    if opt.tentative_teacher_id is not None:
        t = await session.get(User, opt.tentative_teacher_id)
        teacher_name = t.name if t else None
    return ElectiveGroupOptionOut.model_validate(
        {
            "id": opt.id,
            "elective_group_id": opt.elective_group_id,
            "course_id": opt.course_id,
            "course_code": course.code if course else "",
            "course_title": course.title if course else "",
            "tentative_teacher_id": opt.tentative_teacher_id,
            "tentative_teacher_name": teacher_name,
            "is_dissolved": opt.is_dissolved,
        }
    )


@workflow_router.patch(
    "/semester-setups/{setup_id}/elective-groups/{eg_id}/options/{option_id}",
    response_model=ElectiveGroupOptionOut,
)
async def patch_elective_option(
    setup_id: UUID,
    eg_id: UUID,
    option_id: UUID,
    payload: ElectiveGroupOptionPatch,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ElectiveGroupOptionOut:
    try:
        opt = await service.patch_elective_option(
            session,
            actor=actor,
            setup_id=setup_id,
            eg_id=eg_id,
            option_id=option_id,
            payload=payload,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    course = await session.get(Course, opt.course_id)
    teacher_name = None
    if opt.tentative_teacher_id is not None:
        t = await session.get(User, opt.tentative_teacher_id)
        teacher_name = t.name if t else None
    return ElectiveGroupOptionOut.model_validate(
        {
            "id": opt.id,
            "elective_group_id": opt.elective_group_id,
            "course_id": opt.course_id,
            "course_code": course.code if course else "",
            "course_title": course.title if course else "",
            "tentative_teacher_id": opt.tentative_teacher_id,
            "tentative_teacher_name": teacher_name,
            "is_dissolved": opt.is_dissolved,
        }
    )


@workflow_router.delete(
    "/semester-setups/{setup_id}/elective-groups/{eg_id}/options/{option_id}",
    status_code=204,
)
async def delete_elective_option(
    setup_id: UUID,
    eg_id: UUID,
    option_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> None:
    try:
        await service.delete_elective_option(
            session,
            actor=actor,
            setup_id=setup_id,
            eg_id=eg_id,
            option_id=option_id,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


# ── /admin/notifications ────────────────────────────────────────────────────
admin_notifications_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_notifications_router.get(
    "/notifications", response_model=Page[AdminNotificationOut]
)
async def list_admin_notifications(
    session: SessionDep,
    actor: User = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AdminNotificationOut]:
    try:
        rows, total = await service.list_admin_notifications(
            session, actor=actor, limit=limit, offset=offset
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return Page[AdminNotificationOut](
        items=[AdminNotificationOut.model_validate(r) for r in rows], total=total
    )


# ── M10b: registration window ───────────────────────────────────────────────
@workflow_router.post(
    "/semester-setups/{setup_id}/registration-window",
    response_model=SemesterSetupOut,
)
async def set_registration_window(
    setup_id: UUID,
    payload: RegistrationWindowSet,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SemesterSetupOut:
    try:
        setup = await service_m10b.set_registration_window(
            session,
            actor=actor,
            setup_id=setup_id,
            opens_at=payload.opens_at,
            closes_at=payload.closes_at,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SemesterSetupOut.model_validate(setup)


# ── M10b: HOD enrollment view + dissolve / migrate / cap ───────────────────
@workflow_router.get(
    "/elective-groups/{eg_id}/enrollment",
    response_model=ElectiveGroupEnrollmentView,
)
async def get_elective_group_enrollment(
    eg_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ElectiveGroupEnrollmentView:
    try:
        d = await service_m10b.get_group_enrollment_view(
            session, actor=actor, eg_id=eg_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return ElectiveGroupEnrollmentView.model_validate(d)


@workflow_router.post(
    "/elective-groups/{eg_id}/options/{option_id}/dissolve/preview",
    response_model=CascadeSummary,
)
async def dissolve_option_preview(
    eg_id: UUID,
    option_id: UUID,
    payload: DissolveRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> CascadeSummary:
    try:
        d = await service_m10b.dissolve_option_preview(
            session,
            actor=actor,
            eg_id=eg_id,
            option_id=option_id,
            target_option_id=payload.target_option_id,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return CascadeSummary.model_validate(d)


@workflow_router.post(
    "/elective-groups/{eg_id}/options/{option_id}/dissolve",
    response_model=DissolveResponse,
)
async def dissolve_option(
    eg_id: UUID,
    option_id: UUID,
    payload: DissolveRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> DissolveResponse:
    try:
        summary, dissolved_payload, student_migrated_payloads = (
            await service_m10b.dissolve_option(
                session,
                actor=actor,
                eg_id=eg_id,
                option_id=option_id,
                target_option_id=payload.target_option_id,
                reason=payload.reason,
                evidence_url=payload.evidence_url,
            )
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e

    # Post-commit event emission. Failures are swallowed by the publisher.
    from app.core.event_bus import publish as publish_event

    event = await publish_event(
        "elective.dissolved",
        dissolved_payload,
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    for p in student_migrated_payloads:
        await publish_event(
            "student.migrated",
            p,
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return DissolveResponse(
        summary=CascadeSummary.model_validate(summary),
        event=event,
    )


@workflow_router.post(
    "/elective-groups/{eg_id}/migrate-student",
    response_model=ManualMigrateResponse,
)
async def migrate_student_manual(
    eg_id: UUID,
    payload: ManualMigrateRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ManualMigrateResponse:
    try:
        summary, student_migrated_payload = await service_m10b.migrate_student_manual(
            session,
            actor=actor,
            eg_id=eg_id,
            student_id=payload.student_id,
            from_option_id=payload.from_option_id,
            to_option_id=payload.to_option_id,
            reason=payload.reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    from app.core.event_bus import publish as publish_event

    event = await publish_event(
        "student.migrated",
        student_migrated_payload,
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return ManualMigrateResponse(
        summary=CascadeSummary.model_validate(summary),
        event=event,
    )


@workflow_router.post(
    "/elective-groups/{eg_id}/options/{option_id}/cap",
    response_model=CapResponse,
)
async def cap_option_capacity(
    eg_id: UUID,
    option_id: UUID,
    payload: CapRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> CapResponse:
    try:
        out = await service_m10b.cap_option_capacity(
            session,
            actor=actor,
            eg_id=eg_id,
            option_id=option_id,
            max_enrollment=payload.max_enrollment,
            redistribute_to_option_id=payload.redistribute_to_option_id,
            redistribute_strategy=payload.redistribute_strategy,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e

    from app.core.event_bus import publish as publish_event

    for p in out.get("events", []):
        await publish_event(
            "student.migrated",
            p,
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return CapResponse(
        new_max=out["new_max"],
        displaced=[DisplacedStudent.model_validate(d) for d in out.get("displaced", [])],
        summary=(
            CascadeSummary.model_validate(out["summary"])
            if out.get("summary")
            else None
        ),
    )


# ── M10b: student-side registration endpoints ──────────────────────────────
student_registration_router = APIRouter(
    prefix="/student/registration", tags=["student"]
)


@student_registration_router.get("", response_model=StudentRegistrationView)
async def student_registration_view(
    session: SessionDep,
    actor: User = Depends(require_student),
) -> StudentRegistrationView:
    try:
        d = await service_m10b.get_student_registration_view(
            session, student=actor
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return StudentRegistrationView.model_validate(d)


@student_registration_router.post(
    "/electives", response_model=list[RegistrationRowOut]
)
async def student_submit_electives(
    payload: StudentRegistrationSubmit,
    session: SessionDep,
    actor: User = Depends(require_student),
) -> list[RegistrationRowOut]:
    try:
        rows = await service_m10b.submit_student_registration(
            session,
            student=actor,
            choices=[(c.elective_group_id, c.elective_group_option_id) for c in payload.choices],
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [RegistrationRowOut.model_validate(r) for r in rows]


@student_registration_router.get(
    "/status", response_model=list[RegistrationRowOut]
)
async def student_registration_status(
    session: SessionDep,
    actor: User = Depends(require_student),
) -> list[RegistrationRowOut]:
    rows = await service_m10b.get_student_registration_status(
        session, student=actor
    )
    return [RegistrationRowOut.model_validate(r) for r in rows]


# ── M10c: lab batches ──────────────────────────────────────────────────────
@workflow_router.post(
    "/course-offerings/{offering_id}/lab-batches",
    response_model=LabBatchOut,
    status_code=201,
)
async def create_lab_batch(
    offering_id: UUID,
    payload: LabBatchCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> LabBatchOut:
    try:
        batch = await service_m10c.create_lab_batch(
            session,
            actor=actor,
            offering_id=offering_id,
            name=payload.name,
            display_order=payload.display_order,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return LabBatchOut.model_validate(
        {
            "id": batch.id,
            "course_offering_id": batch.course_offering_id,
            "section_id": batch.section_id,
            "name": batch.name,
            "display_order": batch.display_order,
            "member_count": 0,
            "incharge": None,
            "co_evaluators": [],
        }
    )


@workflow_router.get(
    "/course-offerings/{offering_id}/lab-batches",
    response_model=list[LabBatchOut],
)
async def list_lab_batches(
    offering_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> list[LabBatchOut]:
    try:
        rows = await service_m10c.list_lab_batches(
            session, actor=actor, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [LabBatchOut.model_validate(r) for r in rows]


@workflow_router.patch(
    "/lab-batches/{batch_id}", response_model=LabBatchOut
)
async def patch_lab_batch(
    batch_id: UUID,
    payload: LabBatchPatch,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> LabBatchOut:
    try:
        batch = await service_m10c.patch_lab_batch(
            session,
            actor=actor,
            batch_id=batch_id,
            name=payload.name,
            display_order=payload.display_order,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    # Re-issue a list to get member counts + assignments without re-implementing.
    rows = await service_m10c.list_lab_batches(
        session, actor=actor, offering_id=batch.course_offering_id
    )
    for r in rows:
        if r["id"] == batch.id:
            return LabBatchOut.model_validate(r)
    # Shouldn't happen — fallback to bare shape.
    return LabBatchOut.model_validate(
        {
            "id": batch.id,
            "course_offering_id": batch.course_offering_id,
            "section_id": batch.section_id,
            "name": batch.name,
            "display_order": batch.display_order,
            "member_count": 0,
            "incharge": None,
            "co_evaluators": [],
        }
    )


@workflow_router.delete("/lab-batches/{batch_id}", status_code=204)
async def delete_lab_batch(
    batch_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> None:
    try:
        await service_m10c.delete_lab_batch(
            session, actor=actor, batch_id=batch_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


class LabBatchMembersAddResponse(BaseModel):
    added_count: int
    skipped_not_in_section: list[str]
    skipped_already_in_batch: list[str]


@workflow_router.post(
    "/lab-batches/{batch_id}/members",
    response_model=LabBatchMembersAddResponse,
)
async def add_lab_batch_members(
    batch_id: UUID,
    payload: LabBatchMembersAdd,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> LabBatchMembersAddResponse:
    try:
        out = await service_m10c.add_members(
            session,
            actor=actor,
            batch_id=batch_id,
            student_user_ids=payload.student_user_ids,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return LabBatchMembersAddResponse.model_validate(out)


@workflow_router.delete(
    "/lab-batches/{batch_id}/members/{student_user_id}",
    status_code=204,
)
async def remove_lab_batch_member(
    batch_id: UUID,
    student_user_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
    reason: str | None = Query(default=None, max_length=500),
) -> None:
    try:
        await service_m10c.remove_member(
            session,
            actor=actor,
            batch_id=batch_id,
            student_user_id=student_user_id,
            reason=reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


@workflow_router.get(
    "/course-offerings/{offering_id}/roster",
    response_model=list[OfferingRosterEntry],
)
async def get_offering_roster(
    offering_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> list[OfferingRosterEntry]:
    try:
        rows = await service_m10c.get_offering_roster(
            session, actor=actor, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [OfferingRosterEntry.model_validate(r) for r in rows]


@workflow_router.post(
    "/course-offerings/{offering_id}/lab-batches/auto-compose",
    response_model=LabBatchAutoComposeResult,
)
async def auto_compose_lab_batches(
    offering_id: UUID,
    payload: LabBatchAutoCompose,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> LabBatchAutoComposeResult:
    try:
        out = await service_m10c.auto_compose_batches(
            session,
            actor=actor,
            offering_id=offering_id,
            batch_count=payload.batch_count,
            name_prefix=payload.name_prefix,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return LabBatchAutoComposeResult.model_validate(out)


class LabBatchAssignmentResponse(BaseModel):
    assignment: LabBatchAssignmentOut
    previous_incharge_id: str | None = None
    event: dict | None = None


@workflow_router.post(
    "/lab-batches/{batch_id}/assignments",
    response_model=LabBatchAssignmentResponse,
)
async def add_lab_batch_assignment(
    batch_id: UUID,
    payload: LabBatchAssignmentCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> LabBatchAssignmentResponse:
    try:
        out = await service_m10c.add_assignment(
            session,
            actor=actor,
            batch_id=batch_id,
            teacher_user_id=payload.teacher_user_id,
            role=payload.role,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return LabBatchAssignmentResponse(
        assignment=LabBatchAssignmentOut.model_validate(out["assignment"]),
        previous_incharge_id=out["previous_incharge_id"],
        event=out["event"],
    )


@workflow_router.delete(
    "/lab-batches/{batch_id}/assignments/{assignment_id}",
    status_code=204,
)
async def remove_lab_batch_assignment(
    batch_id: UUID,
    assignment_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
    reason: str | None = Query(default=None, max_length=500),
) -> None:
    try:
        await service_m10c.remove_assignment(
            session,
            actor=actor,
            batch_id=batch_id,
            assignment_id=assignment_id,
            reason=reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


# ── M10c: per-offering scheme picker ───────────────────────────────────────
@workflow_router.get(
    "/course-offerings/{offering_id}/scheme",
    response_model=SchemeOut,
)
async def get_offering_scheme(
    offering_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> SchemeOut:
    try:
        d = await service_m10c.get_scheme(
            session, actor=actor, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeOut.model_validate(d)


class SchemeReplaceResponse(SchemeOut):
    event: dict | None = None


@workflow_router.post(
    "/course-offerings/{offering_id}/scheme",
    response_model=SchemeReplaceResponse,
)
async def replace_offering_scheme(
    offering_id: UUID,
    payload: SchemeReplace,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> SchemeReplaceResponse:
    try:
        d = await service_m10c.replace_scheme(
            session,
            actor=actor,
            offering_id=offering_id,
            template_id=payload.template_id,
            clone_from_offering_id=payload.clone_from_offering_id,
            components_input=(
                [c.model_dump() for c in payload.components]
                if payload.components is not None
                else None
            ),
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeReplaceResponse.model_validate(d)


@workflow_router.patch(
    "/course-offerings/{offering_id}/scheme/components/{component_id}",
    response_model=SchemeReplaceResponse,
)
async def patch_scheme_component(
    offering_id: UUID,
    component_id: UUID,
    payload: SchemeComponentPatch,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> SchemeReplaceResponse:
    try:
        d = await service_m10c.patch_component(
            session,
            actor=actor,
            offering_id=offering_id,
            component_id=component_id,
            label=payload.label,
            max_marks=payload.max_marks,
            weight_percent=payload.weight_percent,
            ordinal=payload.ordinal,
            is_dropped_in_best_of=payload.is_dropped_in_best_of,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeReplaceResponse.model_validate(d)


@workflow_router.post(
    "/course-offerings/{offering_id}/scheme/lock",
    response_model=SchemeOut,
)
async def lock_offering_scheme(
    offering_id: UUID,
    payload: SchemeLockRequest,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> SchemeOut:
    try:
        d = await service_m10c.lock_scheme(
            session,
            actor=actor,
            offering_id=offering_id,
            reason=payload.reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeOut.model_validate(d)


@workflow_router.post(
    "/course-offerings/{offering_id}/scheme/unlock",
    response_model=SchemeOut,
)
async def unlock_offering_scheme(
    offering_id: UUID,
    payload: SchemeUnlockRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SchemeOut:
    try:
        d = await service_m10c.unlock_scheme(
            session,
            actor=actor,
            offering_id=offering_id,
            reason=payload.reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeOut.model_validate(d)


# ── M10c: scheme templates ─────────────────────────────────────────────────
@workflow_router.get(
    "/scheme-templates", response_model=list[SchemeTemplateOut]
)
async def list_scheme_templates(
    session: SessionDep,
    actor: CurrentUser,
    applies_to_course_type: str | None = Query(default=None),
) -> list[SchemeTemplateOut]:
    try:
        rows = await service_m10c.list_templates(
            session,
            actor=actor,
            applies_to_course_type=applies_to_course_type,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [SchemeTemplateOut.model_validate(r) for r in rows]


def _template_view(tpl, dept_code: str | None, usage_count: int = 0) -> dict[str, Any]:
    return {
        "id": tpl.id,
        "owner_department_id": tpl.owner_department_id,
        "owner_department_code": dept_code,
        "name": tpl.name,
        "description": tpl.description,
        "applies_to_course_type": tpl.applies_to_course_type,
        "validation_rules": tpl.validation_rules or {},
        "default_components": tpl.default_components or [],
        "is_active": tpl.is_active,
        "is_institutional": tpl.owner_department_id is None,
        "usage_count": usage_count,
    }


@workflow_router.post(
    "/scheme-templates", response_model=SchemeTemplateOut, status_code=201
)
async def create_scheme_template(
    payload: SchemeTemplateCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SchemeTemplateOut:
    try:
        tpl = await service_m10c.create_template(
            session,
            actor=actor,
            name=payload.name,
            description=payload.description,
            applies_to_course_type=payload.applies_to_course_type,
            validation_rules=payload.validation_rules,
            default_components=[c.model_dump() for c in payload.default_components],
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    dept_code: str | None = None
    if tpl.owner_department_id is not None:
        dept = await session.get(Department, tpl.owner_department_id)
        dept_code = dept.code if dept else None
    return SchemeTemplateOut.model_validate(_template_view(tpl, dept_code, 0))


@workflow_router.get(
    "/scheme-templates/{template_id}", response_model=SchemeTemplateOut
)
async def get_scheme_template(
    template_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> SchemeTemplateOut:
    try:
        tpl = await service_m10c.get_template(
            session, actor=actor, template_id=template_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    dept_code: str | None = None
    if tpl.owner_department_id is not None:
        dept = await session.get(Department, tpl.owner_department_id)
        dept_code = dept.code if dept else None
    # Recompute usage_count lazily — only this single template.
    from sqlalchemy import func as _func
    from app.modules.academic.models import AssessmentScheme as _AS

    usage = (
        await session.execute(
            select(_func.count(_AS.id)).where(
                _AS.template_id == tpl.id,
                _AS.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return SchemeTemplateOut.model_validate(
        _template_view(tpl, dept_code, int(usage))
    )


@workflow_router.patch(
    "/scheme-templates/{template_id}", response_model=SchemeTemplateOut
)
async def patch_scheme_template(
    template_id: UUID,
    payload: SchemeTemplatePatch,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SchemeTemplateOut:
    try:
        tpl = await service_m10c.patch_template(
            session,
            actor=actor,
            template_id=template_id,
            name=payload.name,
            description=payload.description,
            validation_rules=payload.validation_rules,
            default_components=(
                [c.model_dump() for c in payload.default_components]
                if payload.default_components is not None
                else None
            ),
            is_active=payload.is_active,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    dept_code: str | None = None
    if tpl.owner_department_id is not None:
        dept = await session.get(Department, tpl.owner_department_id)
        dept_code = dept.code if dept else None
    return SchemeTemplateOut.model_validate(_template_view(tpl, dept_code))


@workflow_router.delete("/scheme-templates/{template_id}", status_code=204)
async def delete_scheme_template(
    template_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> None:
    try:
        await service_m10c.delete_template(
            session, actor=actor, template_id=template_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


# ── M10c: HOD scheme-readiness card ────────────────────────────────────────
@hod_router.get("/scheme-readiness", response_model=SchemeReadinessOut)
async def hod_scheme_readiness(
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SchemeReadinessOut:
    try:
        d = await service_m10c.get_scheme_readiness(session, actor=actor)
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SchemeReadinessOut.model_validate(d)


# ── M10d: internal deadlines ───────────────────────────────────────────────
@workflow_router.get(
    "/internal-deadlines", response_model=list[InternalDeadlineOut]
)
async def list_internal_deadlines(
    session: SessionDep,
    actor: CurrentUser,
    academic_term_id: UUID | None = Query(default=None),
    kind: str | None = Query(default=None),
) -> list[InternalDeadlineOut]:
    try:
        rows = await service_m10d.list_deadlines(
            session,
            actor=actor,
            academic_term_id=academic_term_id,
            kind=kind,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    out = []
    for d in rows:
        view = await service_m10d.deadline_to_dict(session, d)
        out.append(InternalDeadlineOut.model_validate(view))
    return out


@workflow_router.post(
    "/internal-deadlines",
    response_model=InternalDeadlineOut,
    status_code=201,
)
async def create_internal_deadline(
    payload: InternalDeadlineCreate,
    session: SessionDep,
    actor: CurrentUser,
) -> InternalDeadlineOut:
    try:
        d = await service_m10d.create_deadline(
            session,
            actor=actor,
            academic_term_id=payload.academic_term_id,
            deadline_at=payload.deadline_at,
            kind=payload.kind,
            department_id=payload.department_id,
            course_offering_id=payload.course_offering_id,
            notes=payload.notes,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    view = await service_m10d.deadline_to_dict(session, d)
    return InternalDeadlineOut.model_validate(view)


@workflow_router.patch(
    "/internal-deadlines/{deadline_id}",
    response_model=InternalDeadlineOut,
)
async def patch_internal_deadline(
    deadline_id: UUID,
    payload: InternalDeadlinePatch,
    session: SessionDep,
    actor: CurrentUser,
) -> InternalDeadlineOut:
    try:
        d = await service_m10d.patch_deadline(
            session,
            actor=actor,
            deadline_id=deadline_id,
            deadline_at=payload.deadline_at,
            notes=payload.notes,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    view = await service_m10d.deadline_to_dict(session, d)
    return InternalDeadlineOut.model_validate(view)


@workflow_router.delete(
    "/internal-deadlines/{deadline_id}", status_code=204
)
async def delete_internal_deadline(
    deadline_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> None:
    try:
        await service_m10d.delete_deadline(
            session, actor=actor, deadline_id=deadline_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e


class InternalDeadlineFreezeResponse(BaseModel):
    deadline: InternalDeadlineOut
    event: dict | None = None


@workflow_router.post(
    "/internal-deadlines/{deadline_id}/freeze",
    response_model=InternalDeadlineFreezeResponse,
)
async def freeze_internal_deadline(
    deadline_id: UUID,
    payload: InternalDeadlineFreezeRequest,
    session: SessionDep,
    actor: CurrentUser,
) -> InternalDeadlineFreezeResponse:
    try:
        d, event = await service_m10d.freeze_deadline(
            session,
            actor=actor,
            deadline_id=deadline_id,
            is_frozen=payload.is_frozen,
            notes=payload.notes,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    view = await service_m10d.deadline_to_dict(session, d)
    return InternalDeadlineFreezeResponse(
        deadline=InternalDeadlineOut.model_validate(view), event=event
    )


@workflow_router.get(
    "/course-offerings/{offering_id}/freeze-status",
    response_model=OfferingFreezeStatus,
)
async def offering_freeze_status(
    offering_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> OfferingFreezeStatus:
    try:
        d = await service_m10d.get_offering_freeze_status(
            session, actor=actor, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return OfferingFreezeStatus.model_validate(d)


# ── M10d: CIE schedule ─────────────────────────────────────────────────────
@workflow_router.get(
    "/course-offerings/{offering_id}/cie-schedule",
    response_model=list[CIEScheduleOut],
)
async def list_cie_for_offering(
    offering_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> list[CIEScheduleOut]:
    try:
        rows = await service_m10d.list_cie_schedule(
            session, actor=actor, offering_id=offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [CIEScheduleOut.model_validate(r) for r in rows]


@workflow_router.post(
    "/course-offerings/{offering_id}/cie-schedule",
    response_model=CIEScheduleOut,
    status_code=201,
)
async def create_cie_entry(
    offering_id: UUID,
    payload: CIEScheduleCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> CIEScheduleOut:
    try:
        cie = await service_m10d.create_cie(
            session,
            actor=actor,
            offering_id=offering_id,
            cie_number=payload.cie_number,
            scheduled_at=payload.scheduled_at,
            duration_minutes=payload.duration_minutes,
            room_id=payload.room_id,
            notes=payload.notes,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    room_code: str | None = None
    if cie.room_id is not None:
        from app.modules.academic.models import Room as _Room

        rm = await session.get(_Room, cie.room_id)
        room_code = rm.code if rm else None
    return CIEScheduleOut.model_validate(
        {
            "id": cie.id,
            "course_offering_id": cie.course_offering_id,
            "cie_number": cie.cie_number,
            "scheduled_at": cie.scheduled_at,
            "duration_minutes": cie.duration_minutes,
            "room_id": cie.room_id,
            "room_code": room_code,
            "notes": cie.notes,
            "is_published": cie.is_published,
            "published_at": cie.published_at,
            "created_at": cie.created_at,
            "updated_at": cie.updated_at,
        }
    )


@workflow_router.patch(
    "/cie-schedule/{cie_id}", response_model=CIEScheduleOut
)
async def patch_cie_entry(
    cie_id: UUID,
    payload: CIESchedulePatch,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> CIEScheduleOut:
    try:
        cie = await service_m10d.patch_cie(
            session,
            actor=actor,
            cie_id=cie_id,
            scheduled_at=payload.scheduled_at,
            duration_minutes=payload.duration_minutes,
            room_id=payload.room_id,
            notes=payload.notes,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    room_code: str | None = None
    if cie.room_id is not None:
        from app.modules.academic.models import Room as _Room

        rm = await session.get(_Room, cie.room_id)
        room_code = rm.code if rm else None
    return CIEScheduleOut.model_validate(
        {
            "id": cie.id,
            "course_offering_id": cie.course_offering_id,
            "cie_number": cie.cie_number,
            "scheduled_at": cie.scheduled_at,
            "duration_minutes": cie.duration_minutes,
            "room_id": cie.room_id,
            "room_code": room_code,
            "notes": cie.notes,
            "is_published": cie.is_published,
            "published_at": cie.published_at,
            "created_at": cie.created_at,
            "updated_at": cie.updated_at,
        }
    )


@workflow_router.delete("/cie-schedule/{cie_id}", status_code=204)
async def delete_cie_entry(
    cie_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> None:
    try:
        await service_m10d.delete_cie(session, actor=actor, cie_id=cie_id)
    except service.WorkflowError as e:
        raise _to_http(e) from e


class CIEPublishResponse(BaseModel):
    course_offering_id: UUID
    is_published: bool
    cie_count: int
    event: dict | None = None


@workflow_router.post(
    "/course-offerings/{offering_id}/cie-schedule/publish",
    response_model=CIEPublishResponse,
)
async def publish_cie(
    offering_id: UUID,
    payload: CIEPublishRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> CIEPublishResponse:
    try:
        d = await service_m10d.publish_cie_schedule(
            session,
            actor=actor,
            offering_id=offering_id,
            publish=payload.publish,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return CIEPublishResponse.model_validate(d)


# ── M10d: tasks ────────────────────────────────────────────────────────────
@workflow_router.get("/tasks", response_model=list[TaskOut])
async def list_workflow_tasks(
    session: SessionDep,
    actor: CurrentUser,
    mode: str = Query(default="mine"),
    status: str | None = Query(default=None),
) -> list[TaskOut]:
    try:
        rows = await service_m10d.list_tasks(
            session, actor=actor, mode=mode, status=status  # type: ignore[arg-type]
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    out = []
    for t in rows:
        view = await service_m10d.task_to_dict(session, t)
        out.append(TaskOut.model_validate(view))
    return out


@workflow_router.post(
    "/tasks", response_model=TaskOut, status_code=201
)
async def create_workflow_task(
    payload: TaskCreate,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> TaskOut:
    try:
        t = await service_m10d.create_task(
            session,
            actor=actor,
            assigned_to_user_id=payload.assigned_to_user_id,
            task_type=payload.task_type,
            title=payload.title,
            description=payload.description,
            related_entity_type=payload.related_entity_type,
            related_entity_id=payload.related_entity_id,
            due_at=payload.due_at,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    view = await service_m10d.task_to_dict(session, t)
    return TaskOut.model_validate(view)


@workflow_router.post(
    "/tasks/{task_id}/status", response_model=TaskOut
)
async def transition_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    session: SessionDep,
    actor: CurrentUser,
) -> TaskOut:
    try:
        t = await service_m10d.update_task_status(
            session,
            actor=actor,
            task_id=task_id,
            status=payload.status,
            decline_reason=payload.decline_reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    view = await service_m10d.task_to_dict(session, t)
    return TaskOut.model_validate(view)


# ── M10e: hall tickets ─────────────────────────────────────────────────────
@workflow_router.get(
    "/hall-tickets", response_model=list[HallTicketOut]
)
async def list_hall_tickets(
    session: SessionDep,
    actor: User = Depends(require_hod_or_admin),
    academic_term_id: UUID | None = Query(default=None),
) -> list[HallTicketOut]:
    try:
        rows = await service_m10e.list_hall_tickets(
            session, actor=actor, academic_term_id=academic_term_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [HallTicketOut.model_validate(r) for r in rows]


class HallTicketGenerateRequest(BaseModel):
    student_user_id: UUID
    academic_term_id: UUID


@workflow_router.post(
    "/hall-tickets/generate",
    response_model=HallTicketOut,
)
async def generate_hall_ticket(
    payload: HallTicketGenerateRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> HallTicketOut:
    try:
        await service_m10e.generate_hall_ticket_for_student(
            session,
            actor=actor,
            student_user_id=payload.student_user_id,
            academic_term_id=payload.academic_term_id,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    rows = await service_m10e.list_hall_tickets(
        session, actor=actor, academic_term_id=payload.academic_term_id
    )
    matched = [r for r in rows if r["student_user_id"] == payload.student_user_id]
    if not matched:
        raise HTTPException(404, detail={"code": "not_found", "message": "ticket not found"})
    return HallTicketOut.model_validate(matched[0])


@workflow_router.post(
    "/hall-tickets/batch", response_model=HallTicketBatchResult
)
async def batch_generate_hall_tickets(
    payload: HallTicketBatchRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> HallTicketBatchResult:
    try:
        out = await service_m10e.batch_generate_hall_tickets(
            session, actor=actor, academic_term_id=payload.academic_term_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return HallTicketBatchResult.model_validate(out)


class HallTicketApproveResponse(BaseModel):
    approved: int


@workflow_router.post(
    "/hall-tickets/approve", response_model=HallTicketApproveResponse
)
async def approve_hall_tickets(
    payload: HallTicketApproveRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> HallTicketApproveResponse:
    try:
        n = await service_m10e.approve_hall_tickets(
            session, actor=actor, hall_ticket_ids=payload.hall_ticket_ids
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return HallTicketApproveResponse(approved=n)


@workflow_router.get("/hall-tickets/me", response_model=HallTicketOut | None)
async def my_hall_ticket(
    session: SessionDep,
    actor: User = Depends(require_student),
    academic_term_id: UUID | None = Query(default=None),
) -> HallTicketOut | None:
    try:
        d = await service_m10e.get_my_hall_ticket(
            session, student=actor, academic_term_id=academic_term_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    if d is None:
        return None
    return HallTicketOut.model_validate(d)


@workflow_router.get(
    "/hall-tickets/versions/{version_id}/pdf",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_hall_ticket_pdf(
    version_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> Response:
    try:
        pdf_bytes = await service_m10e.render_hall_ticket_pdf_for_version(
            session, actor=actor, version_id=version_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="hall_ticket_{version_id}.pdf"'},
    )


# ── M10e: SEE upload + list ────────────────────────────────────────────────
@workflow_router.post(
    "/see-results/upload", response_model=SEEUploadResult
)
async def upload_see(
    payload: SEEUploadRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> SEEUploadResult:
    try:
        out = await service_m10e.upload_see_results(
            session,
            actor=actor,
            course_offering_id=payload.course_offering_id,
            max_marks=Decimal(str(payload.max_marks)),
            rows=[r.model_dump() for r in payload.rows],
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return SEEUploadResult.model_validate(out)


@workflow_router.get(
    "/see-results", response_model=list[SEEResultOut]
)
async def list_see(
    session: SessionDep,
    actor: CurrentUser,
    course_offering_id: UUID = Query(...),
) -> list[SEEResultOut]:
    try:
        rows = await service_m10e.list_see_results(
            session, actor=actor, course_offering_id=course_offering_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [SEEResultOut.model_validate(r) for r in rows]


# ── M10e: re-evaluation ────────────────────────────────────────────────────
@workflow_router.post(
    "/re-evaluations", response_model=ReEvalOut, status_code=201
)
async def request_re_evaluation_route(
    payload: ReEvalRequestCreate,
    session: SessionDep,
    actor: User = Depends(require_student),
) -> ReEvalOut:
    try:
        r = await service_m10e.request_re_evaluation(
            session,
            student=actor,
            course_offering_id=payload.course_offering_id,
            reason=payload.reason,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    # Hydrate via list_re_evaluations(mine=True) to denormalise.
    rows = await service_m10e.list_re_evaluations(
        session, actor=actor, mine=True
    )
    matched = [row for row in rows if row["id"] == r.id]
    return ReEvalOut.model_validate(matched[0] if matched else rows[0])


@workflow_router.post(
    "/re-evaluations/upload", response_model=ReEvalUploadResult
)
async def upload_re_eval_marks(
    payload: ReEvalUploadRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> ReEvalUploadResult:
    try:
        out = await service_m10e.upload_re_evaluation_marks(
            session,
            actor=actor,
            course_offering_id=payload.course_offering_id,
            rows=[r.model_dump() for r in payload.rows],
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return ReEvalUploadResult.model_validate(out)


@workflow_router.get(
    "/re-evaluations", response_model=list[ReEvalOut]
)
async def list_re_evals(
    session: SessionDep,
    actor: CurrentUser,
    course_offering_id: UUID | None = Query(default=None),
    mine: bool = Query(default=False),
) -> list[ReEvalOut]:
    try:
        rows = await service_m10e.list_re_evaluations(
            session,
            actor=actor,
            course_offering_id=course_offering_id,
            mine=mine,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [ReEvalOut.model_validate(r) for r in rows]


# ── M10e: makeup ───────────────────────────────────────────────────────────
class MakeupAuthorizeResponse(BaseModel):
    authorised: int
    skipped: list[dict]


@workflow_router.post(
    "/makeup/authorize", response_model=MakeupAuthorizeResponse
)
async def authorize_makeup_route(
    payload: MakeupAuthorizeRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> MakeupAuthorizeResponse:
    try:
        out = await service_m10e.authorize_makeup(
            session,
            actor=actor,
            course_offering_id=payload.course_offering_id,
            enrollment_ids=payload.enrollment_ids,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return MakeupAuthorizeResponse.model_validate(out)


@workflow_router.post(
    "/makeup/upload", response_model=MakeupUploadResult
)
async def upload_makeup_route(
    payload: MakeupUploadRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> MakeupUploadResult:
    try:
        out = await service_m10e.upload_makeup_marks(
            session,
            actor=actor,
            course_offering_id=payload.course_offering_id,
            max_marks=Decimal(str(payload.max_marks)),
            rows=[r.model_dump() for r in payload.rows],
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return MakeupUploadResult.model_validate(out)


# ── M10e: grade cards ──────────────────────────────────────────────────────
@workflow_router.post(
    "/grade-cards/generate", response_model=GradeCardOut
)
async def generate_grade_card_route(
    payload: GradeCardGenerateRequest,
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> GradeCardOut:
    if payload.student_user_ids is None or len(payload.student_user_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_payload",
                "message": "single-student generate uses student_user_ids=[uuid]; batch UI uses /grade-cards/batch (M10e+)",
            },
        )
    sid = payload.student_user_ids[0]
    try:
        await service_m10e.generate_grade_card(
            session,
            actor=actor,
            student_user_id=sid,
            academic_term_id=payload.academic_term_id,
            trigger_reason="initial",
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    rows = await service_m10e.list_grade_cards(
        session,
        actor=actor,
        academic_term_id=payload.academic_term_id,
        student_user_id=sid,
    )
    if not rows:
        raise HTTPException(404, detail={"code": "not_found", "message": "card not found"})
    return GradeCardOut.model_validate(rows[0])


@workflow_router.get(
    "/grade-cards", response_model=list[GradeCardOut]
)
async def list_grade_cards_route(
    session: SessionDep,
    actor: CurrentUser,
    academic_term_id: UUID | None = Query(default=None),
    student_user_id: UUID | None = Query(default=None),
) -> list[GradeCardOut]:
    try:
        rows = await service_m10e.list_grade_cards(
            session,
            actor=actor,
            academic_term_id=academic_term_id,
            student_user_id=student_user_id,
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return [GradeCardOut.model_validate(r) for r in rows]


@workflow_router.get(
    "/grade-cards/versions/{version_id}/pdf",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_grade_card_pdf(
    version_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> Response:
    try:
        pdf_bytes = await service_m10e.render_grade_card_pdf_for_version(
            session, actor=actor, version_id=version_id
        )
    except service.WorkflowError as e:
        raise _to_http(e) from e
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="grade_card_{version_id}.pdf"'},
    )


# Public re-export so main.py can wire all three with one symbol.
router = workflow_router
