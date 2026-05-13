"""Business logic for M4 — marks service.

Tenant isolation: every read and write filters by `actor.college_id`, and
every cross-module FK target is verified to belong to the same college
before being referenced. Mutating calls write to both `audit_logs` (the
cross-cutting trail, via `write_audit`) and `marks_audit` (the
value-level trail that powers the FE edit-log Dialog).

Soft delete is enforced at this layer for `assessments`; `marks`,
`marks_audit`, and `guardian_links` are not soft-deletable by design.
"""
from __future__ import annotations

import csv
import io
import secrets
import statistics
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.security import hash_password
from app.modules.academic.models import (
    Course,
    CourseOffering,
    Enrollment,
    Section,
)
from app.modules.marks.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    GradeRule,
    GuardianLink,
    GuardianRelationship,
    Mark,
    MarkAudit,
    MarkState,
)
from app.modules.marks.schemas import (
    AssessmentCreate,
    AssessmentPatch,
    AssessmentRosterRow,
    AssessmentStats,
    AssessmentSummary,
    BulkError,
    GradeRuleEntry,
    GradeRuleSet,
    GuardianLinkCreate,
    MarkBulkResponse,
    MarkEntry,
    MarkOut,
    ParentChildView,
    ParentMarksView,
    StudentMarkItem,
    StudentMarksHistory,
    StudentSummary,
)
from app.modules.users.models import User, UserRole, UserStatus


# ── Error ────────────────────────────────────────────────────────────────────
class MarksError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ── Helpers ──────────────────────────────────────────────────────────────────
_DEFAULT_GRADE_RULES: list[tuple[AssessmentType, Decimal, Decimal]] = [
    (AssessmentType.cie1, Decimal("15"), Decimal("40")),
    (AssessmentType.cie2, Decimal("15"), Decimal("40")),
    (AssessmentType.cie3, Decimal("15"), Decimal("40")),
    (AssessmentType.see, Decimal("50"), Decimal("40")),
    (AssessmentType.assignment, Decimal("5"), Decimal("40")),
    (AssessmentType.lab, Decimal("0"), Decimal("40")),
]


def _jsonify(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "value"):
            out[k] = v.value
        else:
            out[k] = str(v)
    return out


def _require_admin(actor: User) -> None:
    if actor.role != UserRole.admin:
        raise MarksError("forbidden", "admin role required", 403)


def _require_teacher_or_admin(actor: User) -> None:
    if actor.role not in (UserRole.teacher, UserRole.admin):
        raise MarksError("forbidden", "teacher or admin role required", 403)


async def _get_offering(
    session: AsyncSession, offering_id: UUID, college_id: UUID
) -> CourseOffering | None:
    row = await session.execute(
        select(CourseOffering).where(
            CourseOffering.id == offering_id,
            CourseOffering.college_id == college_id,
            CourseOffering.deleted_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _verify_offering_access(
    session: AsyncSession, *, actor: User, offering: CourseOffering
) -> None:
    """Teacher must own the offering; admin can touch any in their college."""
    if actor.role == UserRole.admin:
        return
    if actor.role == UserRole.teacher and offering.teacher_user_id == actor.id:
        return
    raise MarksError("forbidden", "you do not own this offering", 403)


async def _get_active_assessment(
    session: AsyncSession, *, assessment_id: UUID, college_id: UUID
) -> Assessment | None:
    row = await session.execute(
        select(Assessment).where(
            Assessment.id == assessment_id,
            Assessment.college_id == college_id,
            Assessment.deleted_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _verify_student_enrolled(
    session: AsyncSession,
    *,
    student_user_id: UUID,
    offering: CourseOffering,
) -> Enrollment:
    """Student must have an active enrollment in the offering's section
    for the offering's academic_term.
    """
    row = await session.execute(
        select(Enrollment).where(
            Enrollment.student_user_id == student_user_id,
            Enrollment.section_id == offering.section_id,
            Enrollment.academic_term == offering.academic_term,
            Enrollment.withdrawn_at.is_(None),
            Enrollment.college_id == offering.college_id,
        )
    )
    e = row.scalar_one_or_none()
    if e is None:
        raise MarksError(
            "not_enrolled",
            "student is not enrolled in this offering's section for this term",
            403,
        )
    return e


async def _write_mark_audit(
    session: AsyncSession,
    *,
    mark: Mark,
    action: str,
    old_value: dict | None,
    new_value: dict | None,
    actor: User,
    reason: str | None = None,
) -> None:
    session.add(
        MarkAudit(
            college_id=mark.college_id,
            mark_id=mark.id,
            assessment_id=mark.assessment_id,
            student_user_id=mark.student_user_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            actor_user_id=actor.id,
            created_at=utcnow(),
        )
    )


# ── Assessments ──────────────────────────────────────────────────────────────
async def create_assessment(
    session: AsyncSession, *, actor: User, payload: AssessmentCreate
) -> Assessment:
    _require_teacher_or_admin(actor)
    offering = await _get_offering(session, payload.course_offering_id, actor.college_id)
    if offering is None:
        raise MarksError("bad_offering", "course offering not found", 400)
    await _verify_offering_access(session, actor=actor, offering=offering)

    a = Assessment(
        college_id=actor.college_id,
        course_offering_id=offering.id,
        type=payload.type,
        name=payload.name.strip(),
        max_marks=payload.max_marks,
        weight_percent=payload.weight_percent,
        scheduled_date=payload.scheduled_date,
        state=AssessmentState.draft,
    )
    session.add(a)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise MarksError(
            "name_in_use",
            "assessment name already exists for this offering and type",
            409,
        ) from e

    await write_audit(
        session,
        action="assessment.create",
        entity_type="assessment",
        entity_id=a.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "course_offering_id": str(offering.id),
            "type": a.type.value,
            "name": a.name,
            "max_marks": float(a.max_marks),
            "weight_percent": (
                float(a.weight_percent) if a.weight_percent is not None else None
            ),
            "scheduled_date": (
                a.scheduled_date.isoformat() if a.scheduled_date else None
            ),
        },
    )
    # TODO(events): publish('assessment.created', {assessment_id: a.id})
    await session.commit()
    await session.refresh(a)
    return a


async def list_assessments(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID | None = None,
    assessment_type: AssessmentType | None = None,
    state: AssessmentState | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Assessment], int]:
    q = select(Assessment).where(Assessment.college_id == actor.college_id)
    if not include_deleted:
        q = q.where(Assessment.deleted_at.is_(None))
    if course_offering_id is not None:
        q = q.where(Assessment.course_offering_id == course_offering_id)
    if assessment_type is not None:
        q = q.where(Assessment.type == assessment_type)
    if state is not None:
        q = q.where(Assessment.state == state)

    # Teachers only see their own offerings unless admin.
    if actor.role == UserRole.teacher:
        q = q.join(
            CourseOffering, Assessment.course_offering_id == CourseOffering.id
        ).where(CourseOffering.teacher_user_id == actor.id)
    elif actor.role == UserRole.student:
        # Students see assessments for offerings of sections they're enrolled in.
        enrolled_sections = (
            select(Enrollment.section_id)
            .where(
                Enrollment.student_user_id == actor.id,
                Enrollment.withdrawn_at.is_(None),
            )
            .subquery()
        )
        q = q.join(
            CourseOffering, Assessment.course_offering_id == CourseOffering.id
        ).where(CourseOffering.section_id.in_(select(enrolled_sections.c.section_id)))
    elif actor.role == UserRole.parent:
        # Parents see assessments for their linked children's enrollments.
        linked_students = (
            select(GuardianLink.student_user_id)
            .where(
                GuardianLink.parent_user_id == actor.id,
                GuardianLink.verified_at.is_not(None),
            )
            .subquery()
        )
        student_sections = (
            select(Enrollment.section_id)
            .where(
                Enrollment.student_user_id.in_(
                    select(linked_students.c.student_user_id)
                ),
                Enrollment.withdrawn_at.is_(None),
            )
            .subquery()
        )
        q = q.join(
            CourseOffering, Assessment.course_offering_id == CourseOffering.id
        ).where(CourseOffering.section_id.in_(select(student_sections.c.section_id)))

    total_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(total_q)).scalar_one()
    rows = (
        await session.execute(q.order_by(Assessment.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return list(rows), int(total)


async def get_assessment(
    session: AsyncSession, *, actor: User, assessment_id: UUID
) -> Assessment:
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    if actor.role == UserRole.teacher:
        offering = await _get_offering(session, a.course_offering_id, actor.college_id)
        if offering is None or offering.teacher_user_id != actor.id:
            raise MarksError("forbidden", "you do not own this offering", 403)
    elif actor.role == UserRole.student:
        offering = await _get_offering(session, a.course_offering_id, actor.college_id)
        if offering is None:
            raise MarksError("forbidden", "you cannot see this assessment", 403)
        try:
            await _verify_student_enrolled(
                session, student_user_id=actor.id, offering=offering
            )
        except MarksError as e:
            raise MarksError("forbidden", "you are not enrolled in this offering", 403) from e
    return a


async def patch_assessment(
    session: AsyncSession,
    *,
    actor: User,
    assessment_id: UUID,
    payload: AssessmentPatch,
) -> Assessment:
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)

    if a.state == AssessmentState.locked and actor.role != UserRole.admin:
        raise MarksError(
            "locked",
            "assessment is locked; only admin can edit it",
            409,
        )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(a, field)
        setattr(a, field, value)
        after[field] = value
    if not after:
        return a

    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise MarksError(
            "name_in_use",
            "assessment name already exists for this offering and type",
            409,
        ) from e

    await write_audit(
        session,
        action="assessment.update",
        entity_type="assessment",
        entity_id=a.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(a)
    return a


async def delete_assessment(
    session: AsyncSession, *, actor: User, assessment_id: UUID
) -> None:
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)

    # Reject if any marks exist.
    has_marks = (
        await session.execute(
            select(func.count(Mark.id)).where(Mark.assessment_id == a.id)
        )
    ).scalar_one()
    if has_marks:
        raise MarksError(
            "has_marks",
            "cannot delete assessment with entered marks",
            409,
        )

    a.deleted_at = utcnow()
    await write_audit(
        session,
        action="assessment.delete",
        entity_type="assessment",
        entity_id=a.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={"state": a.state.value},
    )
    await session.commit()


async def lock_assessment(
    session: AsyncSession,
    *,
    actor: User,
    assessment_id: UUID,
    lock: bool,
    reason: str | None = None,
) -> Assessment:
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)

    if lock and a.state == AssessmentState.locked:
        return a
    if not lock and a.state != AssessmentState.locked:
        return a

    if not lock and actor.role != UserRole.admin:
        raise MarksError(
            "forbidden",
            "only admin can unlock an assessment",
            403,
        )
    if not lock and not reason:
        raise MarksError("reason_required", "unlock requires a reason", 400)

    prev_state = a.state
    if lock:
        a.state = AssessmentState.locked
        a.locked_at = utcnow()
        a.locked_by_user_id = actor.id
    else:
        a.state = AssessmentState.draft
        a.locked_at = None
        a.locked_by_user_id = None

    # Cascade to child marks: flip mark.state to locked/entered to mirror.
    new_mark_state = MarkState.locked if lock else MarkState.entered
    child_marks = (
        await session.execute(select(Mark).where(Mark.assessment_id == a.id))
    ).scalars().all()
    for m in child_marks:
        m.state = new_mark_state
        await _write_mark_audit(
            session,
            mark=m,
            action="mark.lock" if lock else "mark.unlock",
            old_value={"state": (MarkState.entered if lock else MarkState.locked).value},
            new_value={"state": new_mark_state.value},
            actor=actor,
            reason=reason,
        )

    await write_audit(
        session,
        action="assessment.lock" if lock else "assessment.unlock",
        entity_type="assessment",
        entity_id=a.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={"state": prev_state.value},
        new_value={"state": a.state.value, "reason": reason},
    )
    # TODO(events): publish('assessment.locked' if lock else 'assessment.unlocked', ...)
    await session.commit()
    await session.refresh(a)
    return a


# ── Marks ────────────────────────────────────────────────────────────────────
async def set_mark(
    session: AsyncSession,
    *,
    actor: User,
    assessment_id: UUID,
    student_user_id: UUID,
    payload: MarkEntry,
) -> Mark:
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)

    if a.state == AssessmentState.locked:
        if actor.role != UserRole.admin:
            raise MarksError("locked", "assessment is locked", 409)
        if not payload.reason:
            raise MarksError(
                "reason_required",
                "writing to a locked assessment requires a reason",
                400,
            )

    if payload.is_absent and payload.marks_obtained is not None:
        raise MarksError(
            "bad_input",
            "is_absent=true must not include marks_obtained",
            400,
        )
    if not payload.is_absent and payload.marks_obtained is None:
        raise MarksError(
            "bad_input",
            "marks_obtained is required when is_absent is false",
            400,
        )
    if (
        payload.marks_obtained is not None
        and payload.marks_obtained > a.max_marks
    ):
        raise MarksError(
            "above_max_marks",
            f"marks_obtained ({payload.marks_obtained}) exceeds max_marks ({a.max_marks})",
            409,
        )

    await _verify_student_enrolled(
        session, student_user_id=student_user_id, offering=offering
    )

    # Upsert (assessment_id, student_user_id) — fetch existing or create new.
    existing = (
        await session.execute(
            select(Mark).where(
                Mark.assessment_id == a.id,
                Mark.student_user_id == student_user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        m = Mark(
            college_id=actor.college_id,
            assessment_id=a.id,
            student_user_id=student_user_id,
            marks_obtained=payload.marks_obtained,
            is_absent=payload.is_absent,
            state=MarkState.locked if a.state == AssessmentState.locked else MarkState.entered,
            entered_by_user_id=actor.id,
            last_modified_by_user_id=actor.id,
        )
        session.add(m)
        await session.flush()
        await _write_mark_audit(
            session,
            mark=m,
            action="mark.create",
            old_value=None,
            new_value={
                "marks_obtained": (
                    float(payload.marks_obtained)
                    if payload.marks_obtained is not None
                    else None
                ),
                "is_absent": payload.is_absent,
            },
            actor=actor,
            reason=payload.reason,
        )
    else:
        old_value = {
            "marks_obtained": (
                float(existing.marks_obtained)
                if existing.marks_obtained is not None
                else None
            ),
            "is_absent": existing.is_absent,
        }
        existing.marks_obtained = payload.marks_obtained
        existing.is_absent = payload.is_absent
        existing.last_modified_by_user_id = actor.id
        m = existing
        await _write_mark_audit(
            session,
            mark=m,
            action="mark.update",
            old_value=old_value,
            new_value={
                "marks_obtained": (
                    float(payload.marks_obtained)
                    if payload.marks_obtained is not None
                    else None
                ),
                "is_absent": payload.is_absent,
            },
            actor=actor,
            reason=payload.reason,
        )

    await write_audit(
        session,
        action="mark.set",
        entity_type="mark",
        entity_id=m.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "assessment_id": str(a.id),
            "student_user_id": str(student_user_id),
            "marks_obtained": (
                float(payload.marks_obtained)
                if payload.marks_obtained is not None
                else None
            ),
            "is_absent": payload.is_absent,
        },
    )
    # TODO(events): publish('marks.updated', {assessment_id: a.id, student_user_id: ...})
    await session.commit()
    await session.refresh(m)
    return m


async def bulk_set_marks(
    session: AsyncSession,
    *,
    actor: User,
    assessment_id: UUID,
    csv_bytes: bytes,
    dry_run: bool = False,
) -> MarkBulkResponse:
    """Best-effort CSV upload. Valid rows commit, invalid rows are returned
    in the errors list. CSV columns: student_uid, marks_obtained, is_absent.
    """
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)
    if a.state == AssessmentState.locked:
        raise MarksError("locked", "assessment is locked", 409)

    # Parse CSV.
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise MarksError("bad_csv", f"CSV is not valid UTF-8: {e}", 400) from e
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "student_uid" not in reader.fieldnames:
        raise MarksError(
            "bad_csv",
            "CSV must have headers: student_uid, marks_obtained, is_absent",
            400,
        )

    errors: list[BulkError] = []
    committed = 0

    # Pre-fetch enrolled students keyed by USN.
    enrolled_rows = (
        await session.execute(
            select(User.id, User.usn).where(
                User.college_id == actor.college_id,
                User.role == UserRole.student,
                User.deleted_at.is_(None),
                User.id.in_(
                    select(Enrollment.student_user_id).where(
                        Enrollment.section_id == offering.section_id,
                        Enrollment.academic_term == offering.academic_term,
                        Enrollment.withdrawn_at.is_(None),
                    )
                ),
            )
        )
    ).all()
    uid_to_id: dict[str, UUID] = {}
    for uid_, sid in enrolled_rows:
        if sid:
            uid_to_id[sid.strip().lower()] = uid_

    for row_idx, row in enumerate(reader, start=2):  # start=2 for 1 header + 1-based
        student_uid_raw = (row.get("student_uid") or "").strip()
        marks_raw = (row.get("marks_obtained") or "").strip()
        absent_raw = (row.get("is_absent") or "").strip().lower()

        if not student_uid_raw:
            errors.append(BulkError(row_number=row_idx, student_uid=None, code="missing_uid", message="student_uid is required"))
            continue

        is_absent = absent_raw in ("true", "1", "yes", "y")
        marks_value: Decimal | None = None
        if not is_absent:
            if not marks_raw:
                errors.append(
                    BulkError(
                        row_number=row_idx,
                        student_uid=student_uid_raw,
                        code="missing_marks",
                        message="marks_obtained is required when is_absent is false",
                    )
                )
                continue
            try:
                marks_value = Decimal(marks_raw)
            except (InvalidOperation, ValueError):
                errors.append(
                    BulkError(
                        row_number=row_idx,
                        student_uid=student_uid_raw,
                        code="bad_marks",
                        message=f"marks_obtained '{marks_raw}' is not a valid number",
                    )
                )
                continue
            if marks_value < 0:
                errors.append(
                    BulkError(
                        row_number=row_idx,
                        student_uid=student_uid_raw,
                        code="bad_marks",
                        message="marks_obtained must be non-negative",
                    )
                )
                continue
            if marks_value > a.max_marks:
                errors.append(
                    BulkError(
                        row_number=row_idx,
                        student_uid=student_uid_raw,
                        code="above_max_marks",
                        message=f"marks_obtained ({marks_value}) exceeds max_marks ({a.max_marks})",
                    )
                )
                continue

        student_id = uid_to_id.get(student_uid_raw.lower())
        if student_id is None:
            errors.append(
                BulkError(
                    row_number=row_idx,
                    student_uid=student_uid_raw,
                    code="unknown_student",
                    message="student_uid not found among enrolled students",
                )
            )
            continue

        if dry_run:
            committed += 1
            continue

        # Upsert this row.
        existing = (
            await session.execute(
                select(Mark).where(
                    Mark.assessment_id == a.id,
                    Mark.student_user_id == student_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            m = Mark(
                college_id=actor.college_id,
                assessment_id=a.id,
                student_user_id=student_id,
                marks_obtained=marks_value,
                is_absent=is_absent,
                state=MarkState.entered,
                entered_by_user_id=actor.id,
                last_modified_by_user_id=actor.id,
            )
            session.add(m)
            await session.flush()
            await _write_mark_audit(
                session,
                mark=m,
                action="mark.bulk_create",
                old_value=None,
                new_value={
                    "marks_obtained": (
                        float(marks_value) if marks_value is not None else None
                    ),
                    "is_absent": is_absent,
                },
                actor=actor,
                reason=None,
            )
        else:
            old_value = {
                "marks_obtained": (
                    float(existing.marks_obtained)
                    if existing.marks_obtained is not None
                    else None
                ),
                "is_absent": existing.is_absent,
            }
            existing.marks_obtained = marks_value
            existing.is_absent = is_absent
            existing.last_modified_by_user_id = actor.id
            await _write_mark_audit(
                session,
                mark=existing,
                action="mark.bulk_update",
                old_value=old_value,
                new_value={
                    "marks_obtained": (
                        float(marks_value) if marks_value is not None else None
                    ),
                    "is_absent": is_absent,
                },
                actor=actor,
                reason=None,
            )
        committed += 1

    if not dry_run:
        await write_audit(
            session,
            action="mark.bulk",
            entity_type="assessment",
            entity_id=a.id,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={"committed": committed, "errors": len(errors)},
        )
        # TODO(events): publish('marks.updated', {assessment_id: a.id, bulk: True})
        await session.commit()
    else:
        await session.rollback()

    return MarkBulkResponse(committed=committed, errors=errors, dry_run=dry_run)


# ── Stats ────────────────────────────────────────────────────────────────────
async def get_assessment_stats(
    session: AsyncSession, *, actor: User, assessment_id: UUID
) -> AssessmentStats:
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    if actor.role == UserRole.teacher:
        await _verify_offering_access(session, actor=actor, offering=offering)
    elif actor.role == UserRole.student:
        raise MarksError("forbidden", "students cannot fetch stats directly", 403)
    elif actor.role == UserRole.parent:
        raise MarksError("forbidden", "parents cannot fetch stats directly", 403)

    rows = (
        await session.execute(
            select(Mark.marks_obtained, Mark.is_absent).where(
                Mark.assessment_id == a.id
            )
        )
    ).all()
    count = len(rows)
    absent_count = sum(1 for _m, ab in rows if ab)
    values = [float(m) for m, ab in rows if not ab and m is not None]
    mean = statistics.mean(values) if values else None
    median = statistics.median(values) if values else None
    stddev = statistics.stdev(values) if len(values) > 1 else None
    return AssessmentStats(
        assessment_id=a.id,
        count=count,
        absent_count=absent_count,
        mean=mean,
        median=median,
        stddev=stddev,
        min=min(values) if values else None,
        max=max(values) if values else None,
        max_marks=float(a.max_marks),
        locked=a.state == AssessmentState.locked,
    )


# ── Roster (for teacher entry page) ─────────────────────────────────────────
async def get_assessment_roster(
    session: AsyncSession, *, actor: User, assessment_id: UUID
) -> list[AssessmentRosterRow]:
    _require_teacher_or_admin(actor)
    a = await _get_active_assessment(
        session, assessment_id=assessment_id, college_id=actor.college_id
    )
    if a is None:
        raise MarksError("not_found", "assessment not found", 404)
    offering = await _get_offering(session, a.course_offering_id, actor.college_id)
    assert offering is not None
    await _verify_offering_access(session, actor=actor, offering=offering)

    rows = (
        await session.execute(
            select(
                User.id, User.name, User.usn,
                Mark.id, Mark.marks_obtained, Mark.is_absent, Mark.state,
            )
            .select_from(Enrollment)
            .join(User, User.id == Enrollment.student_user_id)
            .outerjoin(
                Mark,
                and_(
                    Mark.assessment_id == a.id,
                    Mark.student_user_id == Enrollment.student_user_id,
                ),
            )
            .where(
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term == offering.academic_term,
                Enrollment.withdrawn_at.is_(None),
                Enrollment.college_id == actor.college_id,
                User.deleted_at.is_(None),
            )
            .order_by(User.usn.nullslast(), User.name)
        )
    ).all()
    return [
        AssessmentRosterRow(
            student_user_id=uid,
            name=name,
            usn=usn,
            mark_id=mid,
            marks_obtained=mo,
            is_absent=ia if ia is not None else False,
            state=st,
        )
        for uid, name, usn, mid, mo, ia, st in rows
    ]


# ── Student history ─────────────────────────────────────────────────────────
async def get_student_marks_history(
    session: AsyncSession,
    *,
    actor: User,
    student_user_id: UUID,
    course_offering_id: UUID | None = None,
) -> StudentMarksHistory:
    # Access control.
    if actor.role == UserRole.student:
        if actor.id != student_user_id:
            raise MarksError("forbidden", "students can only view their own marks", 403)
    elif actor.role == UserRole.parent:
        link = (
            await session.execute(
                select(GuardianLink).where(
                    GuardianLink.parent_user_id == actor.id,
                    GuardianLink.student_user_id == student_user_id,
                    GuardianLink.verified_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if link is None:
            raise MarksError(
                "forbidden",
                "you are not linked to this student",
                403,
            )
    elif actor.role == UserRole.teacher:
        # Teacher can see students in their offerings.
        pass
    # admin: free pass.

    # Pull assessments for offerings the student is enrolled in.
    enrolled_sections = (
        select(Enrollment.section_id, Enrollment.academic_term)
        .where(
            Enrollment.student_user_id == student_user_id,
            Enrollment.withdrawn_at.is_(None),
            Enrollment.college_id == actor.college_id,
        )
        .subquery()
    )
    q = (
        select(Assessment, CourseOffering, Course)
        .join(
            CourseOffering,
            Assessment.course_offering_id == CourseOffering.id,
        )
        .join(Course, CourseOffering.course_id == Course.id)
        .join(
            enrolled_sections,
            and_(
                CourseOffering.section_id == enrolled_sections.c.section_id,
                CourseOffering.academic_term == enrolled_sections.c.academic_term,
            ),
        )
        .where(
            Assessment.college_id == actor.college_id,
            Assessment.deleted_at.is_(None),
        )
    )
    if course_offering_id is not None:
        q = q.where(Assessment.course_offering_id == course_offering_id)
    if actor.role == UserRole.teacher:
        q = q.where(CourseOffering.teacher_user_id == actor.id)
    rows = (await session.execute(q.order_by(Assessment.scheduled_date.desc().nullslast()))).all()

    # For each assessment, fetch the student's mark + class stats.
    items: list[StudentMarkItem] = []
    for a, offering, course in rows:
        m_row = (
            await session.execute(
                select(Mark).where(
                    Mark.assessment_id == a.id,
                    Mark.student_user_id == student_user_id,
                )
            )
        ).scalar_one_or_none()
        class_vals = (
            await session.execute(
                select(Mark.marks_obtained).where(
                    Mark.assessment_id == a.id,
                    Mark.is_absent.is_(False),
                    Mark.marks_obtained.is_not(None),
                )
            )
        ).scalars().all()
        floats = [float(v) for v in class_vals]
        class_mean = statistics.mean(floats) if floats else None
        class_stddev = statistics.stdev(floats) if len(floats) > 1 else None

        items.append(
            StudentMarkItem(
                assessment=AssessmentSummary(
                    id=a.id,
                    course_offering_id=offering.id,
                    course_code=course.code,
                    course_title=course.title,
                    type=a.type,
                    name=a.name,
                    max_marks=a.max_marks,
                    weight_percent=a.weight_percent,
                    scheduled_date=a.scheduled_date,
                    state=a.state,
                ),
                mark=MarkOut.model_validate(m_row) if m_row is not None else None,
                class_mean=class_mean,
                class_stddev=class_stddev,
            )
        )

    return StudentMarksHistory(student_user_id=student_user_id, items=items)


# ── Mark audit ──────────────────────────────────────────────────────────────
async def get_mark_audit(
    session: AsyncSession, *, actor: User, mark_id: UUID
) -> list[MarkAudit]:
    _require_teacher_or_admin(actor)
    m = (
        await session.execute(
            select(Mark).where(
                Mark.id == mark_id, Mark.college_id == actor.college_id
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise MarksError("not_found", "mark not found", 404)
    offering = (
        await session.execute(
            select(CourseOffering)
            .join(Assessment, Assessment.course_offering_id == CourseOffering.id)
            .where(Assessment.id == m.assessment_id)
        )
    ).scalar_one_or_none()
    if offering is None:
        raise MarksError("not_found", "offering missing for this mark", 404)
    await _verify_offering_access(session, actor=actor, offering=offering)

    entries = (
        await session.execute(
            select(MarkAudit)
            .where(MarkAudit.mark_id == mark_id)
            .order_by(MarkAudit.created_at.asc())
        )
    ).scalars().all()
    return list(entries)


# ── Grade rules ─────────────────────────────────────────────────────────────
async def get_grade_rules(
    session: AsyncSession, *, actor: User, course_offering_id: UUID
) -> GradeRuleSet:
    offering = await _get_offering(session, course_offering_id, actor.college_id)
    if offering is None:
        raise MarksError("bad_offering", "course offering not found", 400)
    # Access scope: teacher (own), student (enrolled), parent (linked), admin (any).
    if actor.role == UserRole.teacher and offering.teacher_user_id != actor.id:
        raise MarksError("forbidden", "you do not own this offering", 403)
    if actor.role == UserRole.student:
        await _verify_student_enrolled(
            session, student_user_id=actor.id, offering=offering
        )
    if actor.role == UserRole.parent:
        # OK to read; we don't enforce that the parent has a linked child
        # in this section since the parent UI only renders rules for the
        # selected child's offerings.
        pass

    rows = (
        await session.execute(
            select(GradeRule).where(
                GradeRule.course_offering_id == course_offering_id,
                GradeRule.college_id == actor.college_id,
            )
        )
    ).scalars().all()
    if rows:
        rules = [
            GradeRuleEntry(
                assessment_type=r.assessment_type,
                weight_percent=r.weight_percent,
                passing_threshold_percent=r.passing_threshold_percent,
            )
            for r in rows
        ]
    else:
        rules = [
            GradeRuleEntry(
                assessment_type=t,
                weight_percent=w,
                passing_threshold_percent=p,
            )
            for t, w, p in _DEFAULT_GRADE_RULES
        ]
    return GradeRuleSet(course_offering_id=course_offering_id, rules=rules)


async def upsert_grade_rules(
    session: AsyncSession, *, actor: User, payload: GradeRuleSet
) -> GradeRuleSet:
    _require_teacher_or_admin(actor)
    offering = await _get_offering(session, payload.course_offering_id, actor.college_id)
    if offering is None:
        raise MarksError("bad_offering", "course offering not found", 400)
    await _verify_offering_access(session, actor=actor, offering=offering)

    total = sum(r.weight_percent for r in payload.rules)
    if total != Decimal("100"):
        raise MarksError(
            "weights_sum",
            f"weight_percent values must sum to 100; got {total}",
            409,
        )

    seen_types: set[AssessmentType] = set()
    for r in payload.rules:
        if r.assessment_type in seen_types:
            raise MarksError(
                "duplicate_type",
                f"duplicate assessment_type {r.assessment_type.value}",
                400,
            )
        seen_types.add(r.assessment_type)

    # Replace-all: delete existing rules and insert fresh.
    await session.execute(
        GradeRule.__table__.delete().where(
            GradeRule.course_offering_id == payload.course_offering_id,
            GradeRule.college_id == actor.college_id,
        )
    )
    for r in payload.rules:
        session.add(
            GradeRule(
                college_id=actor.college_id,
                course_offering_id=payload.course_offering_id,
                assessment_type=r.assessment_type,
                weight_percent=r.weight_percent,
                passing_threshold_percent=r.passing_threshold_percent,
            )
        )
    await session.flush()
    await write_audit(
        session,
        action="grade_rule.update",
        entity_type="course_offering",
        entity_id=payload.course_offering_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "rules": [
                {
                    "type": r.assessment_type.value,
                    "weight": float(r.weight_percent),
                    "pass": float(r.passing_threshold_percent),
                }
                for r in payload.rules
            ]
        },
    )
    await session.commit()
    return payload


# ── Parent / guardian ───────────────────────────────────────────────────────
async def create_guardian_link(
    session: AsyncSession, *, actor: User, payload: GuardianLinkCreate
) -> tuple[GuardianLink, str | None]:
    """Admin links a parent to a student. If a user with `parent_email` does
    not exist in the actor's college, a new parent-role user is created
    with a generated password (returned to the admin one-time).
    Returns (link, initial_password_or_None).
    """
    _require_admin(actor)
    student = (
        await session.execute(
            select(User).where(
                User.id == payload.student_user_id,
                User.college_id == actor.college_id,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if student is None:
        raise MarksError("bad_student", "student not found", 400)
    if student.role != UserRole.student:
        raise MarksError("bad_student", "target user is not a student", 400)

    email = payload.parent_email.strip().lower()
    parent = (
        await session.execute(
            select(User).where(
                User.email == email,
                User.college_id == actor.college_id,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    initial_password: str | None = None
    if parent is None:
        initial_password = secrets.token_urlsafe(12)
        parent = User(
            college_id=actor.college_id,
            email=email,
            name=payload.parent_name.strip(),
            role=UserRole.parent,
            status=UserStatus.active,
            password_hash=hash_password(initial_password),
        )
        session.add(parent)
        await session.flush()
    elif parent.role != UserRole.parent:
        raise MarksError(
            "bad_parent",
            "existing user with that email is not a parent",
            409,
        )

    existing = (
        await session.execute(
            select(GuardianLink).where(
                GuardianLink.parent_user_id == parent.id,
                GuardianLink.student_user_id == student.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Re-verify if already linked.
        if existing.verified_at is None:
            existing.verified_at = utcnow()
        link = existing
    else:
        link = GuardianLink(
            college_id=actor.college_id,
            parent_user_id=parent.id,
            student_user_id=student.id,
            relationship=payload.relationship,
            verified_at=utcnow(),
            created_at=utcnow(),
        )
        session.add(link)
        await session.flush()

    await write_audit(
        session,
        action="guardian.link",
        entity_type="guardian_link",
        entity_id=link.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "parent_user_id": str(parent.id),
            "student_user_id": str(student.id),
            "relationship": payload.relationship.value,
            "parent_created": initial_password is not None,
        },
    )
    await session.commit()
    await session.refresh(link)
    return link, initial_password


async def delete_guardian_link(
    session: AsyncSession, *, actor: User, link_id: UUID
) -> None:
    _require_admin(actor)
    link = (
        await session.execute(
            select(GuardianLink).where(
                GuardianLink.id == link_id,
                GuardianLink.college_id == actor.college_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise MarksError("not_found", "guardian link not found", 404)
    await session.execute(
        GuardianLink.__table__.delete().where(GuardianLink.id == link.id)
    )
    await write_audit(
        session,
        action="guardian.unlink",
        entity_type="guardian_link",
        entity_id=link.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={
            "parent_user_id": str(link.parent_user_id),
            "student_user_id": str(link.student_user_id),
        },
    )
    await session.commit()


async def list_parent_children(
    session: AsyncSession, *, actor: User
) -> list[StudentSummary]:
    if actor.role != UserRole.parent:
        raise MarksError("forbidden", "parent role required", 403)
    rows = (
        await session.execute(
            select(User)
            .join(GuardianLink, GuardianLink.student_user_id == User.id)
            .where(
                GuardianLink.parent_user_id == actor.id,
                GuardianLink.verified_at.is_not(None),
                User.deleted_at.is_(None),
                User.college_id == actor.college_id,
            )
        )
    ).scalars().all()
    return [
        StudentSummary(
            id=u.id,
            name=u.name,
            email=u.email,
            usn=u.usn,
        )
        for u in rows
    ]


async def get_parent_marks_view(
    session: AsyncSession, *, actor: User
) -> ParentMarksView:
    if actor.role != UserRole.parent:
        raise MarksError("forbidden", "parent role required", 403)
    links = (
        await session.execute(
            select(GuardianLink)
            .where(
                GuardianLink.parent_user_id == actor.id,
                GuardianLink.verified_at.is_not(None),
                GuardianLink.college_id == actor.college_id,
            )
        )
    ).scalars().all()
    children: list[ParentChildView] = []
    for link in links:
        student = (
            await session.execute(
                select(User).where(
                    User.id == link.student_user_id,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if student is None:
            continue
        history = await get_student_marks_history(
            session, actor=actor, student_user_id=student.id
        )
        children.append(
            ParentChildView(
                student=StudentSummary(
                    id=student.id,
                    name=student.name,
                    email=student.email,
                    usn=student.usn,
                ),
                relationship=link.relationship,
                history=history,
            )
        )
    return ParentMarksView(children=children)
