"""Business logic for M3 — attendance service.

Three independent anti-proxy layers on submit:

1. QR token   — JWT signature + DB jti row not revoked + within validity window
2. GPS        — haversine vs. room centroid, > threshold ⇒ flagged (not rejected)
3. Face match — handed to M8 stub (frame discarded), confidence < 0.6 ⇒ flagged

Plus device anti-replay: one (session, device_fingerprint) row in `device_logs`
allowed (DB unique index); a second submit from the same phone → 409.

Materialiser is idempotent. Re-running on `timetable.updated` patches
room/time on existing rows but never resets state.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    Enrollment,
    Room,
    Section,
    TimetableException,
    TimetableExceptionKind,
    TimetableSlot,
)
from app.modules.attendance.face_stub import verify_face_stub
from app.modules.attendance.geo import haversine_m
from app.modules.attendance.models import (
    AttendanceOverride,
    AttendanceRecord,
    AttendanceRecordState,
    ClassSession,
    ClassSessionSource,
    ClassSessionState,
    DeviceLog,
    QRToken,
)
from app.modules.attendance.qr import QRInvalidError, sign_qr, verify_qr
from app.modules.attendance.schemas import (
    AttendanceReport,
    AttendanceReportRow,
    AttendanceSubmit,
    OverrideRequest,
    SessionFeed,
    SessionFeedRow,
)
from app.modules.users.models import User, UserRole


# ── Error ────────────────────────────────────────────────────────────────────
class AttendanceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ── Constants ────────────────────────────────────────────────────────────────
FACE_CONFIDENCE_THRESHOLD = Decimal("0.6")
DEFAULT_MATERIALISE_WINDOW_DAYS = 14


# ── Helpers ──────────────────────────────────────────────────────────────────
def _require_teacher_or_admin(actor: User) -> None:
    if actor.role not in (UserRole.teacher, UserRole.admin):
        raise AttendanceError("forbidden", "teacher or admin role required", 403)


def _require_student(actor: User) -> None:
    if actor.role != UserRole.student:
        raise AttendanceError("forbidden", "student role required", 403)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ensure_owner(actor: User, offering: CourseOffering) -> None:
    """Admin can act on any offering; teacher only on their own."""
    if actor.role == UserRole.admin:
        return
    if offering.teacher_user_id != actor.id:
        raise AttendanceError(
            "forbidden", "you do not own this course offering", 403
        )


# ── Materialiser ─────────────────────────────────────────────────────────────
async def materialise_offering(
    session: AsyncSession,
    *,
    offering_id: UUID,
    from_date: date,
    to_date: date,
) -> int:
    """Idempotently materialise class_sessions for one offering across a date window.

    Returns the count of (offering, date, start_time) tuples upserted.

    Algorithm:
    1. For each active timetable_slot of this offering:
       expand effective_from..effective_until ∩ [from_date, to_date] by day_of_week
    2. Subtract academic_calendar holidays (cancels_classes=TRUE) that apply
    3. Apply timetable_exceptions: cancel drops, reschedule moves times,
       room_change swaps room
    4. Add kind='extra' rows as standalone sessions
    5. UPSERT via ON CONFLICT (course_offering_id, scheduled_date, start_time)
       — only touches room_id, end_time, origin_exception_id; never state.
    """
    offering = (
        await session.execute(
            select(CourseOffering).where(
                CourseOffering.id == offering_id,
                CourseOffering.deleted_at.is_(None),
                CourseOffering.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if offering is None:
        return 0

    # Active slots for this offering.
    slots = (
        await session.execute(
            select(TimetableSlot).where(
                TimetableSlot.course_offering_id == offering_id,
                TimetableSlot.deleted_at.is_(None),
                TimetableSlot.effective_until >= from_date,
                TimetableSlot.effective_from <= to_date,
            )
        )
    ).scalars().all()

    # Calendar holidays (college-wide OR matching the offering's department).
    course = await session.get(Course, offering.course_id)
    if course is None:
        return 0
    dept_id = course.department_id

    holidays = (
        await session.execute(
            select(AcademicCalendarEntry.entry_date).where(
                AcademicCalendarEntry.college_id == offering.college_id,
                AcademicCalendarEntry.deleted_at.is_(None),
                AcademicCalendarEntry.cancels_classes.is_(True),
                AcademicCalendarEntry.entry_date >= from_date,
                AcademicCalendarEntry.entry_date <= to_date,
                or_(
                    AcademicCalendarEntry.applies_to_department_id.is_(None),
                    AcademicCalendarEntry.applies_to_department_id == dept_id,
                ),
            )
        )
    ).scalars().all()
    holiday_dates = set(holidays)

    # Exceptions for this offering in the window.
    exceptions = (
        await session.execute(
            select(TimetableException).where(
                TimetableException.course_offering_id == offering_id,
                TimetableException.exception_date >= from_date,
                TimetableException.exception_date <= to_date,
            )
        )
    ).scalars().all()
    # Map (slot_id, date) → exception for slot-targeted kinds.
    slot_exceptions: dict[tuple[UUID, date], TimetableException] = {}
    extra_exceptions: list[TimetableException] = []
    for exc in exceptions:
        if exc.kind == TimetableExceptionKind.extra:
            extra_exceptions.append(exc)
        elif exc.original_slot_id is not None:
            slot_exceptions[(exc.original_slot_id, exc.exception_date)] = exc

    # Build the candidate set.
    candidates: list[dict[str, Any]] = []
    now = utcnow()
    for slot in slots:
        slot_from = max(slot.effective_from, from_date)
        slot_until = min(slot.effective_until, to_date)
        if slot_from > slot_until:
            continue
        d = slot_from
        while d <= slot_until:
            if d.weekday() == slot.day_of_week and d not in holiday_dates:
                exc = slot_exceptions.get((slot.id, d))
                if exc is not None and exc.kind == TimetableExceptionKind.cancel:
                    d += timedelta(days=1)
                    continue
                room_id = slot.room_id
                start = slot.start_time
                end = slot.end_time
                origin_exception_id: UUID | None = None
                if exc is not None:
                    origin_exception_id = exc.id
                    if exc.kind == TimetableExceptionKind.room_change:
                        room_id = exc.new_room_id
                    elif exc.kind == TimetableExceptionKind.reschedule:
                        start = exc.new_start_time or start
                        end = exc.new_end_time or end
                        if exc.new_room_id is not None:
                            room_id = exc.new_room_id
                candidates.append({
                    "id": uuid4(),
                    "college_id": offering.college_id,
                    "course_offering_id": offering_id,
                    "room_id": room_id,
                    "scheduled_date": d,
                    "start_time": start,
                    "end_time": end,
                    "state": ClassSessionState.pending.value,
                    "source": ClassSessionSource.materialised.value,
                    "origin_slot_id": slot.id,
                    "origin_exception_id": origin_exception_id,
                    "created_at": now,
                    "updated_at": now,
                })
            d += timedelta(days=1)

    # Extra-kind exceptions: standalone sessions with no parent slot.
    for exc in extra_exceptions:
        if exc.exception_date in holiday_dates:
            continue
        if exc.new_start_time is None or exc.new_end_time is None:
            continue
        candidates.append({
            "id": uuid4(),
            "college_id": offering.college_id,
            "course_offering_id": offering_id,
            "room_id": exc.new_room_id,
            "scheduled_date": exc.exception_date,
            "start_time": exc.new_start_time,
            "end_time": exc.new_end_time,
            "state": ClassSessionState.pending.value,
            "source": ClassSessionSource.extra.value,
            "origin_slot_id": None,
            "origin_exception_id": exc.id,
            "created_at": now,
            "updated_at": now,
        })

    if not candidates:
        return 0

    # UPSERT. The unique index `uq_class_sessions_offering_date_start_active`
    # is partial (deleted_at IS NULL), so we need to phrase the conflict
    # clause via index_elements with a predicate.
    stmt = pg_insert(ClassSession.__table__).values(candidates)
    stmt = stmt.on_conflict_do_update(
        index_elements=["course_offering_id", "scheduled_date", "start_time"],
        index_where=ClassSession.__table__.c.deleted_at.is_(None),
        set_={
            "room_id": stmt.excluded.room_id,
            "end_time": stmt.excluded.end_time,
            "origin_exception_id": stmt.excluded.origin_exception_id,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    return len(candidates)


async def materialise_one(
    session: AsyncSession,
    *,
    offering_id: UUID,
    scheduled_date: date,
) -> ClassSession | None:
    """On-demand single-date materialiser. Used when teacher hits /qr for a
    session the cron hasn't created yet. Returns the materialised row, or
    None if no slot applies on that date."""
    await materialise_offering(
        session,
        offering_id=offering_id,
        from_date=scheduled_date,
        to_date=scheduled_date,
    )
    row = await session.execute(
        select(ClassSession).where(
            ClassSession.course_offering_id == offering_id,
            ClassSession.scheduled_date == scheduled_date,
            ClassSession.deleted_at.is_(None),
        )
    )
    return row.scalars().first()


async def materialise_window(
    session: AsyncSession,
    *,
    college_id: UUID,
    from_date: date,
    to_date: date,
) -> int:
    """Materialise every active offering in the college across the window.

    Driven by the CLI (`python -m app.cli materialise`). Returns total
    candidates upserted across all offerings."""
    offerings = (
        await session.execute(
            select(CourseOffering.id).where(
                CourseOffering.college_id == college_id,
                CourseOffering.deleted_at.is_(None),
                CourseOffering.is_active.is_(True),
            )
        )
    ).scalars().all()
    total = 0
    for off_id in offerings:
        total += await materialise_offering(
            session, offering_id=off_id, from_date=from_date, to_date=to_date
        )
    return total


# ── Class session ops ────────────────────────────────────────────────────────
async def _load_session_with_offering(
    session: AsyncSession, *, session_id: UUID, college_id: UUID
) -> tuple[ClassSession, CourseOffering] | None:
    row = await session.execute(
        select(ClassSession, CourseOffering).join(
            CourseOffering, ClassSession.course_offering_id == CourseOffering.id
        ).where(
            ClassSession.id == session_id,
            ClassSession.college_id == college_id,
            ClassSession.deleted_at.is_(None),
        )
    )
    pair = row.first()
    return (pair[0], pair[1]) if pair is not None else None


async def issue_qr_token(
    session: AsyncSession, *, actor: User, session_id: UUID
) -> tuple[str, QRToken, ClassSession]:
    """Mint a fresh QR token for a class session.

    Side effects:
    - flips state pending→open on first call (sets opened_at)
    - revokes prior unrevoked tokens for the session (only one live at a time)
    - inserts a new qr_tokens row (jti unique)

    Raises if the session is closed.
    """
    _require_teacher_or_admin(actor)
    pair = await _load_session_with_offering(
        session, session_id=session_id, college_id=actor.college_id
    )
    if pair is None:
        raise AttendanceError("not_found", "class session not found", 404)
    cs, offering = pair
    _ensure_owner(actor, offering)

    if cs.state == ClassSessionState.closed:
        raise AttendanceError("session_closed", "session is closed", 409)

    # Transition pending → open.
    if cs.state == ClassSessionState.pending:
        cs.state = ClassSessionState.open
        cs.opened_at = utcnow()

    # Revoke prior live tokens for this session — only one live at a time.
    await session.execute(
        QRToken.__table__.update()
        .where(
            QRToken.class_session_id == cs.id,
            QRToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )

    # Look up room centroid (may be NULL if room has no GPS or no room).
    centroid_lat: Decimal | None = None
    centroid_lon: Decimal | None = None
    if cs.room_id is not None:
        room = await session.get(Room, cs.room_id)
        if room is not None and room.lat is not None and room.lon is not None:
            centroid_lat = room.lat
            centroid_lon = room.lon

    jti = uuid4()
    token, valid_from, valid_until = sign_qr(
        jti=jti,
        session_id=cs.id,
        issued_by_user_id=actor.id,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
    )
    qr = QRToken(
        college_id=cs.college_id,
        class_session_id=cs.id,
        jti=jti,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        valid_from=valid_from,
        valid_until=valid_until,
        issued_by_user_id=actor.id,
        created_at=utcnow(),
    )
    session.add(qr)
    await write_audit(
        session,
        action="attendance.qr.issue",
        entity_type="class_session",
        entity_id=cs.id,
        actor_user_id=actor.id,
        college_id=cs.college_id,
        new_value={
            "jti": str(jti),
            "valid_until": valid_until.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(cs)
    await session.refresh(qr)
    return token, qr, cs


async def close_session(
    session: AsyncSession, *, actor: User, session_id: UUID
) -> ClassSession:
    _require_teacher_or_admin(actor)
    pair = await _load_session_with_offering(
        session, session_id=session_id, college_id=actor.college_id
    )
    if pair is None:
        raise AttendanceError("not_found", "class session not found", 404)
    cs, offering = pair
    _ensure_owner(actor, offering)

    if cs.state == ClassSessionState.closed:
        return cs
    cs.state = ClassSessionState.closed
    cs.closed_at = utcnow()
    # Revoke any live QR tokens — nobody else gets to submit.
    await session.execute(
        QRToken.__table__.update()
        .where(
            QRToken.class_session_id == cs.id,
            QRToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    await write_audit(
        session,
        action="class_session.close",
        entity_type="class_session",
        entity_id=cs.id,
        actor_user_id=actor.id,
        college_id=cs.college_id,
    )
    # TODO(events): publish session.closed.
    await session.commit()
    await session.refresh(cs)
    return cs


# ── Submit ───────────────────────────────────────────────────────────────────
async def submit_attendance(
    session: AsyncSession,
    *,
    actor: User,
    payload: AttendanceSubmit,
    ip: str | None,
    user_agent: str | None,
) -> AttendanceRecord:
    """Run the full 3-layer pipeline. Returns the resulting record.

    The record lands in state `recorded` if all three layers pass, or
    `flagged` if GPS is too far or face match fails. The submit itself
    always succeeds (HTTP 200) unless an invariant is violated (closed
    session, expired/replayed QR, duplicate device, missing enrollment).
    """
    _require_student(actor)

    # Layer 1a: JWT signature + type + exp.
    try:
        claims = verify_qr(payload.qr_token)
    except QRInvalidError as e:
        raise AttendanceError(e.code, e.message, 400) from e

    # Layer 1b: jti exists, not revoked, within window.
    qr = (
        await session.execute(
            select(QRToken).where(
                QRToken.jti == claims.jti,
                QRToken.college_id == actor.college_id,
            )
        )
    ).scalar_one_or_none()
    if qr is None:
        raise AttendanceError("qr_unknown", "QR token not recognised", 400)
    if qr.revoked_at is not None:
        raise AttendanceError("qr_revoked", "QR token has been revoked", 400)
    now = utcnow()
    if not (qr.valid_from <= now < qr.valid_until):
        raise AttendanceError("qr_expired", "QR token outside validity window", 400)

    # Session: must exist + open + tenant-scoped.
    pair = await _load_session_with_offering(
        session, session_id=qr.class_session_id, college_id=actor.college_id
    )
    if pair is None:
        raise AttendanceError("session_missing", "class session not found", 404)
    cs, offering = pair
    if cs.state != ClassSessionState.open:
        raise AttendanceError(
            "session_not_open", f"session is {cs.state.value}", 409
        )

    # Enrollment: student must be in the section for the offering's term.
    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.student_user_id == actor.id,
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term == offering.academic_term,
                Enrollment.withdrawn_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if enrolled is None:
        raise AttendanceError(
            "not_enrolled", "you are not enrolled in this section", 403
        )

    # Anti-replay #1: same student, same session, already has a record.
    dup_record = (
        await session.execute(
            select(AttendanceRecord.id).where(
                AttendanceRecord.class_session_id == cs.id,
                AttendanceRecord.student_user_id == actor.id,
            )
        )
    ).scalar_one_or_none()
    if dup_record is not None:
        raise AttendanceError(
            "already_submitted", "you have already submitted for this session", 409
        )

    # Anti-replay #2: same device fingerprint already used for this session.
    fp_hash = _sha256(payload.device_fingerprint)
    dup_device = (
        await session.execute(
            select(DeviceLog.id).where(
                DeviceLog.class_session_id == cs.id,
                DeviceLog.device_fingerprint_hash == fp_hash,
            )
        )
    ).scalar_one_or_none()
    if dup_device is not None:
        raise AttendanceError(
            "device_reused", "this device already submitted for this session", 409
        )

    # Device log row (created before the record so we have its id to FK).
    device_log = DeviceLog(
        college_id=cs.college_id,
        class_session_id=cs.id,
        submitted_by_user_id=actor.id,
        device_fingerprint_hash=fp_hash,
        ip=ip,
        user_agent=user_agent,
        created_at=now,
    )
    session.add(device_log)
    await session.flush()  # so device_log.id is available

    # Layer 2: GPS.
    gps_distance_m: int | None = None
    gps_too_far = False
    if qr.centroid_lat is not None and qr.centroid_lon is not None:
        distance = haversine_m(
            qr.centroid_lat, qr.centroid_lon, payload.gps_lat, payload.gps_lon
        )
        gps_distance_m = int(round(distance))
        threshold = 100  # default
        if cs.room_id is not None:
            room = await session.get(Room, cs.room_id)
            if room is not None and room.gps_radius_m:
                threshold = int(room.gps_radius_m)
        gps_too_far = gps_distance_m > threshold

    # Layer 3: Face stub.
    face_result = verify_face_stub(
        raw_frame_b64=payload.face_frame_b64,
        expected_user_id=str(actor.id),
    )
    face_failed = not face_result.match

    # Decide final state.
    flag_reasons: list[str] = []
    if gps_too_far:
        flag_reasons.append(f"gps_too_far:{gps_distance_m}m")
    if face_failed:
        flag_reasons.append(f"face_no_match:{face_result.confidence}")

    if flag_reasons:
        state = AttendanceRecordState.flagged
        verified_at = None
        recorded_at = None
        flagged_reason = ";".join(flag_reasons)[:200]
    else:
        state = AttendanceRecordState.recorded
        verified_at = now
        recorded_at = now
        flagged_reason = None

    record = AttendanceRecord(
        college_id=cs.college_id,
        class_session_id=cs.id,
        student_user_id=actor.id,
        state=state,
        submitted_at=now,
        verified_at=verified_at,
        recorded_at=recorded_at,
        flagged_reason=flagged_reason,
        gps_lat=payload.gps_lat,
        gps_lon=payload.gps_lon,
        gps_distance_m=gps_distance_m,
        face_match=face_result.match,
        face_confidence=face_result.confidence,
        qr_token_jti=qr.jti,
        device_log_id=device_log.id,
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        # Race: another submit slipped in between our duplicate check and flush.
        raise AttendanceError(
            "already_submitted",
            "this session/device already has a record",
            409,
        ) from e

    await write_audit(
        session,
        action="attendance.submit",
        entity_type="attendance_record",
        entity_id=record.id,
        actor_user_id=actor.id,
        college_id=cs.college_id,
        new_value={
            "state": state.value,
            "session_id": str(cs.id),
            "flagged_reason": flagged_reason,
            "gps_distance_m": gps_distance_m,
            "face_match": face_result.match,
        },
        ip=ip,
        user_agent=user_agent,
    )
    # TODO(events): publish attendance.marked; if flagged, also
    # attendance.anomaly_detected. Bus lands when M5/M9 need it.
    await session.commit()
    await session.refresh(record)
    return record


# ── Views ────────────────────────────────────────────────────────────────────
async def list_sessions(
    session: AsyncSession,
    *,
    actor: User,
    from_date: date | None,
    to_date: date | None,
    state: ClassSessionState | None,
) -> list[ClassSession]:
    """List class_sessions visible to the actor.

    - admin: all sessions in their college
    - teacher: sessions whose offering they own
    - student: sessions for offerings tied to sections they're enrolled in
      (for the term — the FE uses this to render "today's classes")
    """
    stmt = (
        select(ClassSession)
        .join(CourseOffering, ClassSession.course_offering_id == CourseOffering.id)
        .where(
            ClassSession.college_id == actor.college_id,
            ClassSession.deleted_at.is_(None),
        )
    )
    if actor.role == UserRole.teacher:
        stmt = stmt.where(CourseOffering.teacher_user_id == actor.id)
    elif actor.role == UserRole.student:
        stmt = stmt.join(
            Enrollment,
            and_(
                Enrollment.section_id == CourseOffering.section_id,
                Enrollment.academic_term == CourseOffering.academic_term,
                Enrollment.student_user_id == actor.id,
                Enrollment.withdrawn_at.is_(None),
            ),
        )
    if from_date is not None:
        stmt = stmt.where(ClassSession.scheduled_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(ClassSession.scheduled_date <= to_date)
    if state is not None:
        stmt = stmt.where(ClassSession.state == state)
    stmt = stmt.order_by(
        ClassSession.scheduled_date.asc(), ClassSession.start_time.asc()
    )
    return (await session.execute(stmt)).scalars().all()


async def get_student_attendance(
    session: AsyncSession,
    *,
    actor: User,
    student_id: UUID,
    from_date: date | None,
    to_date: date | None,
    course_offering_id: UUID | None,
) -> list[AttendanceRecord]:
    """Student can read their own log; teacher/admin can read anyone in their college."""
    if actor.role == UserRole.student and actor.id != student_id:
        raise AttendanceError("forbidden", "students may read only their own log", 403)
    if actor.role not in (UserRole.admin, UserRole.teacher, UserRole.student):
        raise AttendanceError("forbidden", "role not permitted", 403)

    stmt = (
        select(AttendanceRecord)
        .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
        .where(
            AttendanceRecord.student_user_id == student_id,
            AttendanceRecord.college_id == actor.college_id,
        )
    )
    if from_date is not None:
        stmt = stmt.where(ClassSession.scheduled_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(ClassSession.scheduled_date <= to_date)
    if course_offering_id is not None:
        stmt = stmt.where(ClassSession.course_offering_id == course_offering_id)
    stmt = stmt.order_by(ClassSession.scheduled_date.desc(), ClassSession.start_time.desc())
    return (await session.execute(stmt)).scalars().all()


async def get_session_feed(
    session: AsyncSession, *, actor: User, session_id: UUID
) -> SessionFeed:
    _require_teacher_or_admin(actor)
    pair = await _load_session_with_offering(
        session, session_id=session_id, college_id=actor.college_id
    )
    if pair is None:
        raise AttendanceError("not_found", "class session not found", 404)
    cs, offering = pair
    _ensure_owner(actor, offering)

    # Enrolled students for this section/term.
    students_rows = (
        await session.execute(
            select(User)
            .join(Enrollment, Enrollment.student_user_id == User.id)
            .where(
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term == offering.academic_term,
                Enrollment.withdrawn_at.is_(None),
                User.deleted_at.is_(None),
            )
            .order_by(User.name.asc())
        )
    ).scalars().all()

    # Existing records keyed by student_id.
    records = (
        await session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.class_session_id == cs.id,
            )
        )
    ).scalars().all()
    by_student: dict[UUID, AttendanceRecord] = {r.student_user_id: r for r in records}

    rows: list[SessionFeedRow] = []
    counts = {s.value: 0 for s in AttendanceRecordState}
    counts["absent"] = 0
    for s in students_rows:
        rec = by_student.get(s.id)
        if rec is None:
            counts["absent"] += 1
        else:
            counts[rec.state.value] += 1
        rows.append(
            SessionFeedRow(
                student_user_id=s.id,
                student_name=s.name,
                student_email=s.email,
                record=rec,  # type: ignore[arg-type]  pydantic from_attributes handles it
            )
        )

    return SessionFeed(session=cs, rows=rows, counts=counts)  # type: ignore[arg-type]


# ── Override ─────────────────────────────────────────────────────────────────
async def override_attendance(
    session: AsyncSession,
    *,
    actor: User,
    session_id: UUID,
    record_id: UUID | None,
    payload: OverrideRequest,
) -> AttendanceOverride:
    """Narrow override:

    - record_id present + state is flagged → can set to_state=recorded
    - record_id absent → must supply student_user_id + to_state=recorded; we
      create the record at state=recorded for that student (must be enrolled).

    Any other transition raises 400 — that's intentional. M9 will widen
    this once the audit-log UI ships.
    """
    _require_teacher_or_admin(actor)
    pair = await _load_session_with_offering(
        session, session_id=session_id, college_id=actor.college_id
    )
    if pair is None:
        raise AttendanceError("not_found", "class session not found", 404)
    cs, offering = pair
    _ensure_owner(actor, offering)

    if payload.to_state != AttendanceRecordState.recorded:
        raise AttendanceError(
            "bad_transition",
            "override can only set state to 'recorded' in this release",
            400,
        )

    now = utcnow()
    if record_id is not None:
        record = (
            await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.id == record_id,
                    AttendanceRecord.class_session_id == cs.id,
                    AttendanceRecord.college_id == actor.college_id,
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise AttendanceError("not_found", "attendance record not found", 404)
        if record.state != AttendanceRecordState.flagged:
            raise AttendanceError(
                "bad_transition",
                f"only flagged records can be overridden; got {record.state.value}",
                400,
            )
        from_state = record.state
        record.state = AttendanceRecordState.recorded
        record.recorded_at = now
        record.verified_at = record.verified_at or now
        student_user_id = record.student_user_id
        attendance_record_id: UUID | None = record.id
    else:
        if payload.student_user_id is None:
            raise AttendanceError(
                "bad_request",
                "student_user_id required when creating a record from absence",
                400,
            )
        # Student must be enrolled in this section/term, and not already have a record.
        enrolled = (
            await session.execute(
                select(Enrollment.id).where(
                    Enrollment.student_user_id == payload.student_user_id,
                    Enrollment.section_id == offering.section_id,
                    Enrollment.academic_term == offering.academic_term,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if enrolled is None:
            raise AttendanceError(
                "not_enrolled", "student not enrolled in this section", 400
            )
        existing = (
            await session.execute(
                select(AttendanceRecord.id).where(
                    AttendanceRecord.class_session_id == cs.id,
                    AttendanceRecord.student_user_id == payload.student_user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AttendanceError(
                "record_exists",
                "record already exists; pass record_id to override it",
                409,
            )
        record = AttendanceRecord(
            college_id=cs.college_id,
            class_session_id=cs.id,
            student_user_id=payload.student_user_id,
            state=AttendanceRecordState.recorded,
            submitted_at=now,
            verified_at=now,
            recorded_at=now,
            face_match=False,  # never went through verification
            face_confidence=Decimal("0"),
        )
        session.add(record)
        await session.flush()
        from_state = None
        student_user_id = payload.student_user_id
        attendance_record_id = record.id

    override = AttendanceOverride(
        college_id=cs.college_id,
        class_session_id=cs.id,
        attendance_record_id=attendance_record_id,
        student_user_id=student_user_id,
        from_state=from_state,
        to_state=AttendanceRecordState.recorded,
        reason=payload.reason,
        overridden_by_user_id=actor.id,
        created_at=now,
    )
    session.add(override)
    await write_audit(
        session,
        action="attendance.override",
        entity_type="attendance_record",
        entity_id=attendance_record_id,
        actor_user_id=actor.id,
        college_id=cs.college_id,
        old_value={"state": from_state.value if from_state else None},
        new_value={
            "state": AttendanceRecordState.recorded.value,
            "reason": payload.reason,
            "student_user_id": str(student_user_id),
        },
    )
    await session.commit()
    await session.refresh(override)
    return override


# ── Report ───────────────────────────────────────────────────────────────────
async def generate_report(
    session: AsyncSession,
    *,
    actor: User,
    batch_id: UUID,
    from_date: date | None,
    to_date: date | None,
) -> AttendanceReport:
    """Per-student × per-course-offering attendance percentages for a batch.

    Restricted to admin or a teacher who teaches at least one offering for
    that batch.
    """
    _require_teacher_or_admin(actor)
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.id == batch_id,
                Batch.college_id == actor.college_id,
                Batch.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise AttendanceError("not_found", "batch not found", 404)

    if actor.role == UserRole.teacher:
        # Teacher must teach at least one offering for this batch.
        teaches = (
            await session.execute(
                select(CourseOffering.id)
                .join(Section, Section.id == CourseOffering.section_id)
                .where(
                    Section.batch_id == batch_id,
                    CourseOffering.teacher_user_id == actor.id,
                    CourseOffering.deleted_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if teaches is None:
            raise AttendanceError(
                "forbidden",
                "you do not teach any offering for this batch",
                403,
            )

    # Aggregate: total sessions per offering, and per-student tallies.
    sess_q = (
        select(
            ClassSession.course_offering_id,
            func.count(ClassSession.id).label("total"),
        )
        .join(CourseOffering, CourseOffering.id == ClassSession.course_offering_id)
        .join(Section, Section.id == CourseOffering.section_id)
        .where(
            Section.batch_id == batch_id,
            ClassSession.deleted_at.is_(None),
            ClassSession.state == ClassSessionState.closed,
        )
        .group_by(ClassSession.course_offering_id)
    )
    if from_date is not None:
        sess_q = sess_q.where(ClassSession.scheduled_date >= from_date)
    if to_date is not None:
        sess_q = sess_q.where(ClassSession.scheduled_date <= to_date)
    sess_totals = {
        row.course_offering_id: row.total
        for row in (await session.execute(sess_q)).all()
    }

    rec_q = (
        select(
            ClassSession.course_offering_id,
            AttendanceRecord.student_user_id,
            AttendanceRecord.state,
            func.count(AttendanceRecord.id).label("n"),
        )
        .join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id)
        .join(CourseOffering, CourseOffering.id == ClassSession.course_offering_id)
        .join(Section, Section.id == CourseOffering.section_id)
        .where(
            Section.batch_id == batch_id,
            ClassSession.deleted_at.is_(None),
            ClassSession.state == ClassSessionState.closed,
        )
        .group_by(
            ClassSession.course_offering_id,
            AttendanceRecord.student_user_id,
            AttendanceRecord.state,
        )
    )
    if from_date is not None:
        rec_q = rec_q.where(ClassSession.scheduled_date >= from_date)
    if to_date is not None:
        rec_q = rec_q.where(ClassSession.scheduled_date <= to_date)

    # (offering_id, student_id) → {state: count}
    by_pair: dict[tuple[UUID, UUID], dict[str, int]] = {}
    for row in (await session.execute(rec_q)).all():
        key = (row.course_offering_id, row.student_user_id)
        by_pair.setdefault(key, {}).update({row.state.value: row.n})

    # Roster: enrollments × offerings for this batch.
    roster_q = (
        select(
            User.id.label("student_id"),
            User.name.label("student_name"),
            User.email.label("student_email"),
            Section.id.label("section_id"),
            Section.name.label("section_name"),
            CourseOffering.id.label("offering_id"),
            Course.code.label("course_code"),
            Course.title.label("course_title"),
        )
        .select_from(CourseOffering)
        .join(Section, Section.id == CourseOffering.section_id)
        .join(Course, Course.id == CourseOffering.course_id)
        .join(Enrollment, Enrollment.section_id == Section.id)
        .join(User, User.id == Enrollment.student_user_id)
        .where(
            Section.batch_id == batch_id,
            CourseOffering.deleted_at.is_(None),
            CourseOffering.academic_term == Enrollment.academic_term,
            Enrollment.withdrawn_at.is_(None),
            User.deleted_at.is_(None),
        )
        .order_by(Section.name.asc(), User.name.asc(), Course.code.asc())
    )
    if actor.role == UserRole.teacher:
        roster_q = roster_q.where(CourseOffering.teacher_user_id == actor.id)

    rows: list[AttendanceReportRow] = []
    for r in (await session.execute(roster_q)).all():
        offering_id = r.offering_id
        student_id = r.student_id
        total = sess_totals.get(offering_id, 0)
        states = by_pair.get((offering_id, student_id), {})
        recorded = states.get("recorded", 0)
        flagged = states.get("flagged", 0)
        absent = max(0, total - recorded - flagged)
        pct = (recorded / total * 100.0) if total > 0 else 0.0
        rows.append(
            AttendanceReportRow(
                student_user_id=student_id,
                student_name=r.student_name,
                student_email=r.student_email,
                section_id=r.section_id,
                section_name=r.section_name,
                course_offering_id=offering_id,
                course_code=r.course_code,
                course_title=r.course_title,
                total_sessions=int(total),
                recorded=int(recorded),
                flagged=int(flagged),
                absent=int(absent),
                percentage=round(pct, 2),
            )
        )

    return AttendanceReport(
        batch_id=batch_id,
        from_date=from_date,
        to_date=to_date,
        generated_at=utcnow(),
        rows=rows,
    )
