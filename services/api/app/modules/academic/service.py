"""Business logic for M2 — academic service.

Tenant isolation: every read and write filters by `actor.college_id`, and
every FK target is verified to belong to the same college before being
referenced. Mutating calls write to `audit_logs` before commit.

Soft delete is enforced at this layer; queries always filter
`deleted_at IS NULL` unless callers explicitly opt in via `include_deleted`.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.modules.academic.models import (
    AcademicCalendarEntry,
    AcademicCalendarKind,
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    Room,
    RoomType,
    Section,
    TimetableException,
    TimetableExceptionKind,
    TimetableSlot,
)
from app.modules.academic.schemas import (
    BatchCreate,
    BatchPatch,
    CalendarEntryCreate,
    CalendarEntryPatch,
    ConflictCheckRequest,
    ConflictItem,
    CourseCreate,
    CourseOfferingCreate,
    CourseOfferingPatch,
    CoursePatch,
    DepartmentCreate,
    DepartmentPatch,
    EnrollmentsCreate,
    RoomCreate,
    RoomPatch,
    SectionCreate,
    SectionPatch,
    TimetableExceptionCreate,
    TimetableSlotCreate,
    TimetableSlotPatch,
)
from app.modules.users.models import User, UserRole

# ── Error ────────────────────────────────────────────────────────────────────
class AcademicError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ── Helpers ──────────────────────────────────────────────────────────────────
def _jsonify(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "value"):  # enums
            out[k] = v.value
        else:
            out[k] = str(v)
    return out


async def _get_active(
    session: AsyncSession, model: Any, entity_id: UUID, college_id: UUID
) -> Any:
    row = await session.execute(
        select(model).where(
            model.id == entity_id,
            model.college_id == college_id,
            model.deleted_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


def _require_admin(actor: User) -> None:
    if actor.role != UserRole.admin:
        raise AcademicError("forbidden", "admin role required", 403)


# `timetable.updated` is still owed an event bus — see TODO(events) markers
# below. Until then, M3 is wired in via a direct call: any mutation that
# affects a slot or exception re-materialises the affected offering's
# class_sessions in [today, today+14d]. The work happens in the same
# transaction so partial state is impossible. When the bus lands, replace
# this with `publish('timetable.updated', {offering_id: ...})`.
_MATERIALISE_HORIZON_DAYS = 14


async def _rematerialise_for_event(
    session: AsyncSession, *, offering_id: UUID
) -> None:
    from app.modules.attendance.service import materialise_offering  # lazy

    today = date.today()
    await materialise_offering(
        session,
        offering_id=offering_id,
        from_date=today,
        to_date=today + timedelta(days=_MATERIALISE_HORIZON_DAYS),
    )


# ── Departments ──────────────────────────────────────────────────────────────
async def create_department(
    session: AsyncSession, *, actor: User, payload: DepartmentCreate
) -> Department:
    _require_admin(actor)
    if payload.head_user_id is not None:
        head = await session.get(User, payload.head_user_id)
        if head is None or head.college_id != actor.college_id:
            raise AcademicError("bad_head", "head_user_id invalid", 400)

    dept = Department(
        college_id=actor.college_id,
        name=payload.name.strip(),
        code=payload.code.strip(),
        head_user_id=payload.head_user_id,
    )
    session.add(dept)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "department code already exists", 409) from e

    await write_audit(
        session,
        action="department.create",
        entity_type="department",
        entity_id=dept.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"name": dept.name, "code": dept.code},
    )
    await session.commit()
    await session.refresh(dept)
    return dept


async def list_departments(
    session: AsyncSession,
    *,
    actor: User,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Department], int]:
    stmt = select(Department).where(Department.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(Department.deleted_at.is_(None))
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(Department.code).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_department(
    session: AsyncSession, *, actor: User, dept_id: UUID
) -> Department:
    dept = await _get_active(session, Department, dept_id, actor.college_id)
    if dept is None:
        raise AcademicError("not_found", "department not found", 404)
    return dept


async def patch_department(
    session: AsyncSession, *, actor: User, dept_id: UUID, payload: DepartmentPatch
) -> Department:
    _require_admin(actor)
    dept = await get_department(session, actor=actor, dept_id=dept_id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(dept, field)
        setattr(dept, field, value)
        after[field] = value
    if not after:
        return dept
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "department code already exists", 409) from e

    await write_audit(
        session,
        action="department.update",
        entity_type="department",
        entity_id=dept.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(dept)
    return dept


async def delete_department(
    session: AsyncSession, *, actor: User, dept_id: UUID
) -> None:
    _require_admin(actor)
    dept = await get_department(session, actor=actor, dept_id=dept_id)
    dept.deleted_at = utcnow()
    await write_audit(
        session,
        action="department.delete",
        entity_type="department",
        entity_id=dept.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Courses ──────────────────────────────────────────────────────────────────
async def create_course(
    session: AsyncSession, *, actor: User, payload: CourseCreate
) -> Course:
    _require_admin(actor)
    dept = await _get_active(session, Department, payload.department_id, actor.college_id)
    if dept is None:
        raise AcademicError("bad_department", "department not found in your college", 400)

    course = Course(
        college_id=actor.college_id,
        department_id=payload.department_id,
        code=payload.code.strip(),
        title=payload.title.strip(),
        credits=payload.credits,
        semester=payload.semester,
        course_type=payload.course_type,
    )
    session.add(course)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "course code already exists", 409) from e

    await write_audit(
        session,
        action="course.create",
        entity_type="course",
        entity_id=course.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"code": course.code, "title": course.title, "semester": course.semester},
    )
    await session.commit()
    await session.refresh(course)
    return course


async def list_courses(
    session: AsyncSession,
    *,
    actor: User,
    department_id: UUID | None = None,
    semester: int | None = None,
    course_type: CourseType | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Course], int]:
    stmt = select(Course).where(Course.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(Course.deleted_at.is_(None))
    if department_id is not None:
        stmt = stmt.where(Course.department_id == department_id)
    if semester is not None:
        stmt = stmt.where(Course.semester == semester)
    if course_type is not None:
        stmt = stmt.where(Course.course_type == course_type)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(Course.semester, Course.code).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_course(session: AsyncSession, *, actor: User, course_id: UUID) -> Course:
    course = await _get_active(session, Course, course_id, actor.college_id)
    if course is None:
        raise AcademicError("not_found", "course not found", 404)
    return course


async def patch_course(
    session: AsyncSession, *, actor: User, course_id: UUID, payload: CoursePatch
) -> Course:
    _require_admin(actor)
    course = await get_course(session, actor=actor, course_id=course_id)

    if payload.department_id is not None:
        dept = await _get_active(
            session, Department, payload.department_id, actor.college_id
        )
        if dept is None:
            raise AcademicError("bad_department", "department not found in your college", 400)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(course, field)
        setattr(course, field, value)
        after[field] = value
    if not after:
        return course
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "course code already exists", 409) from e

    await write_audit(
        session,
        action="course.update",
        entity_type="course",
        entity_id=course.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(course)
    return course


async def delete_course(session: AsyncSession, *, actor: User, course_id: UUID) -> None:
    _require_admin(actor)
    course = await get_course(session, actor=actor, course_id=course_id)
    course.deleted_at = utcnow()
    await write_audit(
        session,
        action="course.delete",
        entity_type="course",
        entity_id=course.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Batches ──────────────────────────────────────────────────────────────────
async def create_batch(
    session: AsyncSession, *, actor: User, payload: BatchCreate
) -> Batch:
    _require_admin(actor)
    dept = await _get_active(session, Department, payload.department_id, actor.college_id)
    if dept is None:
        raise AcademicError("bad_department", "department not found in your college", 400)

    batch = Batch(
        college_id=actor.college_id,
        department_id=payload.department_id,
        name=payload.name.strip(),
        admission_year=payload.admission_year,
        program_duration_years=payload.program_duration_years,
        current_semester=payload.current_semester,
    )
    session.add(batch)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_batch",
            "a batch for this department and admission year already exists",
            409,
        ) from e

    await write_audit(
        session,
        action="batch.create",
        entity_type="batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"name": batch.name, "admission_year": batch.admission_year},
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def list_batches(
    session: AsyncSession,
    *,
    actor: User,
    department_id: UUID | None = None,
    admission_year: int | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Batch], int]:
    stmt = select(Batch).where(Batch.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(Batch.deleted_at.is_(None))
    if department_id is not None:
        stmt = stmt.where(Batch.department_id == department_id)
    if admission_year is not None:
        stmt = stmt.where(Batch.admission_year == admission_year)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(Batch.admission_year.desc(), Batch.name)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_batch(session: AsyncSession, *, actor: User, batch_id: UUID) -> Batch:
    batch = await _get_active(session, Batch, batch_id, actor.college_id)
    if batch is None:
        raise AcademicError("not_found", "batch not found", 404)
    return batch


async def patch_batch(
    session: AsyncSession, *, actor: User, batch_id: UUID, payload: BatchPatch
) -> Batch:
    _require_admin(actor)
    batch = await get_batch(session, actor=actor, batch_id=batch_id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(batch, field)
        setattr(batch, field, value)
        after[field] = value
    if not after:
        return batch
    await write_audit(
        session,
        action="batch.update",
        entity_type="batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def delete_batch(session: AsyncSession, *, actor: User, batch_id: UUID) -> None:
    _require_admin(actor)
    batch = await get_batch(session, actor=actor, batch_id=batch_id)
    batch.deleted_at = utcnow()
    await write_audit(
        session,
        action="batch.delete",
        entity_type="batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Sections ─────────────────────────────────────────────────────────────────
async def create_section(
    session: AsyncSession, *, actor: User, payload: SectionCreate
) -> Section:
    _require_admin(actor)
    batch = await _get_active(session, Batch, payload.batch_id, actor.college_id)
    if batch is None:
        raise AcademicError("bad_batch", "batch not found in your college", 400)
    if payload.class_teacher_user_id is not None:
        teacher = await session.get(User, payload.class_teacher_user_id)
        if teacher is None or teacher.college_id != actor.college_id:
            raise AcademicError("bad_teacher", "class teacher invalid", 400)
        if teacher.role not in (UserRole.teacher, UserRole.admin):
            raise AcademicError("bad_teacher", "class teacher must be a teacher", 400)

    section = Section(
        college_id=actor.college_id,
        batch_id=payload.batch_id,
        name=payload.name.strip(),
        class_teacher_user_id=payload.class_teacher_user_id,
    )
    session.add(section)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_section",
            "section with this name already exists in this batch",
            409,
        ) from e

    await write_audit(
        session,
        action="section.create",
        entity_type="section",
        entity_id=section.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"batch_id": str(section.batch_id), "name": section.name},
    )
    await session.commit()
    await session.refresh(section)
    return section


async def list_sections(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Section], int]:
    stmt = select(Section).where(Section.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(Section.deleted_at.is_(None))
    if batch_id is not None:
        stmt = stmt.where(Section.batch_id == batch_id)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(stmt.order_by(Section.name).limit(limit).offset(offset))
    return list(rows.scalars().all()), total


async def get_section(session: AsyncSession, *, actor: User, section_id: UUID) -> Section:
    section = await _get_active(session, Section, section_id, actor.college_id)
    if section is None:
        raise AcademicError("not_found", "section not found", 404)
    return section


async def patch_section(
    session: AsyncSession, *, actor: User, section_id: UUID, payload: SectionPatch
) -> Section:
    _require_admin(actor)
    section = await get_section(session, actor=actor, section_id=section_id)
    if payload.class_teacher_user_id is not None:
        teacher = await session.get(User, payload.class_teacher_user_id)
        if teacher is None or teacher.college_id != actor.college_id:
            raise AcademicError("bad_teacher", "class teacher invalid", 400)
        if teacher.role not in (UserRole.teacher, UserRole.admin):
            raise AcademicError("bad_teacher", "class teacher must be a teacher", 400)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(section, field)
        setattr(section, field, value)
        after[field] = value
    if not after:
        return section
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_section",
            "section with this name already exists in this batch",
            409,
        ) from e
    await write_audit(
        session,
        action="section.update",
        entity_type="section",
        entity_id=section.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(section)
    return section


async def delete_section(
    session: AsyncSession, *, actor: User, section_id: UUID
) -> None:
    _require_admin(actor)
    section = await get_section(session, actor=actor, section_id=section_id)
    section.deleted_at = utcnow()
    await write_audit(
        session,
        action="section.delete",
        entity_type="section",
        entity_id=section.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Enrollments ──────────────────────────────────────────────────────────────
async def add_enrollments(
    session: AsyncSession,
    *,
    actor: User,
    section_id: UUID,
    payload: EnrollmentsCreate,
) -> list[Enrollment]:
    _require_admin(actor)
    section = await get_section(session, actor=actor, section_id=section_id)

    # Validate every student is in the same college and is actually a student.
    students_rows = await session.execute(
        select(User).where(User.id.in_(payload.student_user_ids))
    )
    students = list(students_rows.scalars().all())
    if len(students) != len(payload.student_user_ids):
        raise AcademicError("bad_students", "some student_user_ids are unknown", 400)
    for s in students:
        if s.college_id != actor.college_id:
            raise AcademicError(
                "forbidden", "cross-college enrollment denied", 403
            )
        if s.role != UserRole.student:
            raise AcademicError(
                "bad_students", f"user {s.id} is not a student", 400
            )

    # Skip duplicates (idempotent re-enroll).
    existing = await session.execute(
        select(Enrollment).where(
            Enrollment.section_id == section.id,
            Enrollment.academic_term == payload.academic_term,
            Enrollment.student_user_id.in_(payload.student_user_ids),
            Enrollment.withdrawn_at.is_(None),
        )
    )
    existing_ids = {e.student_user_id for e in existing.scalars().all()}

    created: list[Enrollment] = []
    for sid in payload.student_user_ids:
        if sid in existing_ids:
            continue
        e = Enrollment(
            college_id=actor.college_id,
            student_user_id=sid,
            section_id=section.id,
            academic_term=payload.academic_term,
            semester=payload.semester,
            enrolled_at=utcnow(),
        )
        session.add(e)
        created.append(e)

    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_enrollment", "enrollment already exists", 409
        ) from e

    await write_audit(
        session,
        action="enrollment.create",
        entity_type="section",
        entity_id=section.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "added_student_ids": [str(e.student_user_id) for e in created],
            "academic_term": payload.academic_term,
        },
    )
    # TODO(events): publish user.enrolled for each new enrollment when the
    # event bus exists. M7 (learning engine) will initialise the student
    # knowledge graph on this signal.
    await session.commit()
    for e in created:
        await session.refresh(e)
    return created


async def list_section_enrollments(
    session: AsyncSession, *, actor: User, section_id: UUID
) -> list[Enrollment]:
    await get_section(session, actor=actor, section_id=section_id)
    rows = await session.execute(
        select(Enrollment).where(
            Enrollment.section_id == section_id,
            Enrollment.withdrawn_at.is_(None),
        )
    )
    return list(rows.scalars().all())


async def withdraw_enrollment(
    session: AsyncSession,
    *,
    actor: User,
    section_id: UUID,
    enrollment_id: int,
) -> None:
    _require_admin(actor)
    section = await get_section(session, actor=actor, section_id=section_id)
    row = await session.execute(
        select(Enrollment).where(
            Enrollment.id == enrollment_id,
            Enrollment.section_id == section.id,
            Enrollment.college_id == actor.college_id,
        )
    )
    enr = row.scalar_one_or_none()
    if enr is None:
        raise AcademicError("not_found", "enrollment not found", 404)
    if enr.withdrawn_at is not None:
        return
    enr.withdrawn_at = utcnow()
    await write_audit(
        session,
        action="enrollment.withdraw",
        entity_type="enrollment",
        entity_id=str(enr.id),
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"student_user_id": str(enr.student_user_id)},
    )
    await session.commit()


# ── Rooms ────────────────────────────────────────────────────────────────────
async def create_room(
    session: AsyncSession, *, actor: User, payload: RoomCreate
) -> Room:
    _require_admin(actor)
    room = Room(
        college_id=actor.college_id,
        code=payload.code.strip(),
        building=payload.building,
        floor=payload.floor,
        capacity=payload.capacity,
        room_type=payload.room_type,
        lat=payload.lat,
        lon=payload.lon,
        gps_radius_m=payload.gps_radius_m,
    )
    session.add(room)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "room code already exists", 409) from e

    await write_audit(
        session,
        action="room.create",
        entity_type="room",
        entity_id=room.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"code": room.code, "room_type": room.room_type.value},
    )
    await session.commit()
    await session.refresh(room)
    return room


async def list_rooms(
    session: AsyncSession,
    *,
    actor: User,
    room_type: RoomType | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Room], int]:
    stmt = select(Room).where(Room.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(Room.deleted_at.is_(None))
    if room_type is not None:
        stmt = stmt.where(Room.room_type == room_type)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(stmt.order_by(Room.code).limit(limit).offset(offset))
    return list(rows.scalars().all()), total


async def get_room(session: AsyncSession, *, actor: User, room_id: UUID) -> Room:
    room = await _get_active(session, Room, room_id, actor.college_id)
    if room is None:
        raise AcademicError("not_found", "room not found", 404)
    return room


async def patch_room(
    session: AsyncSession, *, actor: User, room_id: UUID, payload: RoomPatch
) -> Room:
    _require_admin(actor)
    room = await get_room(session, actor=actor, room_id=room_id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(room, field)
        setattr(room, field, value)
        after[field] = value
    if not after:
        return room
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError("code_in_use", "room code already exists", 409) from e

    await write_audit(
        session,
        action="room.update",
        entity_type="room",
        entity_id=room.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(room)
    return room


async def delete_room(session: AsyncSession, *, actor: User, room_id: UUID) -> None:
    _require_admin(actor)
    room = await get_room(session, actor=actor, room_id=room_id)
    room.deleted_at = utcnow()
    await write_audit(
        session,
        action="room.delete",
        entity_type="room",
        entity_id=room.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Course offerings ─────────────────────────────────────────────────────────
async def create_offering(
    session: AsyncSession, *, actor: User, payload: CourseOfferingCreate
) -> CourseOffering:
    _require_admin(actor)
    course = await _get_active(session, Course, payload.course_id, actor.college_id)
    if course is None:
        raise AcademicError("bad_course", "course not found in your college", 400)
    section = await _get_active(session, Section, payload.section_id, actor.college_id)
    if section is None:
        raise AcademicError("bad_section", "section not found in your college", 400)
    teacher = await session.get(User, payload.teacher_user_id)
    if teacher is None or teacher.college_id != actor.college_id:
        raise AcademicError("bad_teacher", "teacher invalid", 400)
    if teacher.role not in (UserRole.teacher, UserRole.admin):
        raise AcademicError("bad_teacher", "teacher must be a teacher", 400)

    offering = CourseOffering(
        college_id=actor.college_id,
        course_id=payload.course_id,
        section_id=payload.section_id,
        teacher_user_id=payload.teacher_user_id,
        academic_term=payload.academic_term,
        semester=payload.semester,
    )
    session.add(offering)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_offering",
            "this course is already offered to this section in that term",
            409,
        ) from e

    await write_audit(
        session,
        action="course_offering.create",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "course_id": str(offering.course_id),
            "section_id": str(offering.section_id),
            "teacher_user_id": str(offering.teacher_user_id),
            "academic_term": offering.academic_term,
        },
    )
    await session.commit()
    await session.refresh(offering)
    return offering


async def list_offerings(
    session: AsyncSession,
    *,
    actor: User,
    section_id: UUID | None = None,
    course_id: UUID | None = None,
    teacher_user_id: UUID | None = None,
    academic_term: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CourseOffering], int]:
    stmt = select(CourseOffering).where(CourseOffering.college_id == actor.college_id)
    if not include_deleted:
        stmt = stmt.where(CourseOffering.deleted_at.is_(None))
    if section_id is not None:
        stmt = stmt.where(CourseOffering.section_id == section_id)
    if course_id is not None:
        stmt = stmt.where(CourseOffering.course_id == course_id)
    if teacher_user_id is not None:
        stmt = stmt.where(CourseOffering.teacher_user_id == teacher_user_id)
    if academic_term is not None:
        stmt = stmt.where(CourseOffering.academic_term == academic_term)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(CourseOffering.academic_term.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_offering(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> CourseOffering:
    offering = await _get_active(session, CourseOffering, offering_id, actor.college_id)
    if offering is None:
        raise AcademicError("not_found", "course offering not found", 404)
    return offering


async def patch_offering(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    payload: CourseOfferingPatch,
) -> CourseOffering:
    _require_admin(actor)
    offering = await get_offering(session, actor=actor, offering_id=offering_id)
    # Only `is_active` is patchable in-place; teacher swaps require soft-delete
    # + new row (otherwise M4 marks would silently rewrite historical authorship).
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(offering, field)
        setattr(offering, field, value)
        after[field] = value
    if not after:
        return offering
    await write_audit(
        session,
        action="course_offering.update",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(offering)
    return offering


async def delete_offering(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> None:
    _require_admin(actor)
    offering = await get_offering(session, actor=actor, offering_id=offering_id)
    offering.deleted_at = utcnow()
    await write_audit(
        session,
        action="course_offering.delete",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Timetable slots ──────────────────────────────────────────────────────────
async def _ensure_slot_targets(
    session: AsyncSession, *, actor: User, offering_id: UUID, room_id: UUID | None
) -> CourseOffering:
    offering = await _get_active(session, CourseOffering, offering_id, actor.college_id)
    if offering is None:
        raise AcademicError("bad_offering", "course offering not found", 400)
    if room_id is not None:
        room = await _get_active(session, Room, room_id, actor.college_id)
        if room is None:
            raise AcademicError("bad_room", "room not found in your college", 400)
    return offering


async def check_timetable_conflict(
    session: AsyncSession, *, actor: User, payload: ConflictCheckRequest
) -> list[ConflictItem]:
    conflicts: list[ConflictItem] = []

    base_filters = [
        TimetableSlot.college_id == actor.college_id,
        TimetableSlot.deleted_at.is_(None),
        TimetableSlot.day_of_week == payload.day_of_week,
        TimetableSlot.start_time < payload.end_time,
        TimetableSlot.end_time > payload.start_time,
        TimetableSlot.effective_from <= payload.effective_until,
        TimetableSlot.effective_until >= payload.effective_from,
    ]
    if payload.exclude_slot_id is not None:
        base_filters.append(TimetableSlot.id != payload.exclude_slot_id)

    # Room conflicts
    if payload.room_id is not None:
        rows = await session.execute(
            select(TimetableSlot).where(
                and_(*base_filters, TimetableSlot.room_id == payload.room_id)
            )
        )
        for s in rows.scalars().all():
            conflicts.append(
                ConflictItem(
                    type="room",
                    slot_id=s.id,
                    course_offering_id=s.course_offering_id,
                    reason=(
                        f"Room booked {_day_name(s.day_of_week)} "
                        f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}"
                    ),
                )
            )

    # Teacher conflicts
    if payload.teacher_user_id is not None:
        rows = await session.execute(
            select(TimetableSlot, CourseOffering)
            .join(CourseOffering, CourseOffering.id == TimetableSlot.course_offering_id)
            .where(
                and_(
                    *base_filters,
                    CourseOffering.teacher_user_id == payload.teacher_user_id,
                    CourseOffering.deleted_at.is_(None),
                )
            )
        )
        for s, _co in rows.all():
            conflicts.append(
                ConflictItem(
                    type="teacher",
                    slot_id=s.id,
                    course_offering_id=s.course_offering_id,
                    reason=(
                        f"Teacher booked {_day_name(s.day_of_week)} "
                        f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}"
                    ),
                )
            )

    # Section conflicts
    if payload.section_id is not None:
        rows = await session.execute(
            select(TimetableSlot, CourseOffering)
            .join(CourseOffering, CourseOffering.id == TimetableSlot.course_offering_id)
            .where(
                and_(
                    *base_filters,
                    CourseOffering.section_id == payload.section_id,
                    CourseOffering.deleted_at.is_(None),
                )
            )
        )
        for s, _co in rows.all():
            conflicts.append(
                ConflictItem(
                    type="section",
                    slot_id=s.id,
                    course_offering_id=s.course_offering_id,
                    reason=(
                        f"Section already has a class {_day_name(s.day_of_week)} "
                        f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}"
                    ),
                )
            )

    return conflicts


def _day_name(d: int) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]


async def create_timetable_slot(
    session: AsyncSession,
    *,
    actor: User,
    payload: TimetableSlotCreate,
    force: bool = False,
) -> TimetableSlot:
    _require_admin(actor)
    offering = await _ensure_slot_targets(
        session, actor=actor, offering_id=payload.course_offering_id, room_id=payload.room_id
    )

    if payload.end_time <= payload.start_time:
        raise AcademicError("bad_time", "end_time must be after start_time", 400)
    if payload.effective_until < payload.effective_from:
        raise AcademicError(
            "bad_date_range", "effective_until must be >= effective_from", 400
        )

    conflicts = await check_timetable_conflict(
        session,
        actor=actor,
        payload=ConflictCheckRequest(
            room_id=payload.room_id,
            teacher_user_id=offering.teacher_user_id,
            section_id=offering.section_id,
            day_of_week=payload.day_of_week,
            start_time=payload.start_time,
            end_time=payload.end_time,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
        ),
    )
    if conflicts and not force:
        raise AcademicError(
            "conflict",
            "schedule conflicts detected — pass force=true to override",
            409,
        )

    slot = TimetableSlot(
        college_id=actor.college_id,
        course_offering_id=offering.id,
        room_id=payload.room_id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
    )
    session.add(slot)
    await session.flush()

    await write_audit(
        session,
        action="timetable_slot.create",
        entity_type="timetable_slot",
        entity_id=slot.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "course_offering_id": str(slot.course_offering_id),
            "room_id": str(slot.room_id) if slot.room_id else None,
            "day_of_week": slot.day_of_week,
            "start_time": slot.start_time.isoformat(),
            "end_time": slot.end_time.isoformat(),
            "force_override": bool(conflicts) and force,
        },
    )
    await _rematerialise_for_event(session, offering_id=slot.course_offering_id)
    # TODO(events): publish timetable.updated for M5 (re-target announcements).
    # M3's materialiser is invoked directly above until the bus lands.
    await session.commit()
    await session.refresh(slot)
    return slot


async def patch_timetable_slot(
    session: AsyncSession,
    *,
    actor: User,
    slot_id: UUID,
    payload: TimetableSlotPatch,
    force: bool = False,
) -> TimetableSlot:
    _require_admin(actor)
    slot = await _get_active(session, TimetableSlot, slot_id, actor.college_id)
    if slot is None:
        raise AcademicError("not_found", "timetable slot not found", 404)

    # Apply changes locally first so we conflict-check the prospective state.
    fields = payload.model_dump(exclude_unset=True)
    if "room_id" in fields and fields["room_id"] is not None:
        room = await _get_active(session, Room, fields["room_id"], actor.college_id)
        if room is None:
            raise AcademicError("bad_room", "room not found in your college", 400)

    new_room = fields.get("room_id", slot.room_id)
    new_dow = fields.get("day_of_week", slot.day_of_week)
    new_start = fields.get("start_time", slot.start_time)
    new_end = fields.get("end_time", slot.end_time)
    new_from = fields.get("effective_from", slot.effective_from)
    new_until = fields.get("effective_until", slot.effective_until)

    if new_end <= new_start:
        raise AcademicError("bad_time", "end_time must be after start_time", 400)
    if new_until < new_from:
        raise AcademicError(
            "bad_date_range", "effective_until must be >= effective_from", 400
        )

    offering = await session.get(CourseOffering, slot.course_offering_id)
    if offering is None:
        raise AcademicError("bad_offering", "underlying offering missing", 400)

    conflicts = await check_timetable_conflict(
        session,
        actor=actor,
        payload=ConflictCheckRequest(
            room_id=new_room,
            teacher_user_id=offering.teacher_user_id,
            section_id=offering.section_id,
            day_of_week=new_dow,
            start_time=new_start,
            end_time=new_end,
            effective_from=new_from,
            effective_until=new_until,
            exclude_slot_id=slot.id,
        ),
    )
    if conflicts and not force:
        raise AcademicError(
            "conflict",
            "schedule conflicts detected — pass force=true to override",
            409,
        )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in fields.items():
        before[field] = getattr(slot, field)
        setattr(slot, field, value)
        after[field] = value
    await write_audit(
        session,
        action="timetable_slot.update",
        entity_type="timetable_slot",
        entity_id=slot.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await _rematerialise_for_event(session, offering_id=slot.course_offering_id)
    # TODO(events): publish timetable.updated (non-M3 consumers).
    await session.commit()
    await session.refresh(slot)
    return slot


async def delete_timetable_slot(
    session: AsyncSession, *, actor: User, slot_id: UUID
) -> None:
    _require_admin(actor)
    slot = await _get_active(session, TimetableSlot, slot_id, actor.college_id)
    if slot is None:
        raise AcademicError("not_found", "timetable slot not found", 404)
    slot.deleted_at = utcnow()
    await write_audit(
        session,
        action="timetable_slot.delete",
        entity_type="timetable_slot",
        entity_id=slot.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    # Existing class_sessions for this slot aren't deleted — admins manage
    # historical sessions explicitly. Re-materialise so future dates that
    # had been derived from this slot stop appearing (the candidate set
    # will no longer include them, but UPSERT-only never deletes; this is
    # documented behavior). New future dates will simply not be created.
    await _rematerialise_for_event(session, offering_id=slot.course_offering_id)
    # TODO(events): publish timetable.updated (non-M3 consumers).
    await session.commit()


async def get_timetable_for_section(
    session: AsyncSession,
    *,
    actor: User,
    section_id: UUID,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[TimetableSlot], list[TimetableException]]:
    section = await get_section(session, actor=actor, section_id=section_id)

    slots_stmt = (
        select(TimetableSlot)
        .join(
            CourseOffering, CourseOffering.id == TimetableSlot.course_offering_id
        )
        .where(
            TimetableSlot.college_id == actor.college_id,
            TimetableSlot.deleted_at.is_(None),
            CourseOffering.section_id == section.id,
            CourseOffering.deleted_at.is_(None),
        )
    )
    if from_date is not None:
        slots_stmt = slots_stmt.where(TimetableSlot.effective_until >= from_date)
    if to_date is not None:
        slots_stmt = slots_stmt.where(TimetableSlot.effective_from <= to_date)
    slots_rows = await session.execute(
        slots_stmt.order_by(TimetableSlot.day_of_week, TimetableSlot.start_time)
    )
    slots = list(slots_rows.scalars().all())

    exc_stmt = (
        select(TimetableException)
        .join(
            CourseOffering,
            CourseOffering.id == TimetableException.course_offering_id,
        )
        .where(
            TimetableException.college_id == actor.college_id,
            CourseOffering.section_id == section.id,
        )
    )
    if from_date is not None:
        exc_stmt = exc_stmt.where(TimetableException.exception_date >= from_date)
    if to_date is not None:
        exc_stmt = exc_stmt.where(TimetableException.exception_date <= to_date)
    exc_rows = await session.execute(
        exc_stmt.order_by(TimetableException.exception_date)
    )
    exceptions = list(exc_rows.scalars().all())
    return slots, exceptions


# ── Timetable exceptions ─────────────────────────────────────────────────────
async def create_timetable_exception(
    session: AsyncSession, *, actor: User, payload: TimetableExceptionCreate
) -> TimetableException:
    _require_admin(actor)
    offering = await _get_active(
        session, CourseOffering, payload.course_offering_id, actor.college_id
    )
    if offering is None:
        raise AcademicError("bad_offering", "course offering not found", 400)

    if payload.new_room_id is not None:
        room = await _get_active(session, Room, payload.new_room_id, actor.college_id)
        if room is None:
            raise AcademicError("bad_room", "new_room_id not found in your college", 400)

    # Mirror the DB check constraints so we surface a clean error.
    k = payload.kind
    if k == TimetableExceptionKind.cancel and (
        payload.new_room_id is not None
        or payload.new_start_time is not None
        or payload.new_end_time is not None
    ):
        raise AcademicError(
            "bad_exception",
            "cancel exceptions cannot carry new_room / new_start_time / new_end_time",
            400,
        )
    if k == TimetableExceptionKind.reschedule and (
        payload.new_start_time is None or payload.new_end_time is None
    ):
        raise AcademicError(
            "bad_exception", "reschedule requires new_start_time and new_end_time", 400
        )
    if k == TimetableExceptionKind.room_change and payload.new_room_id is None:
        raise AcademicError("bad_exception", "room_change requires new_room_id", 400)
    if k == TimetableExceptionKind.extra and (
        payload.new_start_time is None or payload.new_end_time is None
    ):
        raise AcademicError(
            "bad_exception", "extra requires new_start_time and new_end_time", 400
        )

    exc = TimetableException(
        college_id=actor.college_id,
        course_offering_id=offering.id,
        original_slot_id=None,
        exception_date=payload.exception_date,
        kind=payload.kind,
        new_room_id=payload.new_room_id,
        new_start_time=payload.new_start_time,
        new_end_time=payload.new_end_time,
        reason=payload.reason,
        created_by=actor.id,
    )

    # For non-extra kinds, link to the matching recurring slot on that day.
    if k != TimetableExceptionKind.extra:
        slot_rows = await session.execute(
            select(TimetableSlot).where(
                TimetableSlot.course_offering_id == offering.id,
                TimetableSlot.deleted_at.is_(None),
                TimetableSlot.day_of_week == payload.exception_date.weekday(),
                TimetableSlot.effective_from <= payload.exception_date,
                TimetableSlot.effective_until >= payload.exception_date,
            )
        )
        slot = slot_rows.scalars().first()
        if slot is None:
            raise AcademicError(
                "no_matching_slot",
                "no recurring slot covers this date for that offering",
                400,
            )
        exc.original_slot_id = slot.id

    session.add(exc)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise AcademicError(
            "duplicate_exception",
            "an exception for this slot on this date already exists",
            409,
        ) from e

    await write_audit(
        session,
        action="timetable_exception.create",
        entity_type="timetable_exception",
        entity_id=exc.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "kind": exc.kind.value,
            "exception_date": exc.exception_date.isoformat(),
            "offering_id": str(exc.course_offering_id),
        },
    )
    await _rematerialise_for_event(session, offering_id=exc.course_offering_id)
    # TODO(events): publish timetable.updated (non-M3 consumers).
    await session.commit()
    await session.refresh(exc)
    return exc


async def delete_timetable_exception(
    session: AsyncSession, *, actor: User, exception_id: UUID
) -> None:
    _require_admin(actor)
    row = await session.execute(
        select(TimetableException).where(
            TimetableException.id == exception_id,
            TimetableException.college_id == actor.college_id,
        )
    )
    exc = row.scalar_one_or_none()
    if exc is None:
        raise AcademicError("not_found", "exception not found", 404)
    offering_id = exc.course_offering_id
    await session.delete(exc)
    await write_audit(
        session,
        action="timetable_exception.delete",
        entity_type="timetable_exception",
        entity_id=exception_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await _rematerialise_for_event(session, offering_id=offering_id)
    # TODO(events): publish timetable.updated (non-M3 consumers).
    await session.commit()


# ── Academic calendar ────────────────────────────────────────────────────────
async def create_calendar_entry(
    session: AsyncSession, *, actor: User, payload: CalendarEntryCreate
) -> AcademicCalendarEntry:
    _require_admin(actor)
    if payload.applies_to_department_id is not None:
        dept = await _get_active(
            session, Department, payload.applies_to_department_id, actor.college_id
        )
        if dept is None:
            raise AcademicError("bad_department", "department invalid", 400)

    entry = AcademicCalendarEntry(
        college_id=actor.college_id,
        entry_date=payload.entry_date,
        kind=payload.kind,
        title=payload.title.strip(),
        applies_to_department_id=payload.applies_to_department_id,
        cancels_classes=payload.cancels_classes,
    )
    session.add(entry)
    await session.flush()

    await write_audit(
        session,
        action="academic_calendar.create",
        entity_type="academic_calendar",
        entity_id=entry.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "entry_date": entry.entry_date.isoformat(),
            "kind": entry.kind.value,
            "title": entry.title,
        },
    )
    await session.commit()
    await session.refresh(entry)
    return entry


async def list_calendar_entries(
    session: AsyncSession,
    *,
    actor: User,
    from_date: date | None = None,
    to_date: date | None = None,
    kind: AcademicCalendarKind | None = None,
    department_id: UUID | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AcademicCalendarEntry], int]:
    stmt = select(AcademicCalendarEntry).where(
        AcademicCalendarEntry.college_id == actor.college_id
    )
    if not include_deleted:
        stmt = stmt.where(AcademicCalendarEntry.deleted_at.is_(None))
    if from_date is not None:
        stmt = stmt.where(AcademicCalendarEntry.entry_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(AcademicCalendarEntry.entry_date <= to_date)
    if kind is not None:
        stmt = stmt.where(AcademicCalendarEntry.kind == kind)
    if department_id is not None:
        stmt = stmt.where(
            or_(
                AcademicCalendarEntry.applies_to_department_id == department_id,
                AcademicCalendarEntry.applies_to_department_id.is_(None),
            )
        )
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(AcademicCalendarEntry.entry_date).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def patch_calendar_entry(
    session: AsyncSession,
    *,
    actor: User,
    entry_id: UUID,
    payload: CalendarEntryPatch,
) -> AcademicCalendarEntry:
    _require_admin(actor)
    entry = await _get_active(
        session, AcademicCalendarEntry, entry_id, actor.college_id
    )
    if entry is None:
        raise AcademicError("not_found", "calendar entry not found", 404)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(entry, field)
        setattr(entry, field, value)
        after[field] = value
    if not after:
        return entry
    await write_audit(
        session,
        action="academic_calendar.update",
        entity_type="academic_calendar",
        entity_id=entry.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(entry)
    return entry


async def delete_calendar_entry(
    session: AsyncSession, *, actor: User, entry_id: UUID
) -> None:
    _require_admin(actor)
    entry = await _get_active(
        session, AcademicCalendarEntry, entry_id, actor.college_id
    )
    if entry is None:
        raise AcademicError("not_found", "calendar entry not found", 404)
    entry.deleted_at = utcnow()
    await write_audit(
        session,
        action="academic_calendar.delete",
        entity_type="academic_calendar",
        entity_id=entry.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()
