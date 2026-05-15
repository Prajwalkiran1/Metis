"""Service layer for M10c — lab batches, per-offering scheme picker,
and department-owned assessment scheme templates.

Three concerns live here, each with its own RBAC story:

1. **Lab batches** — HOD-of-the-offering's-dept OR the teacher who teaches
   the offering can compose batches, add/remove members, and assign
   incharges. HOD overrides any teacher decision. Auto-compose draws
   from active section enrollments because mandatory labs never get a
   `course_registrations` row (those only exist for electives).

2. **Per-offering scheme** — the teacher of the offering edits component
   weights (max 20% total AAT). HOD-of-dept can push AAT to 40% directly;
   the service writes a typed `academic_overrides` row so M9 audit can
   spot the exception. >40% is rejected for everyone (also enforced by
   the `ck_scheme_comp_aat_max_40pct` CHECK). REPLACE soft-deletes old
   components and inserts new ones, preserving the marks audit trail.
   Lab side of integrated courses (offering.parent_offering_id IS NOT
   NULL) is inherited from the theory parent — writes return
   `scheme_inherited`.

3. **Scheme templates** — institutional templates (owner_department_id
   IS NULL) are seeded in migration 0008 and are read-only for everyone
   except a future admin surface (M9). HODs author dept templates scoped
   to their own department. DELETE refuses with `template_in_use` while
   any AssessmentScheme.template_id still references the row.

Like service_m10b, the cascade-shaped routines run inside the current
session and commit at the end so partial state never reaches Postgres.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.event_bus import publish as publish_event
from app.modules.academic.models import (
    AssessmentComponentKind,
    AssessmentScheme,
    AssessmentSchemeComponent,
    AssessmentSchemeTemplate,
    Course,
    CourseOffering,
    CourseType,
    Enrollment,
    EnrollmentState,
    Section,
)
from app.modules.users.models import User, UserRole
from app.modules.workflow.models import (
    AcademicOverride,
    LabBatch,
    LabBatchAssignment,
    LabBatchMember,
    OverrideType,
)
from app.modules.workflow.service import WorkflowError

# Some types of courses can pick from a wider set of template types than
# the strict 1:1 mapping. Standalone labs are allowed to use a "theory"
# template — that's what the M10a auto-link does today.
_APPLICABLE_TEMPLATE_TYPES: dict[CourseType, set[str]] = {
    CourseType.theory: {"theory"},
    CourseType.lab: {"theory", "lab"},
    CourseType.integrated: {"integrated"},
    CourseType.nptel: {"nptel"},
}

# Course types that may carry a lab batch composition.
_LAB_BATCH_COMPATIBLE = {CourseType.lab, CourseType.integrated}

# AAT band that requires HOD authorisation (per BMSCE rules).
_AAT_FREE_CAP = Decimal("20")
_AAT_HOD_CAP = Decimal("40")


# ── Generic helpers ─────────────────────────────────────────────────────────
async def _get_offering_or_404(
    session: AsyncSession, *, offering_id: UUID, college_id: UUID
) -> CourseOffering:
    row = await session.execute(
        select(CourseOffering).where(
            CourseOffering.id == offering_id,
            CourseOffering.college_id == college_id,
            CourseOffering.deleted_at.is_(None),
        )
    )
    offering = row.scalar_one_or_none()
    if offering is None:
        raise WorkflowError("not_found", "course offering not found", 404)
    return offering


async def _course_for_offering(
    session: AsyncSession, *, offering: CourseOffering
) -> Course:
    course = await session.get(Course, offering.course_id)
    if course is None or course.deleted_at is not None:
        raise WorkflowError("not_found", "offering's course not found", 404)
    return course


def _require_offering_writer(actor: User, offering: CourseOffering, course: Course) -> None:
    """Allow the teacher of this offering OR the HOD of the course's dept.

    Admins are deliberately blocked from writing — per CLAUDE.md authority
    table, lab batch composition and scheme picking belong to HOD/teacher.
    Admins can read via get_lab_batches / get_scheme.
    """
    if actor.role == UserRole.teacher and offering.teacher_user_id == actor.id:
        return
    if (
        actor.role == UserRole.hod
        and actor.hod_of_department_id == course.department_id
    ):
        return
    # An HOD who happens to ALSO be the teacher (HOD-as-teacher path) goes
    # through the first arm too — they hit it on teacher_user_id match.
    raise WorkflowError(
        "forbidden",
        "only the offering's teacher or the department's HOD can do this",
        403,
    )


def _require_offering_reader(actor: User, offering: CourseOffering, course: Course) -> None:
    """Read access: writers + admin."""
    if actor.role == UserRole.admin:
        return
    if (
        actor.role == UserRole.hod
        and actor.hod_of_department_id == course.department_id
    ):
        return
    if actor.role in (UserRole.teacher, UserRole.hod) and offering.teacher_user_id == actor.id:
        return
    raise WorkflowError("forbidden", "no read access to this offering", 403)


def _require_hod_for_offering(actor: User, course: Course) -> None:
    if (
        actor.role != UserRole.hod
        or actor.hod_of_department_id != course.department_id
    ):
        raise WorkflowError("forbidden", "HOD of this department only", 403)


async def _get_batch_or_404(
    session: AsyncSession, *, batch_id: UUID, college_id: UUID
) -> LabBatch:
    row = await session.execute(
        select(LabBatch).where(
            LabBatch.id == batch_id,
            LabBatch.college_id == college_id,
            LabBatch.deleted_at.is_(None),
        )
    )
    batch = row.scalar_one_or_none()
    if batch is None:
        raise WorkflowError("not_found", "lab batch not found", 404)
    return batch


# ── Lab batches ─────────────────────────────────────────────────────────────
async def create_lab_batch(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    name: str,
    display_order: int,
) -> LabBatch:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)
    if course.course_type not in _LAB_BATCH_COMPATIBLE:
        raise WorkflowError(
            "course_type_incompatible",
            "lab batches require an integrated or lab course",
            400,
        )

    batch = LabBatch(
        college_id=actor.college_id,
        course_offering_id=offering.id,
        section_id=offering.section_id,
        name=name.strip(),
        display_order=display_order,
    )
    session.add(batch)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_batch_name",
            "a batch with this name already exists for the offering",
            409,
        ) from e

    await write_audit(
        session,
        action="lab_batch.create",
        entity_type="lab_batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "course_offering_id": str(offering.id),
            "name": batch.name,
            "display_order": batch.display_order,
        },
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def list_lab_batches(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> list[dict[str, Any]]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_reader(actor, offering, course)

    batches = (
        await session.execute(
            select(LabBatch)
            .where(
                LabBatch.course_offering_id == offering.id,
                LabBatch.deleted_at.is_(None),
            )
            .order_by(LabBatch.display_order, LabBatch.name)
        )
    ).scalars().all()
    if not batches:
        return []

    batch_ids = [b.id for b in batches]
    # Member counts
    counts = dict(
        (
            await session.execute(
                select(
                    LabBatchMember.lab_batch_id,
                    func.count(LabBatchMember.id),
                )
                .where(
                    LabBatchMember.lab_batch_id.in_(batch_ids),
                    LabBatchMember.removed_at.is_(None),
                )
                .group_by(LabBatchMember.lab_batch_id)
            )
        ).all()
    )

    # Assignments
    assignment_rows = (
        await session.execute(
            select(LabBatchAssignment, User.name)
            .join(User, User.id == LabBatchAssignment.teacher_user_id)
            .where(
                LabBatchAssignment.lab_batch_id.in_(batch_ids),
                LabBatchAssignment.unassigned_at.is_(None),
            )
            .order_by(LabBatchAssignment.assigned_at)
        )
    ).all()
    by_batch: dict[UUID, list[tuple[LabBatchAssignment, str]]] = {}
    for asg, name in assignment_rows:
        by_batch.setdefault(asg.lab_batch_id, []).append((asg, name))

    out: list[dict[str, Any]] = []
    for b in batches:
        asg_list = by_batch.get(b.id, [])
        incharge = next(
            (a for a, _n in asg_list if a.role == "batch_incharge"), None
        )
        incharge_name = next(
            (n for a, n in asg_list if a.role == "batch_incharge"), None
        )
        co_evals = [(a, n) for a, n in asg_list if a.role == "co_evaluator"]
        out.append(
            {
                "id": b.id,
                "course_offering_id": b.course_offering_id,
                "section_id": b.section_id,
                "name": b.name,
                "display_order": b.display_order,
                "member_count": int(counts.get(b.id, 0)),
                "incharge": (
                    {
                        "id": incharge.id,
                        "lab_batch_id": incharge.lab_batch_id,
                        "teacher_user_id": incharge.teacher_user_id,
                        "teacher_name": incharge_name,
                        "role": incharge.role,
                        "assigned_at": incharge.assigned_at,
                        "unassigned_at": incharge.unassigned_at,
                        "unassigned_reason": incharge.unassigned_reason,
                    }
                    if incharge is not None
                    else None
                ),
                "co_evaluators": [
                    {
                        "id": a.id,
                        "lab_batch_id": a.lab_batch_id,
                        "teacher_user_id": a.teacher_user_id,
                        "teacher_name": n,
                        "role": a.role,
                        "assigned_at": a.assigned_at,
                        "unassigned_at": a.unassigned_at,
                        "unassigned_reason": a.unassigned_reason,
                    }
                    for a, n in co_evals
                ],
            }
        )
    return out


async def patch_lab_batch(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    name: str | None,
    display_order: int | None,
) -> LabBatch:
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    if name is not None:
        batch.name = name.strip()
    if display_order is not None:
        batch.display_order = display_order
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_batch_name", "another batch already uses this name", 409
        ) from e

    await write_audit(
        session,
        action="lab_batch.patch",
        entity_type="lab_batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"name": batch.name, "display_order": batch.display_order},
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def delete_lab_batch(
    session: AsyncSession, *, actor: User, batch_id: UUID
) -> None:
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    now = utcnow()
    batch.deleted_at = now
    member_rows = (
        await session.execute(
            select(LabBatchMember).where(
                LabBatchMember.lab_batch_id == batch.id,
                LabBatchMember.removed_at.is_(None),
            )
        )
    ).scalars().all()
    for m in member_rows:
        m.removed_at = now
        m.removed_reason = "batch_deleted"
    assign_rows = (
        await session.execute(
            select(LabBatchAssignment).where(
                LabBatchAssignment.lab_batch_id == batch.id,
                LabBatchAssignment.unassigned_at.is_(None),
            )
        )
    ).scalars().all()
    for a in assign_rows:
        a.unassigned_at = now
        a.unassigned_reason = "batch_deleted"

    await write_audit(
        session,
        action="lab_batch.delete",
        entity_type="lab_batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"members_removed": len(member_rows), "assignments_removed": len(assign_rows)},
    )
    await session.commit()


# ── Offering roster (used by the lab-batch member picker UI) ───────────────
async def get_offering_roster(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> list[dict[str, Any]]:
    """Students enrolled in the offering's section for its term. The
    /hod/lab-batches dialog uses this to populate the multi-select; for
    mandatory courses every section student is eligible, and for
    electives the section enrollment is created by M10b's cascade so the
    same source still applies.
    """
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_reader(actor, offering, course)

    student_ids = await _active_section_students(
        session,
        college_id=actor.college_id,
        section_id=offering.section_id,
        academic_term_id=offering.academic_term_id,
        academic_term_code=offering.academic_term,
    )
    if not student_ids:
        return []
    rows = await session.execute(
        select(User.id, User.name, User.usn).where(User.id.in_(student_ids)).order_by(User.name)
    )
    return [
        {"student_user_id": uid, "name": name, "usn": usn}
        for uid, name, usn in rows.all()
    ]


# ── Lab batch members ───────────────────────────────────────────────────────
async def _active_section_students(
    session: AsyncSession,
    *,
    college_id: UUID,
    section_id: UUID,
    academic_term_id: UUID | None,
    academic_term_code: str,
) -> list[UUID]:
    """Return user_ids of students with an active enrollment in this
    section for the offering's term. Matches on academic_term_id when
    set; falls back to the legacy VARCHAR `academic_term` code so
    pre-rework enrollments still resolve.
    """
    where_clauses = [
        Enrollment.college_id == college_id,
        Enrollment.section_id == section_id,
        Enrollment.enrollment_state == EnrollmentState.active,
        Enrollment.withdrawn_at.is_(None),
    ]
    if academic_term_id is not None:
        where_clauses.append(
            or_(
                Enrollment.academic_term_id == academic_term_id,
                Enrollment.academic_term == academic_term_code,
            )
        )
    else:
        where_clauses.append(Enrollment.academic_term == academic_term_code)

    rows = await session.execute(
        select(Enrollment.student_user_id).where(*where_clauses).order_by(Enrollment.enrolled_at)
    )
    return [r[0] for r in rows.all()]


async def _other_active_batch_for(
    session: AsyncSession,
    *,
    offering_id: UUID,
    student_user_id: UUID,
    exclude_batch_id: UUID | None,
) -> LabBatch | None:
    """Return another active lab batch on the same offering for this student,
    if any. Used to enforce one-batch-per-offering."""
    stmt = (
        select(LabBatch)
        .join(LabBatchMember, LabBatchMember.lab_batch_id == LabBatch.id)
        .where(
            LabBatch.course_offering_id == offering_id,
            LabBatch.deleted_at.is_(None),
            LabBatchMember.student_user_id == student_user_id,
            LabBatchMember.removed_at.is_(None),
        )
    )
    if exclude_batch_id is not None:
        stmt = stmt.where(LabBatch.id != exclude_batch_id)
    row = await session.execute(stmt)
    return row.scalars().first()


async def add_members(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    student_user_ids: list[UUID],
) -> dict[str, Any]:
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    # The student must be enrolled in the offering's section for the term.
    allowed = set(
        await _active_section_students(
            session,
            college_id=actor.college_id,
            section_id=offering.section_id,
            academic_term_id=offering.academic_term_id,
            academic_term_code=offering.academic_term,
        )
    )

    added: list[UUID] = []
    skipped_not_in_section: list[UUID] = []
    skipped_already_in_batch: list[UUID] = []
    for sid in student_user_ids:
        if sid not in allowed:
            skipped_not_in_section.append(sid)
            continue
        # Reject if already in another active batch on this offering.
        other = await _other_active_batch_for(
            session,
            offering_id=offering.id,
            student_user_id=sid,
            exclude_batch_id=batch.id,
        )
        if other is not None:
            raise WorkflowError(
                "student_already_in_batch",
                f"student {sid} is already in batch '{other.name}' for this offering",
                409,
            )
        # If already in THIS batch (active), skip silently.
        existing = (
            await session.execute(
                select(LabBatchMember).where(
                    LabBatchMember.lab_batch_id == batch.id,
                    LabBatchMember.student_user_id == sid,
                    LabBatchMember.removed_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            skipped_already_in_batch.append(sid)
            continue
        session.add(
            LabBatchMember(
                college_id=actor.college_id,
                lab_batch_id=batch.id,
                student_user_id=sid,
            )
        )
        added.append(sid)
    await session.flush()
    await write_audit(
        session,
        action="lab_batch.members_add",
        entity_type="lab_batch",
        entity_id=batch.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "added_count": len(added),
            "skipped_not_in_section": len(skipped_not_in_section),
            "skipped_already_in_batch": len(skipped_already_in_batch),
        },
    )
    await session.commit()
    return {
        "added_count": len(added),
        "skipped_not_in_section": [str(s) for s in skipped_not_in_section],
        "skipped_already_in_batch": [str(s) for s in skipped_already_in_batch],
    }


async def remove_member(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    student_user_id: UUID,
    reason: str | None,
) -> None:
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    row = (
        await session.execute(
            select(LabBatchMember).where(
                LabBatchMember.lab_batch_id == batch.id,
                LabBatchMember.student_user_id == student_user_id,
                LabBatchMember.removed_at.is_(None),
            )
        )
    ).scalars().first()
    if row is None:
        raise WorkflowError("not_found", "student is not an active member", 404)
    row.removed_at = utcnow()
    row.removed_reason = reason or "manual_removal"
    await write_audit(
        session,
        action="lab_batch.member_remove",
        entity_type="lab_batch_member",
        entity_id=row.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "student_user_id": str(student_user_id),
            "reason": row.removed_reason,
        },
    )
    await session.commit()


async def auto_compose_batches(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    batch_count: int,
    name_prefix: str,
) -> dict[str, Any]:
    """Idempotent: existing batches keep their members; freshly added
    batches absorb only students who aren't currently in any active batch
    for THIS offering. Distributes round-robin by enrollment order.

    Returns a summary the caller can render. Emits `lab_batch.composed`
    after the transaction commits.
    """
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)
    if course.course_type not in _LAB_BATCH_COMPATIBLE:
        raise WorkflowError(
            "course_type_incompatible",
            "auto-compose requires an integrated or lab course",
            400,
        )

    # Bring existing batches up to the requested count. Reuse names if they
    # already follow the prefix-{N} pattern; otherwise append new ones.
    existing = (
        await session.execute(
            select(LabBatch)
            .where(
                LabBatch.course_offering_id == offering.id,
                LabBatch.deleted_at.is_(None),
            )
            .order_by(LabBatch.display_order, LabBatch.name)
        )
    ).scalars().all()

    batches: list[LabBatch] = list(existing)
    created = 0
    next_order = (
        max((b.display_order for b in existing), default=0) + 1 if existing else 1
    )
    while len(batches) < batch_count:
        candidate = f"{name_prefix} {len(batches) + 1}"
        # Skip if collides with an existing soft-deleted name + active name
        new_batch = LabBatch(
            college_id=actor.college_id,
            course_offering_id=offering.id,
            section_id=offering.section_id,
            name=candidate,
            display_order=next_order,
        )
        session.add(new_batch)
        try:
            await session.flush()
        except IntegrityError as e:
            await session.rollback()
            raise WorkflowError(
                "duplicate_batch_name",
                f"a batch named '{candidate}' already exists; pick a different prefix",
                409,
            ) from e
        batches.append(new_batch)
        created += 1
        next_order += 1

    target_batches = batches[:batch_count]
    if not target_batches:
        raise WorkflowError(
            "no_batches", "batch_count must be >= 1 after composing", 400
        )

    # Roster from section enrollments — auto-compose ignores course_registrations
    # because mandatory labs never write those rows.
    section_students = await _active_section_students(
        session,
        college_id=actor.college_id,
        section_id=offering.section_id,
        academic_term_id=offering.academic_term_id,
        academic_term_code=offering.academic_term,
    )

    # Skip anyone already in an active batch for THIS offering.
    already_assigned = set(
        (
            await session.execute(
                select(LabBatchMember.student_user_id)
                .join(LabBatch, LabBatch.id == LabBatchMember.lab_batch_id)
                .where(
                    LabBatch.course_offering_id == offering.id,
                    LabBatch.deleted_at.is_(None),
                    LabBatchMember.removed_at.is_(None),
                )
            )
        ).scalars().all()
    )
    queue = [s for s in section_students if s not in already_assigned]

    distribution: dict[str, int] = {b.name: 0 for b in target_batches}
    # Seed existing counts so the round-robin starts from the leanest batch.
    existing_counts = dict(
        (
            await session.execute(
                select(
                    LabBatchMember.lab_batch_id,
                    func.count(LabBatchMember.id),
                )
                .where(
                    LabBatchMember.lab_batch_id.in_([b.id for b in target_batches]),
                    LabBatchMember.removed_at.is_(None),
                )
                .group_by(LabBatchMember.lab_batch_id)
            )
        ).all()
    )
    counts = {b.id: int(existing_counts.get(b.id, 0)) for b in target_batches}
    for b in target_batches:
        distribution[b.name] = counts[b.id]

    added = 0
    while queue:
        # Pick the batch with the smallest current count, ties broken by
        # display_order (stable across re-runs).
        target = min(
            target_batches,
            key=lambda b: (counts[b.id], b.display_order, b.name),
        )
        sid = queue.pop(0)
        session.add(
            LabBatchMember(
                college_id=actor.college_id,
                lab_batch_id=target.id,
                student_user_id=sid,
            )
        )
        counts[target.id] += 1
        distribution[target.name] += 1
        added += 1
    await session.flush()

    await write_audit(
        session,
        action="lab_batch.auto_compose",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "batches_total": len(target_batches),
            "batches_created": created,
            "students_assigned": added,
            "distribution": distribution,
        },
    )
    await session.commit()

    incharge_ids: list[str] = []
    for b in target_batches:
        # Fetch the current incharge for the event payload.
        incharge = (
            await session.execute(
                select(LabBatchAssignment.teacher_user_id).where(
                    LabBatchAssignment.lab_batch_id == b.id,
                    LabBatchAssignment.role == "batch_incharge",
                    LabBatchAssignment.unassigned_at.is_(None),
                )
            )
        ).scalars().first()
        if incharge is not None:
            incharge_ids.append(str(incharge))

    event = await publish_event(
        "lab_batch.composed",
        {
            "course_offering_id": str(offering.id),
            "batches_total": len(target_batches),
            "batches_created": created,
            "students_assigned": added,
            "students_skipped": len(section_students) - len(queue) - added,
            "distribution": distribution,
            "incharge_user_ids": incharge_ids,
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )

    return {
        "batches_created": created,
        "batches_total": len(target_batches),
        "students_assigned": added,
        "students_skipped": max(0, len(section_students) - added),
        "distribution": distribution,
        "event": event,
    }


# ── Lab batch assignments (incharges + co-evaluators) ──────────────────────
async def add_assignment(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    teacher_user_id: UUID,
    role: Literal["batch_incharge", "co_evaluator"],
) -> dict[str, Any]:
    """Assign a teacher to a batch. For role='batch_incharge' the active
    one is replaced (unassign + insert) so the HOD-override flow is a
    single call. For 'co_evaluator', multiple are allowed.

    Returns {assignment, previous_incharge_id, event}. The event is
    `lab_batch.reassigned` when an incharge was displaced, else None.
    """
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    teacher = await session.get(User, teacher_user_id)
    if (
        teacher is None
        or teacher.college_id != actor.college_id
        or teacher.deleted_at is not None
        or teacher.role not in (UserRole.teacher, UserRole.hod)
    ):
        raise WorkflowError("bad_teacher", "teacher not found", 400)

    previous_incharge_id: UUID | None = None
    if role == "batch_incharge":
        # Unassign the active incharge (if any) so the partial unique
        # index (lab_batch_id, teacher_user_id, role) WHERE unassigned_at
        # IS NULL doesn't trip.
        existing = (
            await session.execute(
                select(LabBatchAssignment).where(
                    LabBatchAssignment.lab_batch_id == batch.id,
                    LabBatchAssignment.role == "batch_incharge",
                    LabBatchAssignment.unassigned_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            if existing.teacher_user_id == teacher_user_id:
                # No-op: idempotent.
                return {
                    "assignment": _assignment_view(existing, teacher.name),
                    "previous_incharge_id": None,
                    "event": None,
                }
            existing.unassigned_at = utcnow()
            existing.unassigned_reason = "replaced_by_new_incharge"
            previous_incharge_id = existing.teacher_user_id

    new_assignment = LabBatchAssignment(
        college_id=actor.college_id,
        lab_batch_id=batch.id,
        teacher_user_id=teacher_user_id,
        role=role,
    )
    session.add(new_assignment)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_assignment",
            "this teacher is already assigned to the batch in that role",
            409,
        ) from e

    await write_audit(
        session,
        action="lab_batch.assignment_add",
        entity_type="lab_batch_assignment",
        entity_id=new_assignment.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "lab_batch_id": str(batch.id),
            "teacher_user_id": str(teacher_user_id),
            "role": role,
            "replaced_teacher_user_id": (
                str(previous_incharge_id) if previous_incharge_id else None
            ),
        },
    )
    # When the actor is an HOD replacing the existing incharge, log a typed
    # override row so M9 can see the reassignment without grepping audit_logs.
    if previous_incharge_id is not None and actor.role == UserRole.hod:
        session.add(
            AcademicOverride(
                college_id=actor.college_id,
                override_type=OverrideType.lab_batch_reassignment,
                actor_user_id=actor.id,
                target_course_offering_id=offering.id,
                target_entity_type="lab_batch",
                target_entity_id=batch.id,
                old_value={"incharge_user_id": str(previous_incharge_id)},
                new_value={"incharge_user_id": str(teacher_user_id)},
                reason="HOD-override replacement of batch incharge",
            )
        )
    await session.commit()
    await session.refresh(new_assignment)

    event: dict[str, Any] | None = None
    if previous_incharge_id is not None:
        event = await publish_event(
            "lab_batch.reassigned",
            {
                "lab_batch_id": str(batch.id),
                "course_offering_id": str(offering.id),
                "from_teacher_user_id": str(previous_incharge_id),
                "to_teacher_user_id": str(teacher_user_id),
                "role": role,
                "reason": "hod_override" if actor.role == UserRole.hod else "teacher_change",
            },
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return {
        "assignment": _assignment_view(new_assignment, teacher.name),
        "previous_incharge_id": (
            str(previous_incharge_id) if previous_incharge_id else None
        ),
        "event": event,
    }


def _assignment_view(a: LabBatchAssignment, teacher_name: str | None) -> dict[str, Any]:
    return {
        "id": a.id,
        "lab_batch_id": a.lab_batch_id,
        "teacher_user_id": a.teacher_user_id,
        "teacher_name": teacher_name,
        "role": a.role,
        "assigned_at": a.assigned_at,
        "unassigned_at": a.unassigned_at,
        "unassigned_reason": a.unassigned_reason,
    }


async def remove_assignment(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    assignment_id: UUID,
    reason: str | None,
) -> None:
    batch = await _get_batch_or_404(
        session, batch_id=batch_id, college_id=actor.college_id
    )
    offering = await session.get(CourseOffering, batch.course_offering_id)
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)

    row = await session.get(LabBatchAssignment, assignment_id)
    if (
        row is None
        or row.lab_batch_id != batch.id
        or row.college_id != actor.college_id
        or row.unassigned_at is not None
    ):
        raise WorkflowError("not_found", "active assignment not found", 404)
    row.unassigned_at = utcnow()
    row.unassigned_reason = reason or "manual_removal"
    await write_audit(
        session,
        action="lab_batch.assignment_remove",
        entity_type="lab_batch_assignment",
        entity_id=row.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"reason": row.unassigned_reason},
    )
    await session.commit()


# ── Per-offering scheme picker ──────────────────────────────────────────────
async def _scheme_for_offering(
    session: AsyncSession, *, offering: CourseOffering
) -> AssessmentScheme | None:
    if offering.assessment_scheme_id is None:
        return None
    row = await session.execute(
        select(AssessmentScheme).where(
            AssessmentScheme.id == offering.assessment_scheme_id,
            AssessmentScheme.deleted_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _components_for_scheme(
    session: AsyncSession, *, scheme_id: UUID
) -> list[AssessmentSchemeComponent]:
    rows = await session.execute(
        select(AssessmentSchemeComponent)
        .where(
            AssessmentSchemeComponent.assessment_scheme_id == scheme_id,
            AssessmentSchemeComponent.deleted_at.is_(None),
        )
        .order_by(AssessmentSchemeComponent.ordinal, AssessmentSchemeComponent.label)
    )
    return list(rows.scalars().all())


def _aat_total_percent(components: list[AssessmentSchemeComponent]) -> Decimal:
    return sum(
        (c.weight_percent for c in components if c.kind == AssessmentComponentKind.aat),
        start=Decimal("0"),
    )


def _weight_total_percent(components: list[AssessmentSchemeComponent]) -> Decimal:
    return sum((c.weight_percent for c in components), start=Decimal("0"))


def _validate_aat_for_actor(
    *,
    actor: User,
    components: list[AssessmentSchemeComponent],
) -> bool:
    """Return True if the AAT total triggered the HOD-override band (so
    the caller writes an academic_overrides row), False if it was free.
    Raises WorkflowError for hard violations.
    """
    total = _aat_total_percent(components)
    if total > _AAT_HOD_CAP:
        raise WorkflowError(
            "aat_weight_exceeded",
            f"total AAT weight {total}% exceeds the 40% institutional cap",
            400,
        )
    if total > _AAT_FREE_CAP:
        # 20% < total <= 40%: must be HOD.
        if actor.role != UserRole.hod:
            raise WorkflowError(
                "aat_requires_hod",
                f"total AAT {total}% requires HOD authorisation (>20%)",
                403,
            )
        return True
    return False


async def get_scheme(
    session: AsyncSession, *, actor: User, offering_id: UUID
) -> dict[str, Any]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_reader(actor, offering, course)

    # Integrated lab side inherits from the theory parent.
    inherited_from: UUID | None = None
    effective_offering = offering
    if offering.parent_offering_id is not None:
        parent = await session.get(CourseOffering, offering.parent_offering_id)
        if parent is not None and parent.deleted_at is None:
            inherited_from = parent.id
            effective_offering = parent

    scheme = await _scheme_for_offering(session, offering=effective_offering)
    if scheme is None:
        raise WorkflowError("no_scheme", "no scheme configured for this offering", 404)
    components = await _components_for_scheme(session, scheme_id=scheme.id)

    template_name: str | None = None
    if scheme.template_id is not None:
        tpl = await session.get(AssessmentSchemeTemplate, scheme.template_id)
        if tpl is not None and tpl.deleted_at is None:
            template_name = tpl.name

    return {
        "id": scheme.id,
        "course_offering_id": effective_offering.id,
        "template_id": scheme.template_id,
        "template_name": template_name,
        "configured_by_user_id": scheme.configured_by_user_id,
        "is_locked": scheme.is_locked,
        "locked_at": scheme.locked_at,
        "locked_reason": scheme.locked_reason,
        "components": [
            {
                "id": c.id,
                "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                "label": c.label,
                "max_marks": float(c.max_marks),
                "weight_percent": float(c.weight_percent),
                "ordinal": c.ordinal,
                "is_dropped_in_best_of": c.is_dropped_in_best_of,
                "metadata_json": c.metadata_json or {},
            }
            for c in components
        ],
        "aat_total_percent": float(_aat_total_percent(components)),
        "weight_total_percent": float(_weight_total_percent(components)),
        "inherited_from_offering_id": inherited_from,
    }


def _reject_if_inherited(offering: CourseOffering) -> None:
    if offering.parent_offering_id is not None:
        raise WorkflowError(
            "scheme_inherited",
            "this offering inherits its scheme from the theory parent; edit there",
            400,
        )


def _reject_if_locked(scheme: AssessmentScheme) -> None:
    if scheme.is_locked:
        raise WorkflowError(
            "scheme_locked",
            "scheme is locked; HOD must unlock before edits",
            409,
        )


async def replace_scheme(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    template_id: UUID | None,
    clone_from_offering_id: UUID | None,
    components_input: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Soft-delete the existing components and insert new ones. The scheme
    row itself stays (so course_offerings.assessment_scheme_id never breaks
    its FK). Caller has validated exactly one source was provided.

    Emits `assessment.scheme_configured` after commit.
    """
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)
    _reject_if_inherited(offering)

    scheme = await _scheme_for_offering(session, offering=offering)
    if scheme is None:
        # Auto-link should have happened in M10a, but if a setup was
        # built outside that flow, create a fresh scheme on the fly.
        scheme = AssessmentScheme(
            college_id=actor.college_id,
            course_offering_id=offering.id,
            template_id=None,
            configured_by_user_id=actor.id,
            is_locked=False,
        )
        session.add(scheme)
        await session.flush()
        offering.assessment_scheme_id = scheme.id
    else:
        _reject_if_locked(scheme)

    # Materialise the requested component list.
    new_components: list[dict[str, Any]] = []
    template_used: UUID | None = None
    if template_id is not None:
        tpl = await session.get(AssessmentSchemeTemplate, template_id)
        if (
            tpl is None
            or tpl.college_id != actor.college_id
            or tpl.deleted_at is not None
            or not tpl.is_active
        ):
            raise WorkflowError("bad_template", "template not found", 400)
        # HOD-owned templates are scoped to the HOD's dept; institutional
        # ones (owner_department_id IS NULL) are open to anyone.
        if (
            tpl.owner_department_id is not None
            and tpl.owner_department_id != course.department_id
        ):
            raise WorkflowError(
                "bad_template",
                "template belongs to another department",
                400,
            )
        if tpl.applies_to_course_type not in _APPLICABLE_TEMPLATE_TYPES.get(
            course.course_type, set()
        ):
            raise WorkflowError(
                "template_type_mismatch",
                (
                    f"template applies to {tpl.applies_to_course_type} but the "
                    f"course is {course.course_type.value}"
                ),
                400,
            )
        template_used = tpl.id
        for c in tpl.default_components or []:
            new_components.append(
                {
                    "kind": c["kind"],
                    "label": c["label"],
                    "max_marks": Decimal(str(c["max_marks"])),
                    "weight_percent": Decimal(str(c["weight_percent"])),
                    "ordinal": int(c.get("ordinal", 1)),
                    "metadata_json": c.get("metadata", {}) or {},
                    "is_dropped_in_best_of": bool(c.get("is_dropped_in_best_of", False)),
                }
            )
    elif clone_from_offering_id is not None:
        src = await _get_offering_or_404(
            session,
            offering_id=clone_from_offering_id,
            college_id=actor.college_id,
        )
        src_scheme = await _scheme_for_offering(session, offering=src)
        if src_scheme is None:
            raise WorkflowError(
                "no_source_scheme",
                "source offering has no scheme to clone",
                400,
            )
        src_components = await _components_for_scheme(
            session, scheme_id=src_scheme.id
        )
        if not src_components:
            raise WorkflowError(
                "no_source_components",
                "source scheme has no components to clone",
                400,
            )
        template_used = src_scheme.template_id
        for c in src_components:
            new_components.append(
                {
                    "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                    "label": c.label,
                    "max_marks": c.max_marks,
                    "weight_percent": c.weight_percent,
                    "ordinal": c.ordinal,
                    "metadata_json": c.metadata_json or {},
                    "is_dropped_in_best_of": c.is_dropped_in_best_of,
                }
            )
    else:
        assert components_input is not None
        for c in components_input:
            new_components.append(
                {
                    "kind": c["kind"],
                    "label": c["label"],
                    "max_marks": Decimal(str(c["max_marks"])),
                    "weight_percent": Decimal(str(c["weight_percent"])),
                    "ordinal": int(c.get("ordinal", 1)),
                    "metadata_json": c.get("metadata_json", {}) or {},
                    "is_dropped_in_best_of": bool(c.get("is_dropped_in_best_of", False)),
                }
            )

    if not new_components:
        raise WorkflowError(
            "no_components", "scheme must have at least one component", 400
        )

    # Validate label uniqueness so the unique partial index doesn't surface
    # as a 500 later.
    seen_labels: set[str] = set()
    for c in new_components:
        if c["label"] in seen_labels:
            raise WorkflowError(
                "duplicate_label", f"duplicate component label '{c['label']}'", 400
            )
        seen_labels.add(c["label"])

    # AAT gating: build temporary objects so _validate_aat_for_actor can sum
    # weights without committing first.
    class _Tmp:
        def __init__(self, kind: str, weight: Decimal) -> None:
            try:
                self.kind = AssessmentComponentKind(kind)
            except ValueError:
                self.kind = kind  # tolerate raw strings for the sum
            self.weight_percent = weight

    tmps = [_Tmp(c["kind"], c["weight_percent"]) for c in new_components]
    hod_override_needed = _validate_aat_for_actor(actor=actor, components=tmps)  # type: ignore[arg-type]

    # Soft-delete current components.
    now = utcnow()
    existing_components = await _components_for_scheme(session, scheme_id=scheme.id)
    for c in existing_components:
        c.deleted_at = now

    # Flush the soft-deletes BEFORE inserting new rows that may reuse the
    # same labels. The unique partial index is on (scheme_id, label) WHERE
    # deleted_at IS NULL; ordering the writes via flush guarantees Postgres
    # sees the old rows as deleted before the new ones land.
    await session.flush()

    inserted_ids: list[UUID] = []
    for c in new_components:
        comp = AssessmentSchemeComponent(
            college_id=actor.college_id,
            assessment_scheme_id=scheme.id,
            kind=c["kind"],
            label=c["label"],
            max_marks=c["max_marks"],
            weight_percent=c["weight_percent"],
            ordinal=c["ordinal"],
            metadata_json=c["metadata_json"],
            is_dropped_in_best_of=c["is_dropped_in_best_of"],
        )
        session.add(comp)
        await session.flush()
        inserted_ids.append(comp.id)

    scheme.template_id = template_used
    scheme.configured_by_user_id = actor.id

    if hod_override_needed:
        session.add(
            AcademicOverride(
                college_id=actor.college_id,
                override_type=OverrideType.assessment_scheme_unlock,
                actor_user_id=actor.id,
                target_course_offering_id=offering.id,
                target_entity_type="assessment_scheme",
                target_entity_id=scheme.id,
                old_value={"aat_band": "free"},
                new_value={
                    "aat_band": "hod_extended",
                    "aat_total_percent": float(
                        sum(
                            (c["weight_percent"] for c in new_components if c["kind"] == "aat"),
                            start=Decimal("0"),
                        )
                    ),
                },
                reason="HOD pushed AAT into 20–40% band",
            )
        )

    await write_audit(
        session,
        action="scheme.replace",
        entity_type="assessment_scheme",
        entity_id=scheme.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "components_count": len(new_components),
            "template_id": str(template_used) if template_used else None,
            "hod_override_aat": hod_override_needed,
        },
    )
    await session.commit()

    event = await publish_event(
        "assessment.scheme_configured",
        {
            "course_offering_id": str(offering.id),
            "scheme_id": str(scheme.id),
            "template_id": str(template_used) if template_used else None,
            "locked": False,
            "components_count": len(new_components),
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    refreshed = await get_scheme(session, actor=actor, offering_id=offering.id)
    refreshed["event"] = event
    return refreshed


async def patch_component(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    component_id: UUID,
    label: str | None,
    max_marks: float | None,
    weight_percent: float | None,
    ordinal: int | None,
    is_dropped_in_best_of: bool | None,
) -> dict[str, Any]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)
    _reject_if_inherited(offering)

    scheme = await _scheme_for_offering(session, offering=offering)
    if scheme is None:
        raise WorkflowError("no_scheme", "no scheme configured", 404)
    _reject_if_locked(scheme)

    comp = await session.get(AssessmentSchemeComponent, component_id)
    if (
        comp is None
        or comp.assessment_scheme_id != scheme.id
        or comp.deleted_at is not None
    ):
        raise WorkflowError("not_found", "component not found", 404)

    if label is not None:
        comp.label = label
    if max_marks is not None:
        comp.max_marks = Decimal(str(max_marks))
    if weight_percent is not None:
        comp.weight_percent = Decimal(str(weight_percent))
    if ordinal is not None:
        comp.ordinal = ordinal
    if is_dropped_in_best_of is not None:
        comp.is_dropped_in_best_of = is_dropped_in_best_of

    # Re-evaluate the AAT total with this row's updated weight.
    current = await _components_for_scheme(session, scheme_id=scheme.id)
    hod_override_needed = _validate_aat_for_actor(actor=actor, components=current)

    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_label",
            "another component already uses that label",
            409,
        ) from e

    if hod_override_needed:
        session.add(
            AcademicOverride(
                college_id=actor.college_id,
                override_type=OverrideType.assessment_scheme_unlock,
                actor_user_id=actor.id,
                target_course_offering_id=offering.id,
                target_entity_type="assessment_scheme_component",
                target_entity_id=comp.id,
                old_value={"aat_band": "free"},
                new_value={
                    "aat_band": "hod_extended",
                    "aat_total_percent": float(_aat_total_percent(current)),
                },
                reason="HOD edited AAT into 20–40% band",
            )
        )

    await write_audit(
        session,
        action="scheme.component_patch",
        entity_type="assessment_scheme_component",
        entity_id=comp.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "label": comp.label,
            "max_marks": float(comp.max_marks),
            "weight_percent": float(comp.weight_percent),
            "ordinal": comp.ordinal,
            "is_dropped_in_best_of": comp.is_dropped_in_best_of,
            "hod_override_aat": hod_override_needed,
        },
    )
    await session.commit()

    event = await publish_event(
        "assessment.scheme_configured",
        {
            "course_offering_id": str(offering.id),
            "scheme_id": str(scheme.id),
            "template_id": str(scheme.template_id) if scheme.template_id else None,
            "locked": False,
            "components_count": len(current),
            "change": "component_patch",
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    refreshed = await get_scheme(session, actor=actor, offering_id=offering.id)
    refreshed["event"] = event
    return refreshed


async def lock_scheme(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    reason: str | None,
) -> dict[str, Any]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_offering_writer(actor, offering, course)
    _reject_if_inherited(offering)

    scheme = await _scheme_for_offering(session, offering=offering)
    if scheme is None:
        raise WorkflowError("no_scheme", "no scheme to lock", 404)
    if scheme.is_locked:
        # Idempotent.
        return await get_scheme(session, actor=actor, offering_id=offering.id)

    scheme.is_locked = True
    scheme.locked_at = utcnow()
    scheme.locked_reason = reason
    await write_audit(
        session,
        action="scheme.lock",
        entity_type="assessment_scheme",
        entity_id=scheme.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"reason": reason},
    )
    await session.commit()
    await publish_event(
        "assessment.scheme_configured",
        {
            "course_offering_id": str(offering.id),
            "scheme_id": str(scheme.id),
            "template_id": str(scheme.template_id) if scheme.template_id else None,
            "locked": True,
            "change": "lock",
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return await get_scheme(session, actor=actor, offering_id=offering.id)


async def unlock_scheme(
    session: AsyncSession,
    *,
    actor: User,
    offering_id: UUID,
    reason: str,
) -> dict[str, Any]:
    offering = await _get_offering_or_404(
        session, offering_id=offering_id, college_id=actor.college_id
    )
    course = await _course_for_offering(session, offering=offering)
    _require_hod_for_offering(actor, course)
    _reject_if_inherited(offering)

    scheme = await _scheme_for_offering(session, offering=offering)
    if scheme is None:
        raise WorkflowError("no_scheme", "no scheme to unlock", 404)
    if not scheme.is_locked:
        return await get_scheme(session, actor=actor, offering_id=offering.id)

    prior_reason = scheme.locked_reason
    scheme.is_locked = False
    scheme.locked_at = None
    scheme.locked_reason = None

    session.add(
        AcademicOverride(
            college_id=actor.college_id,
            override_type=OverrideType.assessment_scheme_unlock,
            actor_user_id=actor.id,
            target_course_offering_id=offering.id,
            target_entity_type="assessment_scheme",
            target_entity_id=scheme.id,
            old_value={"is_locked": True, "locked_reason": prior_reason},
            new_value={"is_locked": False},
            reason=reason,
        )
    )
    await write_audit(
        session,
        action="scheme.unlock",
        entity_type="assessment_scheme",
        entity_id=scheme.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"reason": reason},
    )
    await session.commit()
    await publish_event(
        "assessment.scheme_configured",
        {
            "course_offering_id": str(offering.id),
            "scheme_id": str(scheme.id),
            "template_id": str(scheme.template_id) if scheme.template_id else None,
            "locked": False,
            "change": "unlock",
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    return await get_scheme(session, actor=actor, offering_id=offering.id)


# ── Department scheme templates ─────────────────────────────────────────────
def _require_template_writer(actor: User, owner_dept_id: UUID | None) -> None:
    """Only HODs author dept templates. Institutional templates
    (owner_department_id IS NULL) are read-only here — admin authoring is
    deferred to M9.
    """
    if owner_dept_id is None:
        raise WorkflowError(
            "template_institutional",
            "institutional templates are read-only in this surface",
            403,
        )
    if actor.role != UserRole.hod or actor.hod_of_department_id != owner_dept_id:
        raise WorkflowError(
            "forbidden", "HOD of the owning department only", 403
        )


async def list_templates(
    session: AsyncSession,
    *,
    actor: User,
    applies_to_course_type: str | None = None,
) -> list[dict[str, Any]]:
    """Visible to HOD/teacher/admin. Returns institutional templates
    PLUS templates owned by the actor's department (if any). Other
    departments' templates are hidden so the picker stays scoped.
    """
    if actor.role not in (UserRole.admin, UserRole.hod, UserRole.teacher):
        raise WorkflowError("forbidden", "must be admin/hod/teacher", 403)
    own_dept: UUID | None = None
    if actor.role == UserRole.hod:
        own_dept = actor.hod_of_department_id
    elif actor.role == UserRole.teacher:
        # Teachers see institutional templates + templates of every
        # department they teach a course for. Picking the right cone is
        # M10c overkill; default to institutional + the dept of any
        # offering they teach. For now, surface institutional only —
        # the picker UI lets them clone from a sibling offering anyway.
        own_dept = None

    where = [
        AssessmentSchemeTemplate.college_id == actor.college_id,
        AssessmentSchemeTemplate.deleted_at.is_(None),
    ]
    if own_dept is not None:
        where.append(
            or_(
                AssessmentSchemeTemplate.owner_department_id.is_(None),
                AssessmentSchemeTemplate.owner_department_id == own_dept,
            )
        )
    else:
        where.append(AssessmentSchemeTemplate.owner_department_id.is_(None))
    if applies_to_course_type is not None:
        where.append(
            AssessmentSchemeTemplate.applies_to_course_type == applies_to_course_type
        )

    rows = (
        await session.execute(
            select(AssessmentSchemeTemplate).where(*where).order_by(
                AssessmentSchemeTemplate.name
            )
        )
    ).scalars().all()

    # Usage counts in one shot.
    usage_rows = (
        await session.execute(
            select(
                AssessmentScheme.template_id,
                func.count(AssessmentScheme.id),
            )
            .where(
                AssessmentScheme.college_id == actor.college_id,
                AssessmentScheme.deleted_at.is_(None),
                AssessmentScheme.template_id.is_not(None),
            )
            .group_by(AssessmentScheme.template_id)
        )
    ).all()
    usage = {tid: int(cnt) for tid, cnt in usage_rows}

    # Department code lookup
    from app.modules.academic.models import Department  # local — cycle guard

    dept_ids = {r.owner_department_id for r in rows if r.owner_department_id is not None}
    dept_codes: dict[UUID, str] = {}
    if dept_ids:
        dept_rows = (
            await session.execute(
                select(Department.id, Department.code).where(
                    Department.id.in_(dept_ids),
                )
            )
        ).all()
        dept_codes = {did: code for did, code in dept_rows}

    return [
        {
            "id": r.id,
            "owner_department_id": r.owner_department_id,
            "owner_department_code": dept_codes.get(r.owner_department_id),
            "name": r.name,
            "description": r.description,
            "applies_to_course_type": r.applies_to_course_type,
            "validation_rules": r.validation_rules or {},
            "default_components": r.default_components or [],
            "is_active": r.is_active,
            "is_institutional": r.owner_department_id is None,
            "usage_count": usage.get(r.id, 0),
        }
        for r in rows
    ]


async def create_template(
    session: AsyncSession,
    *,
    actor: User,
    name: str,
    description: str | None,
    applies_to_course_type: str,
    validation_rules: dict,
    default_components: list[dict[str, Any]],
) -> AssessmentSchemeTemplate:
    if actor.role != UserRole.hod or actor.hod_of_department_id is None:
        raise WorkflowError(
            "forbidden", "only HODs author department templates", 403
        )

    # AAT cap at the template level too, so we don't seed schemes that
    # would only be valid via HOD-override.
    aat_total = sum(
        (
            Decimal(str(c.get("weight_percent", 0)))
            for c in default_components
            if c.get("kind") == "aat"
        ),
        start=Decimal("0"),
    )
    if aat_total > _AAT_HOD_CAP:
        raise WorkflowError(
            "aat_weight_exceeded",
            f"template AAT total {aat_total}% exceeds 40%",
            400,
        )

    tpl = AssessmentSchemeTemplate(
        college_id=actor.college_id,
        owner_department_id=actor.hod_of_department_id,
        name=name.strip(),
        description=description,
        applies_to_course_type=applies_to_course_type,
        validation_rules=validation_rules or {},
        default_components=default_components,
        is_active=True,
    )
    session.add(tpl)
    await session.flush()
    await write_audit(
        session,
        action="scheme_template.create",
        entity_type="assessment_scheme_template",
        entity_id=tpl.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "name": tpl.name,
            "applies_to_course_type": tpl.applies_to_course_type,
            "component_count": len(default_components),
        },
    )
    await session.commit()
    await session.refresh(tpl)
    return tpl


async def get_template(
    session: AsyncSession, *, actor: User, template_id: UUID
) -> AssessmentSchemeTemplate:
    tpl = await session.get(AssessmentSchemeTemplate, template_id)
    if (
        tpl is None
        or tpl.college_id != actor.college_id
        or tpl.deleted_at is not None
    ):
        raise WorkflowError("not_found", "template not found", 404)
    if actor.role == UserRole.hod and tpl.owner_department_id is not None:
        if tpl.owner_department_id != actor.hod_of_department_id:
            raise WorkflowError("forbidden", "not your department's template", 403)
    return tpl


async def patch_template(
    session: AsyncSession,
    *,
    actor: User,
    template_id: UUID,
    name: str | None,
    description: str | None,
    validation_rules: dict | None,
    default_components: list[dict[str, Any]] | None,
    is_active: bool | None,
) -> AssessmentSchemeTemplate:
    tpl = await get_template(session, actor=actor, template_id=template_id)
    _require_template_writer(actor, tpl.owner_department_id)

    if name is not None:
        tpl.name = name.strip()
    if description is not None:
        tpl.description = description
    if validation_rules is not None:
        tpl.validation_rules = validation_rules
    if default_components is not None:
        aat_total = sum(
            (
                Decimal(str(c.get("weight_percent", 0)))
                for c in default_components
                if c.get("kind") == "aat"
            ),
            start=Decimal("0"),
        )
        if aat_total > _AAT_HOD_CAP:
            raise WorkflowError(
                "aat_weight_exceeded",
                f"template AAT total {aat_total}% exceeds 40%",
                400,
            )
        tpl.default_components = default_components
    if is_active is not None:
        tpl.is_active = is_active

    await write_audit(
        session,
        action="scheme_template.patch",
        entity_type="assessment_scheme_template",
        entity_id=tpl.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "name": tpl.name,
            "is_active": tpl.is_active,
            "component_count": len(tpl.default_components or []),
        },
    )
    await session.commit()
    await session.refresh(tpl)
    return tpl


async def delete_template(
    session: AsyncSession, *, actor: User, template_id: UUID
) -> None:
    tpl = await get_template(session, actor=actor, template_id=template_id)
    _require_template_writer(actor, tpl.owner_department_id)

    in_use = (
        await session.execute(
            select(func.count(AssessmentScheme.id)).where(
                AssessmentScheme.template_id == tpl.id,
                AssessmentScheme.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if int(in_use) > 0:
        raise WorkflowError(
            "template_in_use",
            f"template is in use by {int(in_use)} scheme(s); cannot delete",
            409,
        )

    tpl.deleted_at = utcnow()
    await write_audit(
        session,
        action="scheme_template.delete",
        entity_type="assessment_scheme_template",
        entity_id=tpl.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── HOD scheme-readiness card (dashboard delta) ────────────────────────────
async def get_scheme_readiness(
    session: AsyncSession, *, actor: User
) -> dict[str, Any]:
    if actor.role != UserRole.hod or actor.hod_of_department_id is None:
        raise WorkflowError(
            "forbidden", "scheme readiness is HOD-only", 403
        )

    rows = (
        await session.execute(
            select(
                CourseOffering,
                Course.code,
                Course.title,
                Course.course_type,
                Section.name.label("section_name"),
                AssessmentScheme.id.label("scheme_id"),
                AssessmentScheme.is_locked,
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .join(
                AssessmentScheme,
                AssessmentScheme.id == CourseOffering.assessment_scheme_id,
                isouter=True,
            )
            .where(
                CourseOffering.college_id == actor.college_id,
                Course.department_id == actor.hod_of_department_id,
                CourseOffering.deleted_at.is_(None),
                CourseOffering.is_active.is_(True),
            )
            .order_by(Course.code)
        )
    ).all()

    total = len(rows)
    with_scheme = sum(1 for r in rows if r.scheme_id is not None)
    locked = sum(1 for r in rows if r.is_locked)
    unlocked = with_scheme - locked

    # AAT total per offering — collect components in one query.
    scheme_ids = [r.scheme_id for r in rows if r.scheme_id is not None]
    aat_totals: dict[UUID, Decimal] = {}
    if scheme_ids:
        comp_rows = (
            await session.execute(
                select(
                    AssessmentSchemeComponent.assessment_scheme_id,
                    func.sum(AssessmentSchemeComponent.weight_percent),
                )
                .where(
                    AssessmentSchemeComponent.assessment_scheme_id.in_(scheme_ids),
                    AssessmentSchemeComponent.kind == AssessmentComponentKind.aat,
                    AssessmentSchemeComponent.deleted_at.is_(None),
                )
                .group_by(AssessmentSchemeComponent.assessment_scheme_id)
            )
        ).all()
        aat_totals = {sid: Decimal(total or 0) for sid, total in comp_rows}

    offerings = []
    for r in rows:
        offerings.append(
            {
                "course_offering_id": r.CourseOffering.id,
                "course_code": r.code,
                "course_title": r.title,
                "course_type": (
                    r.course_type.value
                    if hasattr(r.course_type, "value")
                    else str(r.course_type)
                ),
                "section_name": r.section_name,
                "is_locked": bool(r.is_locked),
                "has_scheme": r.scheme_id is not None,
                "aat_total_percent": float(
                    aat_totals.get(r.scheme_id, Decimal("0"))
                ),
            }
        )
    return {
        "total_offerings": total,
        "with_scheme": with_scheme,
        "locked": locked,
        "unlocked": unlocked,
        "offerings": offerings,
    }
