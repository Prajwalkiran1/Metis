"""FastAPI router for M2 — academic service.

Conventions:
- Writes require admin (via `Depends(require_admin)`).
- Reads require an authenticated user (`CurrentUser`); tenant filter happens
  in the service layer via `actor.college_id`.
- Service errors → HTTPException via `_to_http(...)`, same pattern as
  `app/modules/users/router.py`.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.db import SessionDep
from app.core.deps import CurrentUser, require_admin, require_teacher_hod_or_admin
from app.modules.academic import service
from app.modules.academic.models import (
    AcademicCalendarKind,
    CourseType,
    RoomType,
)
from app.modules.academic.schemas import (
    BatchCreate,
    BatchOut,
    BatchPatch,
    CalendarEntryCreate,
    CalendarEntryOut,
    CalendarEntryPatch,
    ConflictCheckRequest,
    ConflictCheckResponse,
    CourseCreate,
    CourseOfferingCreate,
    CourseOfferingOut,
    CourseOfferingPatch,
    CourseOut,
    CoursePatch,
    DepartmentCreate,
    DepartmentOut,
    DepartmentPatch,
    EnrollmentOut,
    EnrollmentsCreate,
    Page,
    RoomCreate,
    RoomOut,
    RoomPatch,
    SectionCreate,
    SectionOut,
    SectionPatch,
    AdHocExtraCreate,
    AdHocRescheduleCreate,
    AdHocRoomChangeCreate,
    TimetableExceptionCreate,
    TimetableExceptionOut,
    TimetableSlotCreate,
    TimetableSlotOut,
    TimetableSlotPatch,
    TimetableView,
)
from app.modules.users.models import User

router = APIRouter(tags=["academic"])


def _to_http(exc: service.AcademicError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


# ── Academic terms (read-only for now; admin CRUD lands with M9) ────────────
@router.get("/academic-terms")
async def list_academic_terms(
    session: SessionDep,
    actor: CurrentUser,
) -> list[dict]:
    """Return all non-deleted terms in the actor's college, newest first.

    Read scope only — admin/HOD CRUD lives on the admin terms page in M9.
    Returned shape is intentionally hand-rolled here so we don't have to
    add a Pydantic schema just for a flat list.
    """
    from sqlalchemy import select as _select  # local to avoid top-level churn

    from app.modules.academic.models import AcademicTerm

    rows = (
        await session.execute(
            _select(AcademicTerm)
            .where(
                AcademicTerm.college_id == actor.college_id,
                AcademicTerm.deleted_at.is_(None),
            )
            .order_by(AcademicTerm.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "term_type": r.term_type.value,
            "starts_on": r.starts_on.isoformat() if r.starts_on else None,
            "ends_on": r.ends_on.isoformat() if r.ends_on else None,
        }
        for r in rows
    ]


# ── Departments ─────────────────────────────────────────────────────────────
@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    body: DepartmentCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> DepartmentOut:
    try:
        d = await service.create_department(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return DepartmentOut.model_validate(d)


@router.get("/departments", response_model=Page[DepartmentOut])
async def list_departments(
    session: SessionDep,
    actor: CurrentUser,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[DepartmentOut]:
    items, total = await service.list_departments(
        session,
        actor=actor,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[DepartmentOut](
        items=[DepartmentOut.model_validate(d) for d in items], total=total
    )


@router.get("/departments/{dept_id}", response_model=DepartmentOut)
async def get_department(
    dept_id: UUID, session: SessionDep, actor: CurrentUser
) -> DepartmentOut:
    try:
        d = await service.get_department(session, actor=actor, dept_id=dept_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return DepartmentOut.model_validate(d)


@router.patch("/departments/{dept_id}", response_model=DepartmentOut)
async def patch_department(
    dept_id: UUID,
    body: DepartmentPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> DepartmentOut:
    try:
        d = await service.patch_department(
            session, actor=actor, dept_id=dept_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return DepartmentOut.model_validate(d)


@router.delete("/departments/{dept_id}", status_code=204)
async def delete_department(
    dept_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_department(session, actor=actor, dept_id=dept_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Courses ─────────────────────────────────────────────────────────────────
@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(
    body: CourseCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CourseOut:
    try:
        c = await service.create_course(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOut.model_validate(c)


@router.get("/courses", response_model=Page[CourseOut])
async def list_courses(
    session: SessionDep,
    actor: CurrentUser,
    department_id: UUID | None = None,
    semester: int | None = Query(None, ge=1, le=12),
    course_type: CourseType | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[CourseOut]:
    items, total = await service.list_courses(
        session,
        actor=actor,
        department_id=department_id,
        semester=semester,
        course_type=course_type,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[CourseOut](items=[CourseOut.model_validate(c) for c in items], total=total)


@router.get("/courses/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: UUID, session: SessionDep, actor: CurrentUser
) -> CourseOut:
    try:
        c = await service.get_course(session, actor=actor, course_id=course_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOut.model_validate(c)


@router.patch("/courses/{course_id}", response_model=CourseOut)
async def patch_course(
    course_id: UUID,
    body: CoursePatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CourseOut:
    try:
        c = await service.patch_course(
            session, actor=actor, course_id=course_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOut.model_validate(c)


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(
    course_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_course(session, actor=actor, course_id=course_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Batches ─────────────────────────────────────────────────────────────────
@router.post("/batches", response_model=BatchOut, status_code=201)
async def create_batch(
    body: BatchCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> BatchOut:
    try:
        b = await service.create_batch(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return BatchOut.model_validate(b)


@router.get("/batches", response_model=Page[BatchOut])
async def list_batches(
    session: SessionDep,
    actor: CurrentUser,
    department_id: UUID | None = None,
    admission_year: int | None = Query(None, ge=1900, le=2100),
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[BatchOut]:
    items, total = await service.list_batches(
        session,
        actor=actor,
        department_id=department_id,
        admission_year=admission_year,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[BatchOut](items=[BatchOut.model_validate(b) for b in items], total=total)


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def get_batch(
    batch_id: UUID, session: SessionDep, actor: CurrentUser
) -> BatchOut:
    try:
        b = await service.get_batch(session, actor=actor, batch_id=batch_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return BatchOut.model_validate(b)


@router.patch("/batches/{batch_id}", response_model=BatchOut)
async def patch_batch(
    batch_id: UUID,
    body: BatchPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> BatchOut:
    try:
        b = await service.patch_batch(
            session, actor=actor, batch_id=batch_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return BatchOut.model_validate(b)


@router.delete("/batches/{batch_id}", status_code=204)
async def delete_batch(
    batch_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_batch(session, actor=actor, batch_id=batch_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Sections ────────────────────────────────────────────────────────────────
@router.post("/sections", response_model=SectionOut, status_code=201)
async def create_section(
    body: SectionCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> SectionOut:
    try:
        s = await service.create_section(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return SectionOut.model_validate(s)


@router.get("/sections", response_model=Page[SectionOut])
async def list_sections(
    session: SessionDep,
    actor: CurrentUser,
    batch_id: UUID | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[SectionOut]:
    items, total = await service.list_sections(
        session,
        actor=actor,
        batch_id=batch_id,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[SectionOut](items=[SectionOut.model_validate(s) for s in items], total=total)


@router.get("/sections/{section_id}", response_model=SectionOut)
async def get_section(
    section_id: UUID, session: SessionDep, actor: CurrentUser
) -> SectionOut:
    try:
        s = await service.get_section(session, actor=actor, section_id=section_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return SectionOut.model_validate(s)


@router.patch("/sections/{section_id}", response_model=SectionOut)
async def patch_section(
    section_id: UUID,
    body: SectionPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> SectionOut:
    try:
        s = await service.patch_section(
            session, actor=actor, section_id=section_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return SectionOut.model_validate(s)


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(
    section_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_section(session, actor=actor, section_id=section_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Section enrollments ─────────────────────────────────────────────────────
@router.post(
    "/sections/{section_id}/enrollments",
    response_model=list[EnrollmentOut],
    status_code=201,
)
async def add_section_enrollments(
    section_id: UUID,
    body: EnrollmentsCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> list[EnrollmentOut]:
    try:
        created = await service.add_enrollments(
            session, actor=actor, section_id=section_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return [EnrollmentOut.model_validate(e) for e in created]


@router.get(
    "/sections/{section_id}/students", response_model=list[EnrollmentOut]
)
async def list_section_students(
    section_id: UUID, session: SessionDep, actor: CurrentUser
) -> list[EnrollmentOut]:
    try:
        rows = await service.list_section_enrollments(
            session, actor=actor, section_id=section_id
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return [EnrollmentOut.model_validate(r) for r in rows]


@router.delete(
    "/sections/{section_id}/enrollments/{enrollment_id}", status_code=204
)
async def withdraw_section_enrollment(
    section_id: UUID,
    enrollment_id: int,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.withdraw_enrollment(
            session,
            actor=actor,
            section_id=section_id,
            enrollment_id=enrollment_id,
        )
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Rooms ───────────────────────────────────────────────────────────────────
@router.post("/rooms", response_model=RoomOut, status_code=201)
async def create_room(
    body: RoomCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> RoomOut:
    try:
        r = await service.create_room(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return RoomOut.model_validate(r)


@router.get("/rooms", response_model=Page[RoomOut])
async def list_rooms(
    session: SessionDep,
    actor: CurrentUser,
    room_type: RoomType | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[RoomOut]:
    items, total = await service.list_rooms(
        session,
        actor=actor,
        room_type=room_type,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[RoomOut](items=[RoomOut.model_validate(r) for r in items], total=total)


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(room_id: UUID, session: SessionDep, actor: CurrentUser) -> RoomOut:
    try:
        r = await service.get_room(session, actor=actor, room_id=room_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return RoomOut.model_validate(r)


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def patch_room(
    room_id: UUID,
    body: RoomPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> RoomOut:
    try:
        r = await service.patch_room(
            session, actor=actor, room_id=room_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return RoomOut.model_validate(r)


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(
    room_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_room(session, actor=actor, room_id=room_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Course offerings ────────────────────────────────────────────────────────
@router.post("/course-offerings", response_model=CourseOfferingOut, status_code=201)
async def create_course_offering(
    body: CourseOfferingCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CourseOfferingOut:
    try:
        o = await service.create_offering(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOfferingOut.model_validate(o)


@router.get("/course-offerings", response_model=Page[CourseOfferingOut])
async def list_course_offerings(
    session: SessionDep,
    actor: CurrentUser,
    section_id: UUID | None = None,
    course_id: UUID | None = None,
    teacher_user_id: UUID | None = None,
    academic_term: str | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[CourseOfferingOut]:
    items, total = await service.list_offerings(
        session,
        actor=actor,
        section_id=section_id,
        course_id=course_id,
        teacher_user_id=teacher_user_id,
        academic_term=academic_term,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[CourseOfferingOut](
        items=[CourseOfferingOut.model_validate(o) for o in items], total=total
    )


@router.get("/course-offerings/{offering_id}", response_model=CourseOfferingOut)
async def get_course_offering(
    offering_id: UUID, session: SessionDep, actor: CurrentUser
) -> CourseOfferingOut:
    try:
        o = await service.get_offering(session, actor=actor, offering_id=offering_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOfferingOut.model_validate(o)


@router.patch("/course-offerings/{offering_id}", response_model=CourseOfferingOut)
async def patch_course_offering(
    offering_id: UUID,
    body: CourseOfferingPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CourseOfferingOut:
    try:
        o = await service.patch_offering(
            session, actor=actor, offering_id=offering_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CourseOfferingOut.model_validate(o)


@router.delete("/course-offerings/{offering_id}", status_code=204)
async def delete_course_offering(
    offering_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_offering(session, actor=actor, offering_id=offering_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Timetable ───────────────────────────────────────────────────────────────
@router.post("/timetable", response_model=TimetableSlotOut, status_code=201)
async def create_timetable_slot(
    body: TimetableSlotCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
    force: bool = Query(False, description="Override conflicts; logged in audit_logs."),
) -> TimetableSlotOut:
    try:
        s = await service.create_timetable_slot(
            session, actor=actor, payload=body, force=force
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableSlotOut.model_validate(s)


@router.get("/timetable/{section_id}", response_model=TimetableView)
async def get_timetable_for_section(
    section_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> TimetableView:
    try:
        slots, exceptions = await service.get_timetable_for_section(
            session,
            actor=actor,
            section_id=section_id,
            from_date=from_date,
            to_date=to_date,
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableView(
        section_id=section_id,
        slots=[TimetableSlotOut.model_validate(s) for s in slots],
        exceptions=[TimetableExceptionOut.model_validate(x) for x in exceptions],
    )


@router.patch("/timetable/{slot_id}", response_model=TimetableSlotOut)
async def patch_timetable_slot(
    slot_id: UUID,
    body: TimetableSlotPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
    force: bool = Query(False),
) -> TimetableSlotOut:
    try:
        s = await service.patch_timetable_slot(
            session, actor=actor, slot_id=slot_id, payload=body, force=force
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableSlotOut.model_validate(s)


@router.delete("/timetable/{slot_id}", status_code=204)
async def delete_timetable_slot(
    slot_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_timetable_slot(session, actor=actor, slot_id=slot_id)
    except service.AcademicError as e:
        raise _to_http(e) from e


@router.post(
    "/timetable/check-conflict", response_model=ConflictCheckResponse
)
async def check_timetable_conflict(
    body: ConflictCheckRequest,
    session: SessionDep,
    actor: CurrentUser,
) -> ConflictCheckResponse:
    conflicts = await service.check_timetable_conflict(
        session, actor=actor, payload=body
    )
    return ConflictCheckResponse(has_conflicts=bool(conflicts), conflicts=conflicts)


@router.post(
    "/timetable/exceptions",
    response_model=TimetableExceptionOut,
    status_code=201,
)
async def create_timetable_exception(
    body: TimetableExceptionCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> TimetableExceptionOut:
    try:
        exc = await service.create_timetable_exception(
            session, actor=actor, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableExceptionOut.model_validate(exc)


@router.delete("/timetable/exceptions/{exception_id}", status_code=204)
async def delete_timetable_exception(
    exception_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_timetable_exception(
            session, actor=actor, exception_id=exception_id
        )
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Teacher/HOD-scoped ad-hoc class session routes ──────────────────────────
@router.post(
    "/offerings/{offering_id}/timetable-exceptions/extra",
    response_model=TimetableExceptionOut,
    status_code=201,
)
async def create_offering_extra_session(
    offering_id: UUID,
    body: AdHocExtraCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> TimetableExceptionOut:
    try:
        exc = await service.create_extra_class_session(
            session, actor=actor, offering_id=offering_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableExceptionOut.model_validate(exc)


@router.post(
    "/offerings/{offering_id}/timetable-exceptions/reschedule",
    response_model=TimetableExceptionOut,
    status_code=201,
)
async def create_offering_reschedule(
    offering_id: UUID,
    body: AdHocRescheduleCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> TimetableExceptionOut:
    try:
        exc = await service.create_reschedule_exception(
            session, actor=actor, offering_id=offering_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableExceptionOut.model_validate(exc)


@router.post(
    "/offerings/{offering_id}/timetable-exceptions/room-change",
    response_model=TimetableExceptionOut,
    status_code=201,
)
async def create_offering_room_change(
    offering_id: UUID,
    body: AdHocRoomChangeCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> TimetableExceptionOut:
    try:
        exc = await service.create_room_change_exception(
            session, actor=actor, offering_id=offering_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return TimetableExceptionOut.model_validate(exc)


@router.get(
    "/offerings/{offering_id}/timetable-exceptions",
    response_model=list[TimetableExceptionOut],
)
async def list_offering_timetable_exceptions(
    offering_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> list[TimetableExceptionOut]:
    try:
        rows = await service.list_offering_exceptions(
            session, actor=actor, offering_id=offering_id
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return [TimetableExceptionOut.model_validate(r) for r in rows]


@router.delete(
    "/offerings/{offering_id}/timetable-exceptions/{exception_id}",
    status_code=204,
)
async def delete_offering_timetable_exception(
    offering_id: UUID,
    exception_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_hod_or_admin),
) -> None:
    try:
        await service.delete_offering_exception(
            session,
            actor=actor,
            offering_id=offering_id,
            exception_id=exception_id,
        )
    except service.AcademicError as e:
        raise _to_http(e) from e


# ── Academic calendar ───────────────────────────────────────────────────────
@router.post("/academic-calendar", response_model=CalendarEntryOut, status_code=201)
async def create_calendar_entry(
    body: CalendarEntryCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CalendarEntryOut:
    try:
        entry = await service.create_calendar_entry(session, actor=actor, payload=body)
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CalendarEntryOut.model_validate(entry)


@router.get("/academic-calendar", response_model=Page[CalendarEntryOut])
async def list_calendar_entries(
    session: SessionDep,
    actor: CurrentUser,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    kind: AcademicCalendarKind | None = None,
    department_id: UUID | None = None,
    include_deleted: bool = False,
    limit: int = Query(100, ge=1, le=400),
    offset: int = Query(0, ge=0),
) -> Page[CalendarEntryOut]:
    items, total = await service.list_calendar_entries(
        session,
        actor=actor,
        from_date=from_date,
        to_date=to_date,
        kind=kind,
        department_id=department_id,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[CalendarEntryOut](
        items=[CalendarEntryOut.model_validate(i) for i in items], total=total
    )


@router.patch("/academic-calendar/{entry_id}", response_model=CalendarEntryOut)
async def patch_calendar_entry(
    entry_id: UUID,
    body: CalendarEntryPatch,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> CalendarEntryOut:
    try:
        entry = await service.patch_calendar_entry(
            session, actor=actor, entry_id=entry_id, payload=body
        )
    except service.AcademicError as e:
        raise _to_http(e) from e
    return CalendarEntryOut.model_validate(entry)


@router.delete("/academic-calendar/{entry_id}", status_code=204)
async def delete_calendar_entry(
    entry_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_calendar_entry(session, actor=actor, entry_id=entry_id)
    except service.AcademicError as e:
        raise _to_http(e) from e
