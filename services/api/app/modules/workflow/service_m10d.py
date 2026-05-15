"""Service layer for M10d — internal deadlines, CIE scheduling, tasks,
and the helpers consumed by M3/M4 rework via `is_offering_frozen`.

Three concerns share this file; they're glued together by the same
WorkflowError mapping the rest of the workflow module uses, and they
all emit M10d events through `app.core.event_bus.publish` (subscriber
side wires up in `event_bus_subscriber.py`).

1. **Internal deadlines** — three kinds, three authorities:
     institutional_hard   admin owns; one row per (college, term).
     department_soft      HOD owns; one row per (college, term, dept).
     per_course_freeze    teacher of offering owns; one row per offering.
   Freeze flips `is_frozen=true` and emits `internal_deadline.crossed`
   so subscribers (admin_notifications writer, future M3/M4 freeze
   guards) can react. The freeze is what `is_offering_frozen()` reads.

2. **CIE schedule** — per offering, CIE-1/2/3 with date/time/venue.
   HOD-of-offering's-dept OR teacher of offering can create/edit drafts;
   HOD-only can `publish`. Publishing flips `is_published=true`.

3. **Tasks** — HOD assigns invigilation/paper-setting/evaluation/makeup
   to teachers in their dept. Assignee transitions accept/decline/
   complete; assigner can cancel. Cross-dept assignment is forbidden so
   the boundary stays clean for M9 reporting.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.event_bus import publish as publish_event
from app.modules.academic.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    Room,
)
from app.modules.users.models import User, UserRole
from app.modules.workflow.models import (
    CIESchedule,
    InternalDeadline,
    Task,
    TaskStatus,
    TaskType,
)
from app.modules.workflow.service import WorkflowError
from app.modules.workflow.service_m10c import _course_for_offering, _get_offering_or_404


# ── Authority helpers ───────────────────────────────────────────────────────
def _require_admin(actor: User) -> None:
    if actor.role != UserRole.admin:
        raise WorkflowError("forbidden", "admin only", 403)


def _require_hod(actor: User) -> None:
    if actor.role != UserRole.hod or actor.hod_of_department_id is None:
        raise WorkflowError("forbidden", "HOD only", 403)


def _require_hod_for_dept(actor: User, department_id: UUID) -> None:
    if (
        actor.role != UserRole.hod
        or actor.hod_of_department_id != department_id
    ):
        raise WorkflowError("forbidden", "HOD of that department only", 403)


# ── Internal deadlines ──────────────────────────────────────────────────────
async def _get_deadline_or_404(
    session: AsyncSession, *, deadline_id: UUID, college_id: UUID
) -> InternalDeadline:
    row = await session.execute(
        select(InternalDeadline).where(
            InternalDeadline.id == deadline_id,
            InternalDeadline.college_id == college_id,
            InternalDeadline.deleted_at.is_(None),
        )
    )
    d = row.scalar_one_or_none()
    if d is None:
        raise WorkflowError("not_found", "deadline not found", 404)
    return d


def _validate_deadline_authority(
    actor: User,
    *,
    kind: str,
    department_id: UUID | None,
    offering_dept_id: UUID | None,
) -> None:
    """Each kind has its own owner. offering_dept_id is the dept of the
    course whose offering this deadline pins (for per_course_freeze).
    """
    if kind == "institutional_hard":
        _require_admin(actor)
        return
    if kind == "department_soft":
        if department_id is None:
            raise WorkflowError("bad_kind", "department_soft needs department_id", 400)
        _require_hod_for_dept(actor, department_id)
        return
    if kind == "per_course_freeze":
        # Teacher of the offering, OR HOD of the offering's course's dept.
        if offering_dept_id is None:
            raise WorkflowError(
                "bad_kind", "per_course_freeze needs an offering's dept", 400
            )
        # Caller (route) has loaded the offering; for the freeze path the
        # actor is matched against teacher_user_id by the calling helper.
        if actor.role == UserRole.hod and actor.hod_of_department_id == offering_dept_id:
            return
        # Teacher check has to happen at the call site where the offering
        # is in scope; treat 'teacher' here as a pass-through.
        if actor.role == UserRole.teacher:
            return
        raise WorkflowError(
            "forbidden",
            "per_course_freeze: only the teacher of the offering or the HOD",
            403,
        )
    raise WorkflowError("bad_kind", f"unknown deadline kind '{kind}'", 400)


async def create_deadline(
    session: AsyncSession,
    *,
    actor: User,
    academic_term_id: UUID,
    deadline_at: datetime,
    kind: str,
    department_id: UUID | None,
    course_offering_id: UUID | None,
    notes: str | None,
) -> InternalDeadline:
    # Term must belong to the actor's college.
    term = await session.get(AcademicTerm, academic_term_id)
    if (
        term is None
        or term.college_id != actor.college_id
        or term.deleted_at is not None
    ):
        raise WorkflowError("bad_term", "term not found", 400)

    offering_dept_id: UUID | None = None
    if course_offering_id is not None:
        offering = await _get_offering_or_404(
            session, offering_id=course_offering_id, college_id=actor.college_id
        )
        course = await _course_for_offering(session, offering=offering)
        offering_dept_id = course.department_id
        # If per_course_freeze and actor is teacher, must own the offering.
        if (
            kind == "per_course_freeze"
            and actor.role == UserRole.teacher
            and offering.teacher_user_id != actor.id
        ):
            raise WorkflowError(
                "forbidden", "you don't teach this offering", 403
            )

    if department_id is not None:
        dept = await session.get(Department, department_id)
        if (
            dept is None
            or dept.college_id != actor.college_id
            or dept.deleted_at is not None
        ):
            raise WorkflowError("bad_dept", "department not found", 400)

    _validate_deadline_authority(
        actor,
        kind=kind,
        department_id=department_id,
        offering_dept_id=offering_dept_id,
    )

    # Soft-uniqueness: one institutional_hard per (college, term); one
    # department_soft per (college, term, dept); one per_course_freeze per
    # (college, term, dept, offering). Enforce in-app since there's no
    # partial unique index for these in 0007.
    where = [
        InternalDeadline.college_id == actor.college_id,
        InternalDeadline.academic_term_id == academic_term_id,
        InternalDeadline.kind == kind,
        InternalDeadline.deleted_at.is_(None),
    ]
    if kind == "institutional_hard":
        where.append(InternalDeadline.department_id.is_(None))
        where.append(InternalDeadline.course_offering_id.is_(None))
    elif kind == "department_soft":
        where.append(InternalDeadline.department_id == department_id)
        where.append(InternalDeadline.course_offering_id.is_(None))
    else:  # per_course_freeze
        where.append(InternalDeadline.course_offering_id == course_offering_id)
    exists = (
        await session.execute(
            select(InternalDeadline.id).where(*where)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise WorkflowError(
            "duplicate_deadline",
            f"a {kind} deadline already exists for this scope",
            409,
        )

    d = InternalDeadline(
        college_id=actor.college_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        course_offering_id=course_offering_id,
        deadline_at=deadline_at,
        kind=kind,
        set_by_user_id=actor.id,
        is_frozen=False,
        notes=notes,
    )
    session.add(d)
    await session.flush()
    await write_audit(
        session,
        action="internal_deadline.create",
        entity_type="internal_deadline",
        entity_id=d.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "kind": kind,
            "deadline_at": deadline_at.isoformat(),
            "department_id": str(department_id) if department_id else None,
            "course_offering_id": (
                str(course_offering_id) if course_offering_id else None
            ),
        },
    )
    await session.commit()
    await session.refresh(d)
    return d


async def list_deadlines(
    session: AsyncSession,
    *,
    actor: User,
    academic_term_id: UUID | None = None,
    kind: str | None = None,
) -> list[InternalDeadline]:
    """Visible to admin/HOD/teacher. Teachers see only their own per-course
    freezes plus the institutional + dept-soft rows (so they know when the
    institutional hard-stop lands)."""
    stmt = select(InternalDeadline).where(
        InternalDeadline.college_id == actor.college_id,
        InternalDeadline.deleted_at.is_(None),
    )
    if academic_term_id is not None:
        stmt = stmt.where(InternalDeadline.academic_term_id == academic_term_id)
    if kind is not None:
        stmt = stmt.where(InternalDeadline.kind == kind)

    if actor.role == UserRole.admin:
        pass  # see everything
    elif actor.role == UserRole.hod:
        if actor.hod_of_department_id is None:
            raise WorkflowError("hod_dept_missing", "HOD has no department", 400)
        # HOD sees institutional + own-dept rows + per-course rows on
        # offerings whose course belongs to their dept.
        from app.modules.workflow.models import (  # local — cycle guard
            InternalDeadline as _ID,
        )

        own_dept_courses = select(Course.id).where(
            Course.department_id == actor.hod_of_department_id,
            Course.college_id == actor.college_id,
        )
        own_dept_offerings = select(CourseOffering.id).where(
            CourseOffering.college_id == actor.college_id,
            CourseOffering.course_id.in_(own_dept_courses),
        )
        stmt = stmt.where(
            or_(
                _ID.kind == "institutional_hard",
                and_(
                    _ID.kind == "department_soft",
                    _ID.department_id == actor.hod_of_department_id,
                ),
                and_(
                    _ID.kind == "per_course_freeze",
                    _ID.course_offering_id.in_(own_dept_offerings),
                ),
            )
        )
    elif actor.role == UserRole.teacher:
        # Teachers see institutional + dept-soft rows for context + their
        # own offering's per-course-freeze rows.
        own_offerings = select(CourseOffering.id).where(
            CourseOffering.college_id == actor.college_id,
            CourseOffering.teacher_user_id == actor.id,
        )
        stmt = stmt.where(
            or_(
                InternalDeadline.kind == "institutional_hard",
                InternalDeadline.kind == "department_soft",
                and_(
                    InternalDeadline.kind == "per_course_freeze",
                    InternalDeadline.course_offering_id.in_(own_offerings),
                ),
            )
        )
    else:
        raise WorkflowError("forbidden", "admin/HOD/teacher only", 403)

    rows = await session.execute(
        stmt.order_by(InternalDeadline.deadline_at)
    )
    return list(rows.scalars().all())


async def deadline_to_dict(
    session: AsyncSession, d: InternalDeadline
) -> dict[str, Any]:
    """Denormalise term code, dept code, offering code for the UI."""
    term = await session.get(AcademicTerm, d.academic_term_id)
    dept = (
        await session.get(Department, d.department_id)
        if d.department_id is not None
        else None
    )
    offering = (
        await session.get(CourseOffering, d.course_offering_id)
        if d.course_offering_id is not None
        else None
    )
    course = (
        await session.get(Course, offering.course_id) if offering is not None else None
    )
    setter = await session.get(User, d.set_by_user_id)
    return {
        "id": d.id,
        "college_id": d.college_id,
        "academic_term_id": d.academic_term_id,
        "academic_term_code": term.code if term else None,
        "department_id": d.department_id,
        "department_code": dept.code if dept else None,
        "course_offering_id": d.course_offering_id,
        "course_code": course.code if course else None,
        "deadline_at": d.deadline_at,
        "kind": d.kind,
        "set_by_user_id": d.set_by_user_id,
        "set_by_name": setter.name if setter else None,
        "is_frozen": d.is_frozen,
        "frozen_at": d.frozen_at,
        "frozen_by_user_id": d.frozen_by_user_id,
        "notes": d.notes,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


async def patch_deadline(
    session: AsyncSession,
    *,
    actor: User,
    deadline_id: UUID,
    deadline_at: datetime | None,
    notes: str | None,
) -> InternalDeadline:
    d = await _get_deadline_or_404(
        session, deadline_id=deadline_id, college_id=actor.college_id
    )
    offering_dept_id: UUID | None = None
    if d.course_offering_id is not None:
        offering = await session.get(CourseOffering, d.course_offering_id)
        if offering is not None:
            course = await session.get(Course, offering.course_id)
            offering_dept_id = course.department_id if course else None
            if (
                d.kind == "per_course_freeze"
                and actor.role == UserRole.teacher
                and offering.teacher_user_id != actor.id
            ):
                raise WorkflowError("forbidden", "not your offering", 403)
    _validate_deadline_authority(
        actor,
        kind=d.kind,
        department_id=d.department_id,
        offering_dept_id=offering_dept_id,
    )

    if d.is_frozen:
        raise WorkflowError(
            "deadline_frozen",
            "cannot edit a frozen deadline — unfreeze first",
            409,
        )

    if deadline_at is not None:
        d.deadline_at = deadline_at
    if notes is not None:
        d.notes = notes

    await write_audit(
        session,
        action="internal_deadline.patch",
        entity_type="internal_deadline",
        entity_id=d.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"deadline_at": d.deadline_at.isoformat(), "notes": d.notes},
    )
    await session.commit()
    await session.refresh(d)
    return d


async def delete_deadline(
    session: AsyncSession, *, actor: User, deadline_id: UUID
) -> None:
    d = await _get_deadline_or_404(
        session, deadline_id=deadline_id, college_id=actor.college_id
    )
    offering_dept_id: UUID | None = None
    if d.course_offering_id is not None:
        offering = await session.get(CourseOffering, d.course_offering_id)
        if offering is not None:
            course = await session.get(Course, offering.course_id)
            offering_dept_id = course.department_id if course else None
            if (
                d.kind == "per_course_freeze"
                and actor.role == UserRole.teacher
                and offering.teacher_user_id != actor.id
            ):
                raise WorkflowError("forbidden", "not your offering", 403)
    _validate_deadline_authority(
        actor,
        kind=d.kind,
        department_id=d.department_id,
        offering_dept_id=offering_dept_id,
    )

    d.deleted_at = utcnow()
    await write_audit(
        session,
        action="internal_deadline.delete",
        entity_type="internal_deadline",
        entity_id=d.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


async def freeze_deadline(
    session: AsyncSession,
    *,
    actor: User,
    deadline_id: UUID,
    is_frozen: bool,
    notes: str | None,
) -> tuple[InternalDeadline, dict[str, Any] | None]:
    """Flip the freeze bit. Emits `internal_deadline.crossed` only on the
    false→true transition; unfreeze is silent (admin/HOD path, no event).
    """
    d = await _get_deadline_or_404(
        session, deadline_id=deadline_id, college_id=actor.college_id
    )
    offering_dept_id: UUID | None = None
    if d.course_offering_id is not None:
        offering = await session.get(CourseOffering, d.course_offering_id)
        if offering is not None:
            course = await session.get(Course, offering.course_id)
            offering_dept_id = course.department_id if course else None
            if (
                d.kind == "per_course_freeze"
                and actor.role == UserRole.teacher
                and offering.teacher_user_id != actor.id
            ):
                raise WorkflowError("forbidden", "not your offering", 403)
    _validate_deadline_authority(
        actor,
        kind=d.kind,
        department_id=d.department_id,
        offering_dept_id=offering_dept_id,
    )

    became_frozen = is_frozen and not d.is_frozen
    d.is_frozen = is_frozen
    if is_frozen:
        d.frozen_at = utcnow()
        d.frozen_by_user_id = actor.id
        if notes:
            d.notes = notes
    else:
        d.frozen_at = None
        d.frozen_by_user_id = None

    await write_audit(
        session,
        action="internal_deadline.freeze" if is_frozen else "internal_deadline.unfreeze",
        entity_type="internal_deadline",
        entity_id=d.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"is_frozen": is_frozen, "notes": d.notes},
    )
    await session.commit()
    await session.refresh(d)

    event: dict[str, Any] | None = None
    if became_frozen:
        event = await publish_event(
            "internal_deadline.crossed",
            {
                "internal_deadline_id": str(d.id),
                "kind": d.kind,
                "academic_term_id": str(d.academic_term_id),
                "department_id": str(d.department_id) if d.department_id else None,
                "course_offering_id": (
                    str(d.course_offering_id) if d.course_offering_id else None
                ),
                "deadline_at": d.deadline_at.isoformat(),
                "frozen_at": d.frozen_at.isoformat() if d.frozen_at else None,
            },
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return d, event


async def get_offering_freeze_status(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> dict[str, Any]:
    """Used by M3/M4 rework: returns the strongest freeze that applies to
    this offering. Precedence: institutional_hard > department_soft >
    per_course_freeze. Any frozen deadline above the offering freezes it.
    """
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)

    candidates_q = await session.execute(
        select(InternalDeadline).where(
            InternalDeadline.college_id == actor.college_id,
            InternalDeadline.deleted_at.is_(None),
            InternalDeadline.is_frozen.is_(True),
            or_(
                # institutional_hard for the offering's term
                and_(
                    InternalDeadline.kind == "institutional_hard",
                    InternalDeadline.academic_term_id == offering.academic_term_id,
                ),
                # department_soft for the offering's term + dept
                and_(
                    InternalDeadline.kind == "department_soft",
                    InternalDeadline.academic_term_id == offering.academic_term_id,
                    InternalDeadline.department_id == course.department_id,
                ),
                # per_course_freeze targeting this offering directly
                and_(
                    InternalDeadline.kind == "per_course_freeze",
                    InternalDeadline.course_offering_id == offering.id,
                ),
            ),
        )
    )
    rows = list(candidates_q.scalars().all())
    if not rows:
        return {
            "course_offering_id": offering.id,
            "is_frozen": False,
            "frozen_by_kind": None,
            "deadline_at": None,
            "frozen_at": None,
            "notes": None,
        }
    precedence = {"institutional_hard": 0, "department_soft": 1, "per_course_freeze": 2}
    rows.sort(key=lambda r: precedence.get(r.kind, 99))
    chosen = rows[0]
    return {
        "course_offering_id": offering.id,
        "is_frozen": True,
        "frozen_by_kind": chosen.kind,
        "deadline_at": chosen.deadline_at,
        "frozen_at": chosen.frozen_at,
        "notes": chosen.notes,
    }


async def is_offering_frozen(
    session: AsyncSession, *, college_id: UUID, offering_id: UUID
) -> bool:
    """Lightweight check for M3/M4 rework code. Returns True if any frozen
    deadline applies. Does NOT enforce RBAC; the caller has its own auth.
    """
    offering = await session.get(CourseOffering, offering_id)
    if offering is None or offering.deleted_at is not None:
        return False
    course = await session.get(Course, offering.course_id)
    if course is None:
        return False
    n = (
        await session.execute(
            select(func.count(InternalDeadline.id)).where(
                InternalDeadline.college_id == college_id,
                InternalDeadline.deleted_at.is_(None),
                InternalDeadline.is_frozen.is_(True),
                or_(
                    and_(
                        InternalDeadline.kind == "institutional_hard",
                        InternalDeadline.academic_term_id == offering.academic_term_id,
                    ),
                    and_(
                        InternalDeadline.kind == "department_soft",
                        InternalDeadline.academic_term_id == offering.academic_term_id,
                        InternalDeadline.department_id == course.department_id,
                    ),
                    and_(
                        InternalDeadline.kind == "per_course_freeze",
                        InternalDeadline.course_offering_id == offering.id,
                    ),
                ),
            )
        )
    ).scalar_one()
    return int(n) > 0


# ── CIE schedule ────────────────────────────────────────────────────────────
async def _get_cie_or_404(
    session: AsyncSession, *, cie_id: UUID, college_id: UUID
) -> CIESchedule:
    row = await session.execute(
        select(CIESchedule).where(
            CIESchedule.id == cie_id,
            CIESchedule.college_id == college_id,
            CIESchedule.deleted_at.is_(None),
        )
    )
    cie = row.scalar_one_or_none()
    if cie is None:
        raise WorkflowError("not_found", "CIE schedule entry not found", 404)
    return cie


def _require_cie_writer(actor: User, offering: CourseOffering, course: Course) -> None:
    """HOD-of-dept OR teacher-of-offering can edit CIE drafts."""
    if actor.role == UserRole.teacher and offering.teacher_user_id == actor.id:
        return
    if (
        actor.role == UserRole.hod
        and actor.hod_of_department_id == course.department_id
    ):
        return
    raise WorkflowError(
        "forbidden",
        "only the offering's teacher or the department's HOD can edit",
        403,
    )


async def list_cie_schedule(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> list[dict[str, Any]]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    # Read access: writers + admin + students enrolled? Keep students out
    # of /workflow for now; they'll get a curated read via /student/* later.
    if actor.role == UserRole.admin:
        pass
    elif actor.role == UserRole.hod and actor.hod_of_department_id == course.department_id:
        pass
    elif actor.role in (UserRole.teacher, UserRole.hod) and offering.teacher_user_id == actor.id:
        pass
    else:
        raise WorkflowError("forbidden", "no access to this offering's CIE schedule", 403)

    rows = (
        await session.execute(
            select(CIESchedule)
            .where(
                CIESchedule.course_offering_id == offering.id,
                CIESchedule.deleted_at.is_(None),
            )
            .order_by(CIESchedule.cie_number)
        )
    ).scalars().all()

    room_codes: dict[UUID, str] = {}
    room_ids = {r.room_id for r in rows if r.room_id is not None}
    if room_ids:
        rrows = (
            await session.execute(
                select(Room.id, Room.code).where(Room.id.in_(room_ids))
            )
        ).all()
        room_codes = {rid: code for rid, code in rrows}

    return [
        {
            "id": r.id,
            "course_offering_id": r.course_offering_id,
            "cie_number": r.cie_number,
            "scheduled_at": r.scheduled_at,
            "duration_minutes": r.duration_minutes,
            "room_id": r.room_id,
            "room_code": room_codes.get(r.room_id) if r.room_id else None,
            "notes": r.notes,
            "is_published": r.is_published,
            "published_at": r.published_at,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


async def create_cie(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    cie_number: int,
    scheduled_at: datetime,
    duration_minutes: int,
    room_id: UUID | None,
    notes: str | None,
) -> CIESchedule:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_cie_writer(actor, offering, course)

    if room_id is not None:
        room = await session.get(Room, room_id)
        if (
            room is None
            or room.college_id != actor.college_id
            or room.deleted_at is not None
        ):
            raise WorkflowError("bad_room", "room not found", 400)

    cie = CIESchedule(
        college_id=actor.college_id,
        course_offering_id=offering.id,
        cie_number=cie_number,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        room_id=room_id,
        notes=notes,
        is_published=False,
    )
    session.add(cie)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_cie",
            f"CIE-{cie_number} already exists for this offering",
            409,
        ) from e

    await _validate_cie_ordering(session, offering_id=offering.id)

    await write_audit(
        session,
        action="cie.create",
        entity_type="cie_schedule",
        entity_id=cie.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "course_offering_id": str(offering.id),
            "cie_number": cie_number,
            "scheduled_at": scheduled_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(cie)
    return cie


async def _validate_cie_ordering(
    session: AsyncSession, *, offering_id: UUID
) -> None:
    """CIE-1 must precede CIE-2 must precede CIE-3 by scheduled_at."""
    rows = (
        await session.execute(
            select(CIESchedule)
            .where(
                CIESchedule.course_offering_id == offering_id,
                CIESchedule.deleted_at.is_(None),
            )
            .order_by(CIESchedule.cie_number)
        )
    ).scalars().all()
    last = None
    for r in rows:
        if last is not None and r.scheduled_at <= last.scheduled_at:
            raise WorkflowError(
                "cie_out_of_order",
                f"CIE-{r.cie_number} must be after CIE-{last.cie_number}",
                400,
            )
        last = r


async def patch_cie(
    session: AsyncSession,
    *,
    actor: User,
    cie_id: UUID,
    scheduled_at: datetime | None,
    duration_minutes: int | None,
    room_id: UUID | None,
    notes: str | None,
) -> CIESchedule:
    cie = await _get_cie_or_404(
        session, cie_id=cie_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, cie.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_cie_writer(actor, offering, course)

    if cie.is_published and actor.role != UserRole.hod:
        raise WorkflowError(
            "cie_published",
            "published CIE schedules can only be edited by the HOD",
            409,
        )

    if scheduled_at is not None:
        cie.scheduled_at = scheduled_at
    if duration_minutes is not None:
        cie.duration_minutes = duration_minutes
    if room_id is not None:
        room = await session.get(Room, room_id)
        if (
            room is None
            or room.college_id != actor.college_id
            or room.deleted_at is not None
        ):
            raise WorkflowError("bad_room", "room not found", 400)
        cie.room_id = room_id
    if notes is not None:
        cie.notes = notes

    await session.flush()
    await _validate_cie_ordering(session, offering_id=cie.course_offering_id)

    await write_audit(
        session,
        action="cie.patch",
        entity_type="cie_schedule",
        entity_id=cie.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()
    await session.refresh(cie)
    return cie


async def delete_cie(
    session: AsyncSession, *, actor: User, cie_id: UUID
) -> None:
    cie = await _get_cie_or_404(
        session, cie_id=cie_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, cie.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_cie_writer(actor, offering, course)

    if cie.is_published:
        raise WorkflowError(
            "cie_published",
            "unpublish the CIE first if you really need to remove it",
            409,
        )

    cie.deleted_at = utcnow()
    await write_audit(
        session,
        action="cie.delete",
        entity_type="cie_schedule",
        entity_id=cie.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


async def publish_cie_schedule(
    session: AsyncSession, *, actor: User, offering_id: UUID, publish: bool
) -> dict[str, Any]:
    """Publish (or unpublish) every CIE row on the offering. HOD-only.
    Publishing emits `cie.scheduled` once with the full schedule snapshot.
    """
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    if (
        actor.role != UserRole.hod
        or actor.hod_of_department_id != course.department_id
    ):
        raise WorkflowError("forbidden", "HOD only", 403)

    rows = (
        await session.execute(
            select(CIESchedule)
            .where(
                CIESchedule.course_offering_id == offering.id,
                CIESchedule.deleted_at.is_(None),
            )
            .order_by(CIESchedule.cie_number)
        )
    ).scalars().all()
    if publish and not rows:
        raise WorkflowError(
            "no_cie", "add at least one CIE before publishing", 409
        )
    if publish:
        await _validate_cie_ordering(session, offering_id=offering.id)

    now = utcnow()
    for r in rows:
        r.is_published = publish
        r.published_at = now if publish else None

    await write_audit(
        session,
        action="cie.publish" if publish else "cie.unpublish",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"cie_count": len(rows)},
    )
    await session.commit()

    snapshot = [
        {
            "id": str(r.id),
            "cie_number": r.cie_number,
            "scheduled_at": r.scheduled_at.isoformat(),
            "duration_minutes": r.duration_minutes,
            "room_id": str(r.room_id) if r.room_id else None,
        }
        for r in rows
    ]
    event = await publish_event(
        "cie.scheduled" if publish else "cie.unpublished",
        {
            "course_offering_id": str(offering.id),
            "is_published": publish,
            "entries": snapshot,
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return {
        "course_offering_id": offering.id,
        "is_published": publish,
        "cie_count": len(rows),
        "event": event,
    }


# ── Tasks ───────────────────────────────────────────────────────────────────
async def _get_task_or_404(
    session: AsyncSession, *, task_id: UUID, college_id: UUID
) -> Task:
    row = await session.execute(
        select(Task).where(
            Task.id == task_id,
            Task.college_id == college_id,
            Task.deleted_at.is_(None),
        )
    )
    t = row.scalar_one_or_none()
    if t is None:
        raise WorkflowError("not_found", "task not found", 404)
    return t


async def create_task(
    session: AsyncSession,
    *,
    actor: User,
    assigned_to_user_id: UUID,
    task_type: str,
    title: str,
    description: str | None,
    related_entity_type: str | None,
    related_entity_id: UUID | None,
    due_at: datetime | None,
) -> Task:
    """HOD assigns to teachers in their dept (or HOD themselves, e.g.
    paper-setting). Cross-dept assignment is rejected so the boundary
    stays clean for M9 reporting.
    """
    _require_hod(actor)
    assignee = await session.get(User, assigned_to_user_id)
    if (
        assignee is None
        or assignee.college_id != actor.college_id
        or assignee.deleted_at is not None
        or assignee.role not in (UserRole.teacher, UserRole.hod)
    ):
        raise WorkflowError("bad_assignee", "assignee not found", 400)

    # Restrict to assignees whose own offerings (or own HOD dept) match
    # the actor's dept. The simplest, defensible check: the assignee must
    # have at least one offering under the actor's dept OR be the HOD of
    # the same dept.
    if assignee.role == UserRole.hod and assignee.hod_of_department_id != actor.hod_of_department_id:
        raise WorkflowError(
            "cross_department",
            "cannot assign tasks to another department's HOD",
            403,
        )
    if assignee.role == UserRole.teacher:
        own_dept_count = (
            await session.execute(
                select(func.count(CourseOffering.id))
                .join(Course, Course.id == CourseOffering.course_id)
                .where(
                    CourseOffering.college_id == actor.college_id,
                    CourseOffering.teacher_user_id == assignee.id,
                    Course.department_id == actor.hod_of_department_id,
                    CourseOffering.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        if int(own_dept_count) == 0:
            raise WorkflowError(
                "cross_department",
                "assignee teaches no offerings in your department",
                403,
            )

    try:
        kind = TaskType(task_type)
    except ValueError as e:
        raise WorkflowError("bad_task_type", f"unknown task_type '{task_type}'", 400) from e

    t = Task(
        college_id=actor.college_id,
        assigned_by_user_id=actor.id,
        assigned_to_user_id=assigned_to_user_id,
        task_type=kind,
        title=title.strip(),
        description=description,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        due_at=due_at,
        status=TaskStatus.pending,
    )
    session.add(t)
    await session.flush()
    await write_audit(
        session,
        action="task.create",
        entity_type="task",
        entity_id=t.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "assigned_to_user_id": str(assigned_to_user_id),
            "task_type": task_type,
            "title": t.title,
        },
    )
    await session.commit()
    await session.refresh(t)
    await publish_event(
        "task.assigned",
        {
            "task_id": str(t.id),
            "assigned_by_user_id": str(actor.id),
            "assigned_to_user_id": str(assigned_to_user_id),
            "task_type": task_type,
            "title": t.title,
            "due_at": due_at.isoformat() if due_at else None,
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return t


async def list_tasks(
    session: AsyncSession,
    *,
    actor: User,
    mode: Literal["mine", "assigned_by_me", "department", "all"] = "mine",
    status: str | None = None,
) -> list[Task]:
    """`mine` = assigned_to actor; `assigned_by_me` = assigned_by actor;
    `department` = HOD's view of all dept teachers; `all` = admin-only.
    """
    stmt = select(Task).where(
        Task.college_id == actor.college_id,
        Task.deleted_at.is_(None),
    )
    if mode == "mine":
        stmt = stmt.where(Task.assigned_to_user_id == actor.id)
    elif mode == "assigned_by_me":
        stmt = stmt.where(Task.assigned_by_user_id == actor.id)
    elif mode == "department":
        if actor.role != UserRole.hod or actor.hod_of_department_id is None:
            raise WorkflowError("forbidden", "HOD only", 403)
        # Department mode: tasks the HOD assigned OR tasks whose assignee
        # belongs to the HOD's dept (via own offerings + HOD-self).
        assignee_ids_q = select(CourseOffering.teacher_user_id).join(
            Course, Course.id == CourseOffering.course_id
        ).where(
            Course.department_id == actor.hod_of_department_id,
            CourseOffering.college_id == actor.college_id,
            CourseOffering.deleted_at.is_(None),
        )
        stmt = stmt.where(
            or_(
                Task.assigned_by_user_id == actor.id,
                Task.assigned_to_user_id.in_(assignee_ids_q),
                Task.assigned_to_user_id == actor.id,
            )
        )
    elif mode == "all":
        if actor.role != UserRole.admin:
            raise WorkflowError("forbidden", "admin only", 403)
    if status is not None:
        try:
            stmt = stmt.where(Task.status == TaskStatus(status))
        except ValueError as e:
            raise WorkflowError("bad_status", f"unknown status '{status}'", 400) from e

    rows = await session.execute(stmt.order_by(Task.created_at.desc()))
    return list(rows.scalars().all())


async def task_to_dict(session: AsyncSession, t: Task) -> dict[str, Any]:
    assigned_by = await session.get(User, t.assigned_by_user_id)
    assigned_to = await session.get(User, t.assigned_to_user_id)
    return {
        "id": t.id,
        "assigned_by_user_id": t.assigned_by_user_id,
        "assigned_by_name": assigned_by.name if assigned_by else None,
        "assigned_to_user_id": t.assigned_to_user_id,
        "assigned_to_name": assigned_to.name if assigned_to else None,
        "task_type": t.task_type.value if hasattr(t.task_type, "value") else str(t.task_type),
        "title": t.title,
        "description": t.description,
        "related_entity_type": t.related_entity_type,
        "related_entity_id": t.related_entity_id,
        "due_at": t.due_at,
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "status_updated_at": t.status_updated_at,
        "decline_reason": t.decline_reason,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


_ALLOWED_TRANSITIONS = {
    "pending": {"accepted", "declined", "cancelled"},
    "accepted": {"completed", "cancelled"},
    "declined": set(),
    "completed": set(),
    "cancelled": set(),
}


async def update_task_status(
    session: AsyncSession,
    *,
    actor: User,
    task_id: UUID,
    status: str,
    decline_reason: str | None,
) -> Task:
    t = await _get_task_or_404(
        session, task_id=task_id, college_id=actor.college_id
    )
    # Authority: assignee can accept/decline/complete; assigner can cancel.
    if status in ("accepted", "declined", "completed"):
        if t.assigned_to_user_id != actor.id:
            raise WorkflowError(
                "forbidden", "only the assignee can transition this task", 403
            )
    elif status == "cancelled":
        if t.assigned_by_user_id != actor.id and actor.role != UserRole.admin:
            raise WorkflowError(
                "forbidden", "only the assigner or admin can cancel", 403
            )
    else:
        raise WorkflowError("bad_status", f"cannot transition to '{status}'", 400)

    current = t.status.value if hasattr(t.status, "value") else str(t.status)
    if status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise WorkflowError(
            "bad_transition",
            f"cannot go from '{current}' to '{status}'",
            409,
        )
    if status == "declined" and not decline_reason:
        raise WorkflowError(
            "reason_required", "declining a task requires a reason", 400
        )

    t.status = TaskStatus(status)
    t.status_updated_at = utcnow()
    if status == "declined":
        t.decline_reason = decline_reason

    await write_audit(
        session,
        action=f"task.{status}",
        entity_type="task",
        entity_id=t.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"status": status, "decline_reason": decline_reason},
    )
    await session.commit()
    await session.refresh(t)
    await publish_event(
        "task.status_changed",
        {
            "task_id": str(t.id),
            "status": status,
            "by_user_id": str(actor.id),
            "decline_reason": decline_reason,
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return t
