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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.core.db import SessionDep
from app.core.deps import (
    CurrentUser,
    require_admin,
    require_hod,
    require_hod_or_admin,
    require_student,
)
from app.modules.academic.models import (
    Course,
    CourseOffering,
    Department,
    Section,
)
from app.modules.users.models import User
from app.modules.workflow import service, service_m10b
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
    ManualMigrateRequest,
    ManualMigrateResponse,
    Page,
    RegistrationChoice,
    RegistrationRowOut,
    RegistrationWindowSet,
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


# Public re-export so main.py can wire all three with one symbol.
router = workflow_router
