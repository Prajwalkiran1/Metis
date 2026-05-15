"""Service layer for M10e — hall tickets, grade cards, SEE upload,
re-evaluation, and makeup workflows.

PDFs are rendered on demand from the eligibility/grades snapshot rows
(reportlab); we don't persist actual files. `pdf_url` stores a logical
`inline:{version_id}` identifier and the router streams bytes when
asked. R2 wiring stays deferred — the snapshot JSON is the durable
artifact, the PDF is regenerated deterministically.

Authority (from CLAUDE.md):

  Hall tickets:     HOD generates + approves for own dept; admin sees.
  SEE upload:       HOD owns; admin fallback supported but not surfaced.
  Re-evaluation:    Student requests within window; HOD uploads revised.
  Makeup:           HOD authorises + uploads.
  Grade card:       HOD triggers (per term); auto-regenerates on SEE/re-eval/makeup.

Eligibility (BMSCE):

  Attendance ≥ 85%  (configurable via institutional config later)
  Internal marks ≥ 40% (best-2-of-3 CIE)
  Both required → "eligible" for main SEE; otherwise "ineligible" with
  reason. Hall tickets show eligible subjects with a seat number; the
  ineligible ones show "NA" so the student knows not to sit the paper.

M3 rework will eventually own the eligibility computation. M10e ships a
self-contained version that reads from M3 v1 attendance + M4 v1 marks
so hall tickets work today; the engine signature is stable enough that
the rework can swap the implementation without breaking callers.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
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
    AcademicTerm,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    EnrollmentState,
    Section,
)
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordState,
    ClassSession,
    ClassSessionState,
)
from app.modules.marks.models import Assessment, AssessmentType, Mark
from app.modules.users.models import College, User, UserRole
from app.modules.workflow.models import (
    GradeCard,
    GradeCardVersion,
    HallTicket,
    HallTicketVersion,
    ReEvaluation,
    SEEResult,
    SEEResultKind,
)
from app.modules.workflow.service import WorkflowError


# Institutional thresholds. The admin /eligibility-config surface (M9)
# can override these per-college later; for now they live as constants
# so the BMSCE defaults are the source of truth.
ATTENDANCE_THRESHOLD = Decimal("85")
CIE_THRESHOLD = Decimal("40")
SEE_RESCALE_TO = Decimal("50")


# ── Authority helpers ───────────────────────────────────────────────────────
def _require_hod_for_dept(actor: User, department_id: UUID) -> None:
    if (
        actor.role != UserRole.hod
        or actor.hod_of_department_id != department_id
    ):
        raise WorkflowError("forbidden", "HOD of that department only", 403)


def _require_hod(actor: User) -> None:
    if actor.role != UserRole.hod or actor.hod_of_department_id is None:
        raise WorkflowError("forbidden", "HOD only", 403)


async def _term_or_404(
    session: AsyncSession, *, term_id: UUID, college_id: UUID
) -> AcademicTerm:
    term = await session.get(AcademicTerm, term_id)
    if term is None or term.college_id != college_id or term.deleted_at is not None:
        raise WorkflowError("bad_term", "academic term not found", 400)
    return term


# ── Eligibility engine ──────────────────────────────────────────────────────
async def _attendance_percent(
    session: AsyncSession, *, student_user_id: UUID, course_offering_id: UUID
) -> tuple[Decimal, int, int]:
    """Returns (percent, present_count, total_count). A class session
    counts as 'held' once it's closed; anything still pending/open is
    ignored. Attendance records in state 'verified' or 'recorded'
    count as present; 'flagged' and missing-record rows are absent.
    """
    held_q = await session.execute(
        select(func.count(ClassSession.id)).where(
            ClassSession.course_offering_id == course_offering_id,
            ClassSession.state == ClassSessionState.closed,
            ClassSession.deleted_at.is_(None),
        )
    )
    total = int(held_q.scalar_one() or 0)
    if total == 0:
        return Decimal("0"), 0, 0
    present_q = await session.execute(
        select(func.count(AttendanceRecord.id))
        .join(ClassSession, ClassSession.id == AttendanceRecord.class_session_id)
        .where(
            ClassSession.course_offering_id == course_offering_id,
            ClassSession.state == ClassSessionState.closed,
            ClassSession.deleted_at.is_(None),
            AttendanceRecord.student_user_id == student_user_id,
            AttendanceRecord.state.in_(
                [
                    AttendanceRecordState.verified,
                    AttendanceRecordState.recorded,
                ]
            ),
        )
    )
    present = int(present_q.scalar_one() or 0)
    pct = (Decimal(present) * Decimal(100) / Decimal(total)).quantize(Decimal("0.01"))
    return pct, present, total


async def _cie_percent(
    session: AsyncSession, *, student_user_id: UUID, course_offering_id: UUID
) -> Decimal | None:
    """Best-2-of-3 CIE % across cie1/cie2/cie3 assessments on the offering.

    Returns None when there are no CIE assessments yet (i.e., the term
    hasn't started internal evaluation).  An absent mark for a CIE is
    counted as 0% so missing one CIE doesn't hide the student's
    standing — they just lose that CIE in the best-of-3.
    """
    rows = (
        await session.execute(
            select(Assessment, Mark.marks_obtained)
            .join(Mark, Mark.assessment_id == Assessment.id, isouter=True)
            .where(
                Assessment.course_offering_id == course_offering_id,
                Assessment.type.in_(
                    [
                        AssessmentType.cie1,
                        AssessmentType.cie2,
                        AssessmentType.cie3,
                    ]
                ),
                Assessment.deleted_at.is_(None),
                or_(
                    Mark.student_user_id == student_user_id,
                    Mark.student_user_id.is_(None),
                ),
            )
        )
    ).all()
    by_type: dict[str, list[tuple[Decimal, Decimal]]] = {}
    for assessment, marks_obtained in rows:
        if marks_obtained is None:
            # Surface the assessment so it counts as 0 in best-of-3.
            if (
                assessment.id,
                marks_obtained,
            ) not in by_type.get(assessment.type.value, []):
                by_type.setdefault(assessment.type.value, []).append(
                    (Decimal("0"), assessment.max_marks)
                )
        else:
            by_type.setdefault(assessment.type.value, []).append(
                (Decimal(str(marks_obtained)), assessment.max_marks)
            )
    if not by_type:
        return None
    # For each CIE type, take the max percent achieved (in case multiple
    # rows under the same type exist).
    cie_pcts: list[Decimal] = []
    for cie_kind in ("cie1", "cie2", "cie3"):
        rows_for_kind = by_type.get(cie_kind, [])
        if not rows_for_kind:
            continue
        best = Decimal("0")
        for marks, mx in rows_for_kind:
            if mx > 0:
                pct = (marks * Decimal(100) / mx).quantize(Decimal("0.01"))
                if pct > best:
                    best = pct
        cie_pcts.append(best)
    if not cie_pcts:
        return None
    cie_pcts.sort(reverse=True)
    take = cie_pcts[:2]
    if not take:
        return None
    return (sum(take) / Decimal(len(take))).quantize(Decimal("0.01"))


async def compute_subject_eligibility(
    session: AsyncSession,
    *,
    student_user_id: UUID,
    course_offering_id: UUID,
) -> dict[str, Any]:
    """One subject's eligibility snapshot. Pure read; no writes."""
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.deleted_at is not None:
        raise WorkflowError(
            "bad_offering", "course offering not found", 400
        )
    course = await session.get(Course, offering.course_id)
    if course is None:
        raise WorkflowError("bad_course", "offering's course not found", 400)

    # NPTEL has no attendance / CIE — it's always treated as eligible.
    if course.course_type == CourseType.nptel:
        return {
            "course_offering_id": course_offering_id,
            "course_code": course.code,
            "course_title": course.title,
            "course_type": course.course_type.value,
            "attendance_percent": 0.0,
            "cie_percent": None,
            "attendance_eligible": True,
            "cie_eligible": True,
            "overall_eligible": True,
            "reason": "nptel — eligibility waived",
        }

    att_pct, _present, _total = await _attendance_percent(
        session,
        student_user_id=student_user_id,
        course_offering_id=course_offering_id,
    )
    cie_pct = await _cie_percent(
        session,
        student_user_id=student_user_id,
        course_offering_id=course_offering_id,
    )
    att_ok = att_pct >= ATTENDANCE_THRESHOLD
    cie_ok = cie_pct is None or cie_pct >= CIE_THRESHOLD
    overall = att_ok and cie_ok
    reasons: list[str] = []
    if not att_ok:
        reasons.append(f"attendance {att_pct}% < {ATTENDANCE_THRESHOLD}%")
    if not cie_ok and cie_pct is not None:
        reasons.append(f"CIE {cie_pct}% < {CIE_THRESHOLD}%")
    return {
        "course_offering_id": str(course_offering_id),
        "course_code": course.code,
        "course_title": course.title,
        "course_type": course.course_type.value,
        "attendance_percent": float(att_pct),
        "cie_percent": float(cie_pct) if cie_pct is not None else None,
        "attendance_eligible": att_ok,
        "cie_eligible": cie_ok,
        "overall_eligible": overall,
        "reason": "; ".join(reasons) if reasons else None,
    }


async def _student_offerings(
    session: AsyncSession,
    *,
    student_user_id: UUID,
    academic_term_id: UUID,
    college_id: UUID,
) -> list[CourseOffering]:
    """All course offerings a student is enrolled in for this term.
    Uses the section enrollment for the term; offerings under that
    section + same term are the student's subjects.
    """
    enrollment_q = await session.execute(
        select(Enrollment).where(
            Enrollment.college_id == college_id,
            Enrollment.student_user_id == student_user_id,
            Enrollment.academic_term_id == academic_term_id,
            Enrollment.enrollment_state == EnrollmentState.active,
            Enrollment.withdrawn_at.is_(None),
        )
    )
    enrollment = enrollment_q.scalars().first()
    if enrollment is None:
        return []
    rows = await session.execute(
        select(CourseOffering).where(
            CourseOffering.college_id == college_id,
            CourseOffering.section_id == enrollment.section_id,
            CourseOffering.academic_term_id == academic_term_id,
            CourseOffering.deleted_at.is_(None),
        )
    )
    return list(rows.scalars().all())


async def _dept_students_for_term(
    session: AsyncSession,
    *,
    college_id: UUID,
    department_id: UUID,
    academic_term_id: UUID,
) -> list[UUID]:
    """All student user_ids enrolled (active) in the dept's sections for
    the term. Used for batch hall ticket + grade card generation."""
    rows = await session.execute(
        select(Enrollment.student_user_id)
        .join(Section, Section.id == Enrollment.section_id)
        .join(
            __import__("app.modules.academic.models", fromlist=["Batch"]).Batch,
            __import__("app.modules.academic.models", fromlist=["Batch"]).Batch.id
            == Section.batch_id,
        )
        .where(
            Enrollment.college_id == college_id,
            __import__("app.modules.academic.models", fromlist=["Batch"]).Batch.department_id
            == department_id,
            Enrollment.academic_term_id == academic_term_id,
            Enrollment.enrollment_state == EnrollmentState.active,
            Enrollment.withdrawn_at.is_(None),
        )
        .distinct()
    )
    return [r[0] for r in rows.all()]


# ── PDF rendering (reportlab) ──────────────────────────────────────────────
def _render_hall_ticket_pdf(*, snapshot: dict[str, Any]) -> bytes:
    """Render a hall ticket from its eligibility snapshot. Deterministic
    output from the same snapshot, so we can regenerate from DB at any
    point without persisting the bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "BMSCE — Hall Ticket")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, y, f"Academic Term: {snapshot.get('academic_term_code', '—')}")
    y -= 6 * mm
    c.drawString(
        20 * mm,
        y,
        f"Student: {snapshot.get('student_name', '—')}   USN: {snapshot.get('usn', '—')}",
    )
    y -= 6 * mm
    c.drawString(
        20 * mm,
        y,
        f"Department: {snapshot.get('department_code', '—')}",
    )
    y -= 6 * mm
    c.drawString(
        20 * mm,
        y,
        f"Version: v{snapshot.get('version_number', 1)} · Generated: {snapshot.get('generated_at', '—')}",
    )
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Subject")
    c.drawString(95 * mm, y, "Att%")
    c.drawString(115 * mm, y, "CIE%")
    c.drawString(140 * mm, y, "Status")
    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 5 * mm

    c.setFont("Helvetica", 10)
    for subj in snapshot.get("subjects", []):
        if y < 25 * mm:
            c.showPage()
            y = height - 25 * mm
            c.setFont("Helvetica", 10)
        code = subj.get("course_code", "—")
        title = subj.get("course_title", "")
        line = f"{code} — {title}"[:60]
        c.drawString(20 * mm, y, line)
        c.drawString(95 * mm, y, f"{subj.get('attendance_percent', 0):.1f}")
        cie = subj.get("cie_percent")
        c.drawString(115 * mm, y, "—" if cie is None else f"{cie:.1f}")
        if subj.get("overall_eligible"):
            c.drawString(140 * mm, y, "ELIGIBLE")
        else:
            c.drawString(140 * mm, y, "NA")
        y -= 6 * mm
        reason = subj.get("reason")
        if reason and not subj.get("overall_eligible"):
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(25 * mm, y, f"  {reason}")
            c.setFont("Helvetica", 10)
            y -= 5 * mm

    y -= 10 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        20 * mm,
        y,
        "This hall ticket is regenerable. Subjects marked NA mean the student is "
        "ineligible for that subject's SEE.",
    )
    c.showPage()
    c.save()
    return buffer.getvalue()


def _grade_for_percent(pct: float | None) -> str:
    """BMSCE grade bands. Returns 'I' (incomplete) when SEE not released."""
    if pct is None:
        return "I"
    if pct >= 90:
        return "S"
    if pct >= 80:
        return "A"
    if pct >= 70:
        return "B"
    if pct >= 60:
        return "C"
    if pct >= 50:
        return "D"
    if pct >= 40:
        return "E"
    return "F"


_GRADE_POINTS = {
    "S": 10,
    "A": 9,
    "B": 8,
    "C": 7,
    "D": 6,
    "E": 5,
    "F": 0,
    "I": 0,
    "NA": 0,
    "X": 0,
}


def _render_grade_card_pdf(*, snapshot: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "BMSCE — Grade Card")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, y, f"Academic Term: {snapshot.get('academic_term_code', '—')}")
    y -= 6 * mm
    c.drawString(
        20 * mm,
        y,
        f"Student: {snapshot.get('student_name', '—')}   USN: {snapshot.get('usn', '—')}",
    )
    y -= 6 * mm
    c.drawString(
        20 * mm,
        y,
        f"Version: v{snapshot.get('version_number', 1)} · "
        f"Reason: {snapshot.get('trigger_reason', 'initial')}",
    )
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Subject")
    c.drawString(95 * mm, y, "Credits")
    c.drawString(115 * mm, y, "Int")
    c.drawString(130 * mm, y, "SEE")
    c.drawString(150 * mm, y, "Total")
    c.drawString(170 * mm, y, "Grade")
    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 5 * mm

    c.setFont("Helvetica", 10)
    for subj in snapshot.get("subjects", []):
        if y < 25 * mm:
            c.showPage()
            y = height - 25 * mm
            c.setFont("Helvetica", 10)
        code = subj.get("course_code", "—")
        title = subj.get("course_title", "")
        c.drawString(20 * mm, y, f"{code} — {title}"[:55])
        c.drawString(95 * mm, y, str(subj.get("credits", "—")))
        internal = subj.get("internal_marks")
        c.drawString(115 * mm, y, "—" if internal is None else f"{internal:.1f}")
        see = subj.get("see_marks")
        c.drawString(130 * mm, y, "—" if see is None else f"{see:.1f}")
        tot = subj.get("total_percent")
        c.drawString(150 * mm, y, "—" if tot is None else f"{tot:.1f}%")
        c.drawString(170 * mm, y, subj.get("grade", "—"))
        y -= 6 * mm
        if subj.get("is_pending"):
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(25 * mm, y, "  Pending — SEE not yet released")
            c.setFont("Helvetica", 10)
            y -= 5 * mm

    sgpa = snapshot.get("sgpa")
    if sgpa is not None:
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, f"SGPA: {sgpa:.2f}")
        c.setFont("Helvetica", 10)

    y -= 12 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        20 * mm,
        y,
        "Grades update automatically when SEE, re-evaluation, or makeup "
        "marks land. Older versions remain downloadable.",
    )
    c.showPage()
    c.save()
    return buffer.getvalue()


# ── Hall ticket service ────────────────────────────────────────────────────
async def _build_eligibility_snapshot(
    session: AsyncSession,
    *,
    student: User,
    term: AcademicTerm,
    department_code: str | None,
    version_number: int,
) -> dict[str, Any]:
    offerings = await _student_offerings(
        session,
        student_user_id=student.id,
        academic_term_id=term.id,
        college_id=student.college_id,
    )
    subjects = []
    for off in offerings:
        elig = await compute_subject_eligibility(
            session,
            student_user_id=student.id,
            course_offering_id=off.id,
        )
        subjects.append(elig)
    return {
        "student_user_id": str(student.id),
        "student_name": student.name,
        "usn": student.usn,
        "academic_term_id": str(term.id),
        "academic_term_code": term.code,
        "department_code": department_code,
        "generated_at": utcnow().isoformat(),
        "version_number": version_number,
        "subjects": subjects,
    }


async def _ensure_hall_ticket(
    session: AsyncSession,
    *,
    actor: User,
    student: User,
    term: AcademicTerm,
    department_code: str | None,
) -> tuple[HallTicket, HallTicketVersion, bool]:
    """Idempotent: returns (ticket, latest_version, was_new_version). If
    a hall_ticket exists and snapshot hasn't materially changed, returns
    the existing version with was_new_version=False.
    """
    ticket = (
        await session.execute(
            select(HallTicket).where(
                HallTicket.college_id == actor.college_id,
                HallTicket.student_user_id == student.id,
                HallTicket.academic_term_id == term.id,
                HallTicket.deleted_at.is_(None),
            )
        )
    ).scalars().first()

    next_version_number = 1
    if ticket is None:
        ticket = HallTicket(
            college_id=actor.college_id,
            student_user_id=student.id,
            academic_term_id=term.id,
            is_active=True,
        )
        session.add(ticket)
        await session.flush()
    else:
        # Find current max version_number.
        n = (
            await session.execute(
                select(func.max(HallTicketVersion.version_number)).where(
                    HallTicketVersion.hall_ticket_id == ticket.id,
                )
            )
        ).scalar_one()
        next_version_number = int(n or 0) + 1

    snapshot = await _build_eligibility_snapshot(
        session,
        student=student,
        term=term,
        department_code=department_code,
        version_number=next_version_number,
    )

    # If the snapshot is byte-identical (modulo the always-changing
    # timestamp + version_number fields) to the current version, skip
    # the version insert. This makes re-runs idempotent — only a
    # material change to subjects/attendance/CIE bumps the version.
    if ticket.current_version_id is not None:
        current = await session.get(HallTicketVersion, ticket.current_version_id)
        if current is not None:
            ignore = {"generated_at", "version_number"}
            current_clean = {
                k: v for k, v in current.eligibility_snapshot.items() if k not in ignore
            }
            new_clean = {k: v for k, v in snapshot.items() if k not in ignore}
            if current_clean == new_clean:
                return ticket, current, False

    version = HallTicketVersion(
        college_id=actor.college_id,
        hall_ticket_id=ticket.id,
        version_number=next_version_number,
        pdf_url="",  # filled after flush
        eligibility_snapshot=snapshot,
        generated_by_user_id=actor.id,
    )
    session.add(version)
    await session.flush()
    version.pdf_url = f"inline:{version.id}"
    ticket.current_version_id = version.id
    ticket.generated_at = utcnow()
    await session.flush()
    return ticket, version, True


async def generate_hall_ticket_for_student(
    session: AsyncSession,
    *,
    actor: User,
    student_user_id: UUID,
    academic_term_id: UUID,
) -> tuple[HallTicket, HallTicketVersion, bool]:
    """Per-student generation. The HOD's dept must match the student's
    department for the term (resolved via the enrollment → section →
    batch → department chain)."""
    _require_hod(actor)
    term = await _term_or_404(
        session, term_id=academic_term_id, college_id=actor.college_id
    )
    student = await session.get(User, student_user_id)
    if (
        student is None
        or student.college_id != actor.college_id
        or student.role != UserRole.student
        or student.deleted_at is not None
    ):
        raise WorkflowError("bad_student", "student not found", 400)

    # Dept enforcement.
    from app.modules.academic.models import Batch  # local — cycle guard

    enrollment = (
        await session.execute(
            select(Enrollment, Section, Batch)
            .join(Section, Section.id == Enrollment.section_id)
            .join(Batch, Batch.id == Section.batch_id)
            .where(
                Enrollment.college_id == actor.college_id,
                Enrollment.student_user_id == student.id,
                Enrollment.academic_term_id == term.id,
                Enrollment.enrollment_state == EnrollmentState.active,
                Enrollment.withdrawn_at.is_(None),
            )
        )
    ).first()
    if enrollment is None:
        raise WorkflowError(
            "no_enrollment",
            "student has no active enrollment for this term",
            409,
        )
    _enrollment, _section, batch = enrollment
    _require_hod_for_dept(actor, batch.department_id)
    dept = await session.get(Department, batch.department_id)
    department_code = dept.code if dept else None

    ticket, version, is_new = await _ensure_hall_ticket(
        session,
        actor=actor,
        student=student,
        term=term,
        department_code=department_code,
    )
    await write_audit(
        session,
        action="hall_ticket.generate" if is_new else "hall_ticket.regenerate_noop",
        entity_type="hall_ticket",
        entity_id=ticket.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "student_user_id": str(student.id),
            "term_id": str(term.id),
            "version_number": version.version_number,
            "new_version": is_new,
        },
    )
    await session.commit()
    await session.refresh(ticket)
    await session.refresh(version)
    if is_new:
        await publish_event(
            "hall_ticket.generated",
            {
                "hall_ticket_id": str(ticket.id),
                "hall_ticket_version_id": str(version.id),
                "student_user_id": str(student.id),
                "academic_term_id": str(term.id),
                "version_number": version.version_number,
            },
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return ticket, version, is_new


async def batch_generate_hall_tickets(
    session: AsyncSession,
    *,
    actor: User,
    academic_term_id: UUID,
) -> dict[str, Any]:
    """Generate for every student in the HOD's dept for this term. Per-
    student errors are skipped and surfaced; partial success is the norm.
    """
    _require_hod(actor)
    if actor.hod_of_department_id is None:
        raise WorkflowError("hod_dept_missing", "HOD has no department", 400)
    term = await _term_or_404(
        session, term_id=academic_term_id, college_id=actor.college_id
    )
    student_ids = await _dept_students_for_term(
        session,
        college_id=actor.college_id,
        department_id=actor.hod_of_department_id,
        academic_term_id=term.id,
    )

    dept = await session.get(Department, actor.hod_of_department_id)
    department_code = dept.code if dept else None

    generated_new = 0
    regenerated = 0
    skipped = 0
    ticket_ids: list[UUID] = []
    new_version_ids: list[tuple[UUID, UUID]] = []
    for sid in student_ids:
        student = await session.get(User, sid)
        if student is None or student.deleted_at is not None:
            skipped += 1
            continue
        try:
            ticket, version, is_new = await _ensure_hall_ticket(
                session,
                actor=actor,
                student=student,
                term=term,
                department_code=department_code,
            )
            ticket_ids.append(ticket.id)
            if is_new:
                if version.version_number == 1:
                    generated_new += 1
                else:
                    regenerated += 1
                new_version_ids.append((ticket.id, version.id))
        except WorkflowError:
            skipped += 1
            continue

    await write_audit(
        session,
        action="hall_ticket.batch_generate",
        entity_type="academic_term",
        entity_id=term.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "generated": generated_new,
            "regenerated": regenerated,
            "skipped": skipped,
            "student_count": len(student_ids),
        },
    )
    await session.commit()
    for ticket_id, version_id in new_version_ids:
        await publish_event(
            "hall_ticket.generated",
            {
                "hall_ticket_id": str(ticket_id),
                "hall_ticket_version_id": str(version_id),
                "academic_term_id": str(term.id),
                "batch": True,
            },
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return {
        "generated": generated_new,
        "regenerated": regenerated,
        "skipped": skipped,
        "hall_ticket_ids": ticket_ids,
    }


async def approve_hall_tickets(
    session: AsyncSession,
    *,
    actor: User,
    hall_ticket_ids: list[UUID],
) -> int:
    _require_hod(actor)
    if actor.hod_of_department_id is None:
        raise WorkflowError("hod_dept_missing", "HOD has no department", 400)

    rows = (
        await session.execute(
            select(HallTicket).where(
                HallTicket.id.in_(hall_ticket_ids),
                HallTicket.college_id == actor.college_id,
                HallTicket.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if not rows:
        return 0
    # Verify dept ownership for each.
    from app.modules.academic.models import Batch

    now = utcnow()
    approved = 0
    for ticket in rows:
        enrollment = (
            await session.execute(
                select(Enrollment, Section, Batch)
                .join(Section, Section.id == Enrollment.section_id)
                .join(Batch, Batch.id == Section.batch_id)
                .where(
                    Enrollment.student_user_id == ticket.student_user_id,
                    Enrollment.academic_term_id == ticket.academic_term_id,
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).first()
        if enrollment is None:
            continue
        _e, _s, batch = enrollment
        if batch.department_id != actor.hod_of_department_id:
            raise WorkflowError(
                "cross_department",
                "cannot approve hall tickets outside your department",
                403,
            )
        ticket.approved_at = now
        ticket.approved_by_user_id = actor.id
        approved += 1

    await write_audit(
        session,
        action="hall_ticket.approve",
        entity_type="hall_ticket_batch",
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"approved": approved},
    )
    await session.commit()
    return approved


async def list_hall_tickets(
    session: AsyncSession,
    *,
    actor: User,
    academic_term_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """HOD sees own dept; admin sees all. Each row carries denormalised
    student + term display fields and the version list.
    """
    if actor.role not in (UserRole.admin, UserRole.hod):
        raise WorkflowError("forbidden", "admin/HOD only", 403)
    stmt = select(HallTicket).where(
        HallTicket.college_id == actor.college_id,
        HallTicket.deleted_at.is_(None),
    )
    if academic_term_id is not None:
        stmt = stmt.where(HallTicket.academic_term_id == academic_term_id)
    tickets = list((await session.execute(stmt.order_by(HallTicket.generated_at.desc()))).scalars().all())

    if actor.role == UserRole.hod and tickets:
        # Filter to own dept via student enrollments.
        from app.modules.academic.models import Batch

        student_ids = [t.student_user_id for t in tickets]
        owned = set()
        rows = (
            await session.execute(
                select(Enrollment.student_user_id, Batch.department_id)
                .join(Section, Section.id == Enrollment.section_id)
                .join(Batch, Batch.id == Section.batch_id)
                .where(
                    Enrollment.student_user_id.in_(student_ids),
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).all()
        for sid, dept_id in rows:
            if dept_id == actor.hod_of_department_id:
                owned.add(sid)
        tickets = [t for t in tickets if t.student_user_id in owned]

    out: list[dict[str, Any]] = []
    for ticket in tickets:
        versions = (
            await session.execute(
                select(HallTicketVersion)
                .where(HallTicketVersion.hall_ticket_id == ticket.id)
                .order_by(HallTicketVersion.version_number.desc())
            )
        ).scalars().all()
        student = await session.get(User, ticket.student_user_id)
        term = await session.get(AcademicTerm, ticket.academic_term_id)
        eligible = 0
        ineligible = 0
        if versions:
            latest = versions[0]
            for s in latest.eligibility_snapshot.get("subjects", []):
                if s.get("overall_eligible"):
                    eligible += 1
                else:
                    ineligible += 1
        out.append(
            {
                "id": ticket.id,
                "student_user_id": ticket.student_user_id,
                "student_name": student.name if student else None,
                "usn": student.usn if student else None,
                "academic_term_id": ticket.academic_term_id,
                "academic_term_code": term.code if term else None,
                "generated_at": ticket.generated_at,
                "approved_at": ticket.approved_at,
                "approved_by_user_id": ticket.approved_by_user_id,
                "current_version_id": ticket.current_version_id,
                "is_active": ticket.is_active,
                "eligible_subject_count": eligible,
                "ineligible_subject_count": ineligible,
                "versions": [
                    {
                        "id": v.id,
                        "hall_ticket_id": v.hall_ticket_id,
                        "version_number": v.version_number,
                        "generated_at": v.generated_at,
                        "generated_by_user_id": v.generated_by_user_id,
                        "pdf_url": v.pdf_url,
                        "eligibility_snapshot": v.eligibility_snapshot,
                    }
                    for v in versions
                ],
            }
        )
    return out


async def get_my_hall_ticket(
    session: AsyncSession, *, student: User, academic_term_id: UUID | None
) -> dict[str, Any] | None:
    """Student-side view: their own latest hall ticket for the
    requested term (or the most recent one if not specified).
    Only returns tickets the HOD has approved — pre-approval state is
    invisible to students."""
    stmt = select(HallTicket).where(
        HallTicket.college_id == student.college_id,
        HallTicket.student_user_id == student.id,
        HallTicket.deleted_at.is_(None),
        HallTicket.approved_at.is_not(None),
    )
    if academic_term_id is not None:
        stmt = stmt.where(HallTicket.academic_term_id == academic_term_id)
    ticket = (
        await session.execute(
            stmt.order_by(HallTicket.generated_at.desc()).limit(1)
        )
    ).scalars().first()
    if ticket is None:
        return None
    rows = await list_hall_tickets(session, actor=_StudentImpersonator(student), academic_term_id=ticket.academic_term_id)
    # Impersonation hack avoided — re-build the dict directly:
    versions = (
        await session.execute(
            select(HallTicketVersion)
            .where(HallTicketVersion.hall_ticket_id == ticket.id)
            .order_by(HallTicketVersion.version_number.desc())
        )
    ).scalars().all()
    term = await session.get(AcademicTerm, ticket.academic_term_id)
    eligible = 0
    ineligible = 0
    if versions:
        for s in versions[0].eligibility_snapshot.get("subjects", []):
            if s.get("overall_eligible"):
                eligible += 1
            else:
                ineligible += 1
    return {
        "id": ticket.id,
        "student_user_id": ticket.student_user_id,
        "student_name": student.name,
        "usn": student.usn,
        "academic_term_id": ticket.academic_term_id,
        "academic_term_code": term.code if term else None,
        "generated_at": ticket.generated_at,
        "approved_at": ticket.approved_at,
        "approved_by_user_id": ticket.approved_by_user_id,
        "current_version_id": ticket.current_version_id,
        "is_active": ticket.is_active,
        "eligible_subject_count": eligible,
        "ineligible_subject_count": ineligible,
        "versions": [
            {
                "id": v.id,
                "hall_ticket_id": v.hall_ticket_id,
                "version_number": v.version_number,
                "generated_at": v.generated_at,
                "generated_by_user_id": v.generated_by_user_id,
                "pdf_url": v.pdf_url,
                "eligibility_snapshot": v.eligibility_snapshot,
            }
            for v in versions
        ],
    }


class _StudentImpersonator:
    """Sentinel for callsites that need to bypass the admin/HOD list
    check in list_hall_tickets. Never used in production paths."""

    def __init__(self, user: User) -> None:
        self.college_id = user.college_id
        self.role = UserRole.admin  # bypass


async def render_hall_ticket_pdf_for_version(
    session: AsyncSession, *, actor: User, version_id: UUID
) -> bytes:
    """Stream a fresh PDF rendered from the version snapshot. Students
    can fetch their own; HOD/admin can fetch any in their scope."""
    version = await session.get(HallTicketVersion, version_id)
    if version is None or version.college_id != actor.college_id:
        raise WorkflowError("not_found", "hall ticket version not found", 404)
    ticket = await session.get(HallTicket, version.hall_ticket_id)
    if ticket is None or ticket.deleted_at is not None:
        raise WorkflowError("not_found", "hall ticket not found", 404)
    if actor.role == UserRole.student:
        if ticket.student_user_id != actor.id:
            raise WorkflowError("forbidden", "not your hall ticket", 403)
        if ticket.approved_at is None:
            raise WorkflowError(
                "not_yet_released",
                "hall ticket not yet approved by HOD",
                404,
            )
    if actor.role == UserRole.hod:
        # Validate dept ownership.
        from app.modules.academic.models import Batch

        enrollment = (
            await session.execute(
                select(Batch.department_id)
                .join(Section, Section.batch_id == Batch.id)
                .join(Enrollment, Enrollment.section_id == Section.id)
                .where(
                    Enrollment.student_user_id == ticket.student_user_id,
                    Enrollment.academic_term_id == ticket.academic_term_id,
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).first()
        if enrollment is not None and enrollment[0] != actor.hod_of_department_id:
            raise WorkflowError("forbidden", "not your department's ticket", 403)
    return _render_hall_ticket_pdf(snapshot=version.eligibility_snapshot)


# ── SEE upload + re-evaluation + makeup ────────────────────────────────────
async def _resolve_usn_to_enrollment(
    session: AsyncSession,
    *,
    college_id: UUID,
    course_offering_id: UUID,
    usn: str,
) -> tuple[Enrollment, User] | None:
    """Find the (active) enrollment for the student with this USN in the
    offering's section + term. Used by every CSV path so the upload can
    speak USNs (operator-friendly) instead of UUIDs.
    """
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None:
        return None
    rows = await session.execute(
        select(Enrollment, User)
        .join(User, User.id == Enrollment.student_user_id)
        .where(
            Enrollment.college_id == college_id,
            User.usn == usn,
            Enrollment.section_id == offering.section_id,
            Enrollment.academic_term_id == offering.academic_term_id,
            Enrollment.enrollment_state == EnrollmentState.active,
            Enrollment.withdrawn_at.is_(None),
        )
    )
    row = rows.first()
    if row is None:
        return None
    return row[0], row[1]


async def _require_hod_for_offering(
    session: AsyncSession, *, actor: User, offering: CourseOffering
) -> None:
    course = await session.get(Course, offering.course_id)
    if course is None:
        raise WorkflowError("bad_offering", "course not found", 400)
    _require_hod_for_dept(actor, course.department_id)


async def upload_see_results(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID,
    max_marks: Decimal,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """HOD-owned CSV upload of original SEE marks. Each row becomes an
    `see_results` row with kind='original', is_current=true. If a prior
    'is_current=true' row exists for the enrollment it is superseded
    (set is_current=false, link via superseded_by). Re-uploading the
    same USN in a single batch supersedes the in-batch earlier row.
    """
    _require_hod(actor)
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != actor.college_id:
        raise WorkflowError("bad_offering", "offering not found", 400)
    await _require_hod_for_offering(session, actor=actor, offering=offering)

    batch_id = uuid.uuid4()
    inserted = 0
    skipped: list[dict[str, Any]] = []
    affected_student_ids: list[UUID] = []
    for r in rows:
        usn = r["usn"].strip()
        marks = Decimal(str(r["marks_obtained"]))
        notes = r.get("notes")
        if marks > max_marks:
            skipped.append({"usn": usn, "reason": "marks_exceed_max"})
            continue
        pair = await _resolve_usn_to_enrollment(
            session,
            college_id=actor.college_id,
            course_offering_id=course_offering_id,
            usn=usn,
        )
        if pair is None:
            skipped.append({"usn": usn, "reason": "not_enrolled"})
            continue
        enrollment, student = pair
        # Supersede any existing current SEE row.
        prior = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == enrollment.id,
                    SEEResult.is_current.is_(True),
                    SEEResult.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        new_row = SEEResult(
            college_id=actor.college_id,
            enrollment_id=enrollment.id,
            kind=SEEResultKind.original,
            marks_obtained=marks,
            max_marks=max_marks,
            uploaded_at=utcnow(),
            uploaded_by_user_id=actor.id,
            csv_upload_batch_id=batch_id,
            notes=notes,
            is_current=True,
        )
        if prior is not None:
            prior.is_current = False
            await session.flush()  # release the unique index before insert
            new_row.superseded_by = None  # the prior row points forward
        session.add(new_row)
        await session.flush()
        if prior is not None:
            prior.superseded_by = new_row.id
        inserted += 1
        affected_student_ids.append(student.id)

    await write_audit(
        session,
        action="see.upload",
        entity_type="course_offering",
        entity_id=course_offering_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "batch_id": str(batch_id),
            "inserted": inserted,
            "skipped": len(skipped),
        },
    )
    await session.commit()
    await publish_event(
        "see.marks_released",
        {
            "course_offering_id": str(course_offering_id),
            "csv_upload_batch_id": str(batch_id),
            "row_count": inserted,
            "kind": "original",
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    # Trigger grade card regenerate for every affected student.
    term_id = offering.academic_term_id
    for sid in affected_student_ids:
        try:
            await regenerate_grade_card(
                session,
                actor=actor,
                student_user_id=sid,
                academic_term_id=term_id,
                trigger_reason="see_released",
            )
        except WorkflowError:
            continue
    return {
        "course_offering_id": course_offering_id,
        "batch_id": batch_id,
        "inserted": inserted,
        "skipped": skipped,
        "csv_upload_batch_id": batch_id,
    }


async def list_see_results(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID,
) -> list[dict[str, Any]]:
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != actor.college_id:
        raise WorkflowError("not_found", "offering not found", 404)
    course = await session.get(Course, offering.course_id)
    if actor.role == UserRole.hod:
        _require_hod_for_dept(actor, course.department_id)
    elif actor.role == UserRole.teacher and offering.teacher_user_id == actor.id:
        pass
    elif actor.role != UserRole.admin:
        raise WorkflowError("forbidden", "no access", 403)

    rows = (
        await session.execute(
            select(SEEResult, Enrollment.student_user_id, User.usn, User.name)
            .join(Enrollment, Enrollment.id == SEEResult.enrollment_id)
            .join(User, User.id == Enrollment.student_user_id)
            .where(
                SEEResult.college_id == actor.college_id,
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term_id == offering.academic_term_id,
                SEEResult.deleted_at.is_(None),
            )
            .order_by(User.usn, SEEResult.created_at.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "enrollment_id": r.enrollment_id,
            "student_user_id": sid,
            "usn": usn,
            "student_name": name,
            "kind": r.kind.value if hasattr(r.kind, "value") else str(r.kind),
            "marks_obtained": float(r.marks_obtained) if r.marks_obtained is not None else None,
            "max_marks": float(r.max_marks),
            "uploaded_at": r.uploaded_at,
            "uploaded_by_user_id": r.uploaded_by_user_id,
            "notes": r.notes,
            "is_current": r.is_current,
        }
        for r, sid, usn, name in rows
    ]


# ── Re-evaluation ───────────────────────────────────────────────────────────
async def request_re_evaluation(
    session: AsyncSession,
    *,
    student: User,
    course_offering_id: UUID,
    reason: str,
) -> ReEvaluation:
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != student.college_id:
        raise WorkflowError("bad_offering", "offering not found", 400)
    # Resolve student's enrollment for this offering.
    enrollment = (
        await session.execute(
            select(Enrollment).where(
                Enrollment.student_user_id == student.id,
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term_id == offering.academic_term_id,
                Enrollment.enrollment_state == EnrollmentState.active,
                Enrollment.withdrawn_at.is_(None),
            )
        )
    ).scalars().first()
    if enrollment is None:
        raise WorkflowError(
            "no_enrollment", "you're not enrolled in this offering", 400
        )
    original = (
        await session.execute(
            select(SEEResult).where(
                SEEResult.enrollment_id == enrollment.id,
                SEEResult.kind == SEEResultKind.original,
                SEEResult.deleted_at.is_(None),
            )
            .order_by(SEEResult.created_at)
        )
    ).scalars().first()
    if original is None or original.marks_obtained is None:
        raise WorkflowError(
            "see_not_released", "SEE marks not released yet", 409
        )
    existing = (
        await session.execute(
            select(ReEvaluation).where(
                ReEvaluation.enrollment_id == enrollment.id,
                ReEvaluation.requested_by_student_user_id == student.id,
                ReEvaluation.deleted_at.is_(None),
                ReEvaluation.status.in_(["requested", "processing"]),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise WorkflowError(
            "already_requested", "you already have a re-evaluation in progress", 409
        )
    r = ReEvaluation(
        college_id=student.college_id,
        enrollment_id=enrollment.id,
        requested_by_student_user_id=student.id,
        original_see_result_id=original.id,
        status="requested",
        reason=reason,
    )
    session.add(r)
    await session.flush()
    await write_audit(
        session,
        action="re_evaluation.request",
        entity_type="re_evaluation",
        entity_id=r.id,
        actor_user_id=student.id,
        college_id=student.college_id,
        new_value={"course_offering_id": str(course_offering_id), "reason": reason},
    )
    await session.commit()
    await session.refresh(r)
    return r


async def upload_re_evaluation_marks(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """HOD uploads revised SEE marks. Improve-or-hold rule: a revised
    mark strictly lower than original is rejected (logged in `skipped`),
    equal or higher supersedes the original SEE row.
    """
    _require_hod(actor)
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != actor.college_id:
        raise WorkflowError("bad_offering", "offering not found", 400)
    await _require_hod_for_offering(session, actor=actor, offering=offering)

    processed = 0
    improved = 0
    held = 0
    rejected: list[dict[str, Any]] = []
    affected_student_ids: list[UUID] = []
    for r in rows:
        usn = r["usn"].strip()
        revised = Decimal(str(r["revised_marks"]))
        pair = await _resolve_usn_to_enrollment(
            session,
            college_id=actor.college_id,
            course_offering_id=course_offering_id,
            usn=usn,
        )
        if pair is None:
            rejected.append({"usn": usn, "reason": "not_enrolled"})
            continue
        enrollment, student = pair
        # Locate the live re-eval request for this enrollment, if any.
        req = (
            await session.execute(
                select(ReEvaluation).where(
                    ReEvaluation.enrollment_id == enrollment.id,
                    ReEvaluation.deleted_at.is_(None),
                    ReEvaluation.status.in_(["requested", "processing"]),
                )
                .order_by(ReEvaluation.requested_at.desc())
            )
        ).scalars().first()
        original = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == enrollment.id,
                    SEEResult.kind == SEEResultKind.original,
                    SEEResult.deleted_at.is_(None),
                )
                .order_by(SEEResult.created_at)
            )
        ).scalars().first()
        if original is None or original.marks_obtained is None:
            rejected.append({"usn": usn, "reason": "no_original"})
            continue
        if revised > original.max_marks:
            rejected.append({"usn": usn, "reason": "marks_exceed_max"})
            continue
        outcome: str
        if revised < original.marks_obtained:
            outcome = "rejected"
            rejected.append(
                {
                    "usn": usn,
                    "reason": "improve_or_hold_violation",
                    "original": float(original.marks_obtained),
                    "revised": float(revised),
                }
            )
            if req is not None:
                req.status = "rejected"
                req.outcome = "rejected"
                req.resolved_at = utcnow()
                req.resolved_by_user_id = actor.id
            await session.flush()
            continue
        # Improve or hold: insert a new see_results row.
        original.is_current = False
        await session.flush()
        new_row = SEEResult(
            college_id=actor.college_id,
            enrollment_id=enrollment.id,
            kind=SEEResultKind.re_evaluation,
            marks_obtained=revised,
            max_marks=original.max_marks,
            uploaded_at=utcnow(),
            uploaded_by_user_id=actor.id,
            is_current=True,
        )
        session.add(new_row)
        await session.flush()
        original.superseded_by = new_row.id
        if req is not None:
            req.status = "completed"
            req.revised_see_result_id = new_row.id
            req.outcome = "improved" if revised > original.marks_obtained else "held"
            req.resolved_at = utcnow()
            req.resolved_by_user_id = actor.id
        if revised > original.marks_obtained:
            improved += 1
        else:
            held += 1
        processed += 1
        affected_student_ids.append(student.id)

    await write_audit(
        session,
        action="re_evaluation.upload",
        entity_type="course_offering",
        entity_id=course_offering_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "processed": processed,
            "improved": improved,
            "held": held,
            "rejected": len(rejected),
        },
    )
    await session.commit()
    await publish_event(
        "re_evaluation.completed",
        {
            "course_offering_id": str(course_offering_id),
            "processed": processed,
            "improved": improved,
            "held": held,
            "rejected_count": len(rejected),
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    term_id = offering.academic_term_id
    for sid in affected_student_ids:
        try:
            await regenerate_grade_card(
                session,
                actor=actor,
                student_user_id=sid,
                academic_term_id=term_id,
                trigger_reason="re_eval",
            )
        except WorkflowError:
            continue
    return {
        "processed": processed,
        "improved": improved,
        "held": held,
        "rejected": rejected,
    }


async def list_re_evaluations(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID | None = None,
    mine: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(
        ReEvaluation,
        Enrollment,
        User.name.label("student_name"),
        User.usn.label("student_usn"),
        SEEResult.marks_obtained.label("original_marks"),
    ).join(Enrollment, Enrollment.id == ReEvaluation.enrollment_id).join(
        User, User.id == Enrollment.student_user_id
    ).join(
        SEEResult, SEEResult.id == ReEvaluation.original_see_result_id, isouter=True
    ).where(
        ReEvaluation.college_id == actor.college_id,
        ReEvaluation.deleted_at.is_(None),
    )
    if mine:
        stmt = stmt.where(ReEvaluation.requested_by_student_user_id == actor.id)
    if course_offering_id is not None:
        offering = await session.get(CourseOffering, course_offering_id)
        if offering is not None:
            stmt = stmt.where(
                Enrollment.section_id == offering.section_id,
                Enrollment.academic_term_id == offering.academic_term_id,
            )
    rows = (await session.execute(stmt.order_by(ReEvaluation.requested_at.desc()))).all()

    out = []
    for r, enrollment, name, usn, original_marks in rows:
        # Find the student's course offering for this enrollment.
        offering_q = await session.execute(
            select(CourseOffering, Course.code)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(
                CourseOffering.section_id == enrollment.section_id,
                CourseOffering.academic_term_id == enrollment.academic_term_id,
            )
        )
        offering_rows = offering_q.all()
        # We don't know which specific offering the re-eval was for since
        # ReEvaluation links to enrollment, not offering. Surface the
        # first match (multiple offerings in the same section + term)
        # via original_see_result_id → enrollment is enough since the
        # client always asks for a specific course_offering_id.
        course_code = offering_rows[0][1] if offering_rows else None
        course_offering_id_view = (
            offering_rows[0][0].id if offering_rows else None
        )
        revised_marks = None
        if r.revised_see_result_id is not None:
            rev = await session.get(SEEResult, r.revised_see_result_id)
            if rev is not None:
                revised_marks = float(rev.marks_obtained) if rev.marks_obtained else None
        out.append(
            {
                "id": r.id,
                "enrollment_id": r.enrollment_id,
                "student_user_id": r.requested_by_student_user_id,
                "student_name": name,
                "usn": usn,
                "course_offering_id": course_offering_id_view,
                "course_code": course_code,
                "requested_at": r.requested_at,
                "status": r.status,
                "original_marks": float(original_marks) if original_marks is not None else None,
                "revised_marks": revised_marks,
                "outcome": r.outcome,
                "reason": r.reason,
                "resolved_at": r.resolved_at,
            }
        )
    return out


# ── Makeup ─────────────────────────────────────────────────────────────────
async def authorize_makeup(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID,
    enrollment_ids: list[int],
) -> dict[str, Any]:
    """HOD authorises makeup exam for selected students. This creates
    placeholder `see_results` rows with kind='makeup' and marks_obtained
    NULL — the actual marks land in the makeup upload step. We allow
    re-authorisation (idempotent: existing placeholder is reused).
    """
    _require_hod(actor)
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != actor.college_id:
        raise WorkflowError("bad_offering", "offering not found", 400)
    await _require_hod_for_offering(session, actor=actor, offering=offering)

    authorised = 0
    skipped: list[dict[str, Any]] = []
    for eid in enrollment_ids:
        enrollment = await session.get(Enrollment, eid)
        if enrollment is None or enrollment.section_id != offering.section_id:
            skipped.append({"enrollment_id": eid, "reason": "not_in_offering"})
            continue
        original = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == eid,
                    SEEResult.kind == SEEResultKind.original,
                    SEEResult.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        existing_makeup = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == eid,
                    SEEResult.kind == SEEResultKind.makeup,
                    SEEResult.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing_makeup is not None:
            # Already authorised.
            authorised += 1
            continue
        max_marks = original.max_marks if original is not None else Decimal("100")
        placeholder = SEEResult(
            college_id=actor.college_id,
            enrollment_id=eid,
            kind=SEEResultKind.makeup,
            marks_obtained=None,
            max_marks=max_marks,
            uploaded_at=None,
            uploaded_by_user_id=None,
            is_current=False,  # not current until marks land
        )
        session.add(placeholder)
        await session.flush()
        authorised += 1

    await write_audit(
        session,
        action="makeup.authorize",
        entity_type="course_offering",
        entity_id=course_offering_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"authorised": authorised, "skipped": len(skipped)},
    )
    await session.commit()
    return {"authorised": authorised, "skipped": skipped}


async def upload_makeup_marks(
    session: AsyncSession,
    *,
    actor: User,
    course_offering_id: UUID,
    max_marks: Decimal,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """HOD uploads makeup marks. Each row supersedes the prior is_current
    SEE row (original OR re_evaluation) and flips the makeup placeholder
    row's marks. Standard improve-or-hold doesn't apply here — makeup is
    a separate attempt and its outcome may legitimately be lower.
    """
    _require_hod(actor)
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None or offering.college_id != actor.college_id:
        raise WorkflowError("bad_offering", "offering not found", 400)
    await _require_hod_for_offering(session, actor=actor, offering=offering)

    processed = 0
    skipped: list[dict[str, Any]] = []
    affected_student_ids: list[UUID] = []
    for r in rows:
        usn = r["usn"].strip()
        marks = Decimal(str(r["marks_obtained"]))
        if marks > max_marks:
            skipped.append({"usn": usn, "reason": "marks_exceed_max"})
            continue
        pair = await _resolve_usn_to_enrollment(
            session,
            college_id=actor.college_id,
            course_offering_id=course_offering_id,
            usn=usn,
        )
        if pair is None:
            skipped.append({"usn": usn, "reason": "not_enrolled"})
            continue
        enrollment, student = pair
        # Find the makeup placeholder.
        placeholder = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == enrollment.id,
                    SEEResult.kind == SEEResultKind.makeup,
                    SEEResult.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if placeholder is None:
            skipped.append({"usn": usn, "reason": "not_authorised"})
            continue
        # Demote the prior is_current row.
        prior = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == enrollment.id,
                    SEEResult.is_current.is_(True),
                    SEEResult.id != placeholder.id,
                    SEEResult.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if prior is not None:
            prior.is_current = False
            await session.flush()
        placeholder.marks_obtained = marks
        placeholder.max_marks = max_marks
        placeholder.uploaded_at = utcnow()
        placeholder.uploaded_by_user_id = actor.id
        placeholder.is_current = True
        if prior is not None:
            prior.superseded_by = placeholder.id
        await session.flush()
        processed += 1
        affected_student_ids.append(student.id)

    await write_audit(
        session,
        action="makeup.upload",
        entity_type="course_offering",
        entity_id=course_offering_id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"processed": processed, "skipped": len(skipped)},
    )
    await session.commit()
    await publish_event(
        "makeup.completed",
        {
            "course_offering_id": str(course_offering_id),
            "processed": processed,
        },
        college_id=actor.college_id,
        actor_user_id=actor.id,
    )
    term_id = offering.academic_term_id
    for sid in affected_student_ids:
        try:
            await regenerate_grade_card(
                session,
                actor=actor,
                student_user_id=sid,
                academic_term_id=term_id,
                trigger_reason="makeup_completed",
            )
        except WorkflowError:
            continue
    return {"processed": processed, "skipped": skipped}


# ── Grade cards ────────────────────────────────────────────────────────────
async def _student_internal_percent(
    session: AsyncSession,
    *,
    student_user_id: UUID,
    course_offering_id: UUID,
) -> tuple[Decimal | None, list[dict[str, Any]]]:
    """Sum the student's marks across non-SEE assessments, weighted by
    `weight_percent` when set. Returns (overall_percent, components).
    `components` is for the grade card snapshot.
    """
    rows = (
        await session.execute(
            select(Assessment, Mark)
            .join(Mark, Mark.assessment_id == Assessment.id, isouter=True)
            .where(
                Assessment.course_offering_id == course_offering_id,
                Assessment.type != AssessmentType.see,
                Assessment.deleted_at.is_(None),
                or_(
                    Mark.student_user_id == student_user_id,
                    Mark.student_user_id.is_(None),
                ),
            )
        )
    ).all()
    if not rows:
        return None, []
    # Best-2-of-3 CIE; everything else is summed at face weight.
    cie_pcts: list[Decimal] = []
    other_total = Decimal("0")
    other_weight = Decimal("0")
    components = []
    for assessment, mark in rows:
        marks = Decimal(str(mark.marks_obtained)) if (mark and mark.marks_obtained is not None) else Decimal("0")
        max_marks = assessment.max_marks or Decimal("1")
        pct = (marks * Decimal(100) / max_marks).quantize(Decimal("0.01")) if max_marks > 0 else Decimal("0")
        kind = assessment.type.value if hasattr(assessment.type, "value") else str(assessment.type)
        components.append(
            {
                "type": kind,
                "name": assessment.name,
                "marks": float(marks),
                "max_marks": float(max_marks),
                "percent": float(pct),
            }
        )
        if kind in ("cie1", "cie2", "cie3"):
            cie_pcts.append(pct)
        else:
            weight = assessment.weight_percent or max_marks
            other_total += pct * Decimal(weight)
            other_weight += Decimal(weight)
    cie_pcts.sort(reverse=True)
    take = cie_pcts[:2]
    if take and other_weight > 0:
        cie_avg = sum(take) / Decimal(len(take))
        combined = (cie_avg + other_total / other_weight) / Decimal(2)
    elif take:
        combined = sum(take) / Decimal(len(take))
    elif other_weight > 0:
        combined = other_total / other_weight
    else:
        combined = None
    return (combined.quantize(Decimal("0.01")) if combined is not None else None), components


async def _build_grades_snapshot(
    session: AsyncSession,
    *,
    student: User,
    term: AcademicTerm,
    department_code: str | None,
    version_number: int,
    trigger_reason: str,
) -> dict[str, Any]:
    offerings = await _student_offerings(
        session,
        student_user_id=student.id,
        academic_term_id=term.id,
        college_id=student.college_id,
    )
    subjects = []
    total_grade_points = Decimal("0")
    total_credits = Decimal("0")
    for off in offerings:
        course = await session.get(Course, off.course_id)
        internal_pct, _components = await _student_internal_percent(
            session,
            student_user_id=student.id,
            course_offering_id=off.id,
        )
        # SEE: current see_results row for the student's enrollment in this offering.
        enrollment = (
            await session.execute(
                select(Enrollment).where(
                    Enrollment.student_user_id == student.id,
                    Enrollment.section_id == off.section_id,
                    Enrollment.academic_term_id == term.id,
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).scalars().first()
        see_pct: Decimal | None = None
        see_marks: Decimal | None = None
        is_pending = True
        is_backlog = False
        if enrollment is not None:
            see_row = (
                await session.execute(
                    select(SEEResult).where(
                        SEEResult.enrollment_id == enrollment.id,
                        SEEResult.is_current.is_(True),
                        SEEResult.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if see_row is not None and see_row.marks_obtained is not None:
                see_marks = Decimal(str(see_row.marks_obtained))
                if see_row.max_marks > 0:
                    see_pct = (see_marks * Decimal(100) / see_row.max_marks).quantize(
                        Decimal("0.01")
                    )
                is_pending = False
        # Total percent = average of internal and see when both present.
        total_pct: Decimal | None
        if internal_pct is not None and see_pct is not None:
            total_pct = ((internal_pct + see_pct) / Decimal(2)).quantize(Decimal("0.01"))
        elif see_pct is not None:
            total_pct = see_pct
        elif internal_pct is not None and not is_pending:
            total_pct = internal_pct
        else:
            total_pct = None
        if see_pct is not None and see_pct < CIE_THRESHOLD:
            is_backlog = True
        grade = _grade_for_percent(float(total_pct) if total_pct is not None else None)
        if is_pending:
            grade = "I"
        elif is_backlog:
            grade = "F"
        credits = course.credits if course else 0
        if not is_pending and credits > 0:
            total_grade_points += Decimal(_GRADE_POINTS.get(grade, 0)) * Decimal(credits)
            total_credits += Decimal(credits)
        subjects.append(
            {
                "course_offering_id": str(off.id),
                "course_code": course.code if course else "—",
                "course_title": course.title if course else "—",
                "course_type": course.course_type.value if course else "theory",
                "credits": credits,
                "internal_marks": float(internal_pct) if internal_pct is not None else None,
                "see_marks": float(see_pct) if see_pct is not None else None,
                "total_percent": float(total_pct) if total_pct is not None else None,
                "grade": grade,
                "is_pending": is_pending,
                "is_backlog": is_backlog,
            }
        )
    sgpa = (
        float((total_grade_points / total_credits).quantize(Decimal("0.01")))
        if total_credits > 0
        else None
    )
    return {
        "student_user_id": str(student.id),
        "student_name": student.name,
        "usn": student.usn,
        "academic_term_id": str(term.id),
        "academic_term_code": term.code,
        "department_code": department_code,
        "generated_at": utcnow().isoformat(),
        "version_number": version_number,
        "trigger_reason": trigger_reason,
        "subjects": subjects,
        "sgpa": sgpa,
    }


async def _ensure_grade_card_version(
    session: AsyncSession,
    *,
    actor: User,
    student: User,
    term: AcademicTerm,
    department_code: str | None,
    trigger_reason: str,
) -> tuple[GradeCard, GradeCardVersion, bool]:
    card = (
        await session.execute(
            select(GradeCard).where(
                GradeCard.college_id == actor.college_id,
                GradeCard.student_user_id == student.id,
                GradeCard.academic_term_id == term.id,
                GradeCard.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    next_version_number = 1
    if card is None:
        card = GradeCard(
            college_id=actor.college_id,
            student_user_id=student.id,
            academic_term_id=term.id,
            is_finalised=False,
        )
        session.add(card)
        await session.flush()
    else:
        n = (
            await session.execute(
                select(func.max(GradeCardVersion.version_number)).where(
                    GradeCardVersion.grade_card_id == card.id,
                )
            )
        ).scalar_one()
        next_version_number = int(n or 0) + 1

    snapshot = await _build_grades_snapshot(
        session,
        student=student,
        term=term,
        department_code=department_code,
        version_number=next_version_number,
        trigger_reason=trigger_reason,
    )

    # Skip no-op regenerates: if the current version's snapshot matches
    # (ignoring generated_at + version_number + trigger_reason), don't
    # add a new version.
    if card.current_version_id is not None:
        current = await session.get(GradeCardVersion, card.current_version_id)
        if current is not None:
            ignore = {"generated_at", "version_number", "trigger_reason"}
            current_clean = {
                k: v for k, v in current.grades_snapshot.items() if k not in ignore
            }
            new_clean = {k: v for k, v in snapshot.items() if k not in ignore}
            if current_clean == new_clean:
                return card, current, False

    version = GradeCardVersion(
        college_id=actor.college_id,
        grade_card_id=card.id,
        version_number=next_version_number,
        pdf_url="",
        grades_snapshot=snapshot,
        generated_by_user_id=actor.id,
        trigger_reason=trigger_reason,
    )
    session.add(version)
    await session.flush()
    version.pdf_url = f"inline:{version.id}"
    card.current_version_id = version.id
    # Finalise when every subject has a non-pending grade.
    all_done = all(
        not s.get("is_pending") for s in snapshot.get("subjects", [])
    )
    if all_done and snapshot.get("subjects"):
        card.is_finalised = True
    await session.flush()
    return card, version, True


async def generate_grade_card(
    session: AsyncSession,
    *,
    actor: User,
    student_user_id: UUID,
    academic_term_id: UUID,
    trigger_reason: str = "initial",
) -> tuple[GradeCard, GradeCardVersion, bool]:
    """Triggered manually by HOD or as a downstream of see/re-eval/makeup."""
    _require_hod(actor)
    term = await _term_or_404(
        session, term_id=academic_term_id, college_id=actor.college_id
    )
    student = await session.get(User, student_user_id)
    if (
        student is None
        or student.college_id != actor.college_id
        or student.role != UserRole.student
        or student.deleted_at is not None
    ):
        raise WorkflowError("bad_student", "student not found", 400)
    # Dept enforcement.
    from app.modules.academic.models import Batch

    enrollment = (
        await session.execute(
            select(Enrollment, Section, Batch)
            .join(Section, Section.id == Enrollment.section_id)
            .join(Batch, Batch.id == Section.batch_id)
            .where(
                Enrollment.student_user_id == student.id,
                Enrollment.academic_term_id == term.id,
                Enrollment.enrollment_state == EnrollmentState.active,
                Enrollment.withdrawn_at.is_(None),
            )
        )
    ).first()
    if enrollment is None:
        raise WorkflowError(
            "no_enrollment", "student has no active enrollment", 409
        )
    _e, _s, batch = enrollment
    _require_hod_for_dept(actor, batch.department_id)
    dept = await session.get(Department, batch.department_id)
    department_code = dept.code if dept else None

    card, version, is_new = await _ensure_grade_card_version(
        session,
        actor=actor,
        student=student,
        term=term,
        department_code=department_code,
        trigger_reason=trigger_reason,
    )
    await write_audit(
        session,
        action="grade_card.generate",
        entity_type="grade_card",
        entity_id=card.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "trigger_reason": trigger_reason,
            "version_number": version.version_number,
            "new_version": is_new,
        },
    )
    await session.commit()
    if is_new:
        await publish_event(
            "grade_card.regenerated",
            {
                "grade_card_id": str(card.id),
                "grade_card_version_id": str(version.id),
                "student_user_id": str(student.id),
                "academic_term_id": str(term.id),
                "version_number": version.version_number,
                "trigger_reason": trigger_reason,
            },
            college_id=actor.college_id,
            actor_user_id=actor.id,
        )
    return card, version, is_new


async def regenerate_grade_card(
    session: AsyncSession,
    *,
    actor: User,
    student_user_id: UUID,
    academic_term_id: UUID,
    trigger_reason: str,
) -> tuple[GradeCard, GradeCardVersion, bool] | None:
    """Same as generate_grade_card but tolerates students without an
    active enrollment (returns None) — used by the SEE/re-eval/makeup
    flow which doesn't want to fail an upload because one student moved.
    """
    try:
        return await generate_grade_card(
            session,
            actor=actor,
            student_user_id=student_user_id,
            academic_term_id=academic_term_id,
            trigger_reason=trigger_reason,
        )
    except WorkflowError as e:
        if e.code in ("no_enrollment", "bad_student"):
            return None
        raise


async def list_grade_cards(
    session: AsyncSession,
    *,
    actor: User,
    academic_term_id: UUID | None = None,
    student_user_id: UUID | None = None,
) -> list[dict[str, Any]]:
    if actor.role == UserRole.student:
        # Self-only. Students only see finalised cards — pending state
        # is HOD/admin-internal.
        student_user_id = actor.id
    elif actor.role not in (UserRole.admin, UserRole.hod):
        raise WorkflowError("forbidden", "student/admin/HOD only", 403)
    stmt = select(GradeCard).where(
        GradeCard.college_id == actor.college_id,
        GradeCard.deleted_at.is_(None),
    )
    if actor.role == UserRole.student:
        stmt = stmt.where(GradeCard.is_finalised.is_(True))
    if academic_term_id is not None:
        stmt = stmt.where(GradeCard.academic_term_id == academic_term_id)
    if student_user_id is not None:
        stmt = stmt.where(GradeCard.student_user_id == student_user_id)
    cards = list((await session.execute(stmt.order_by(GradeCard.updated_at.desc()))).scalars().all())
    if actor.role == UserRole.hod and cards:
        # Restrict to own dept via enrollments.
        from app.modules.academic.models import Batch

        student_ids = [c.student_user_id for c in cards]
        owned = set()
        rows = (
            await session.execute(
                select(Enrollment.student_user_id, Batch.department_id)
                .join(Section, Section.id == Enrollment.section_id)
                .join(Batch, Batch.id == Section.batch_id)
                .where(
                    Enrollment.student_user_id.in_(student_ids),
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).all()
        for sid, dept_id in rows:
            if dept_id == actor.hod_of_department_id:
                owned.add(sid)
        cards = [c for c in cards if c.student_user_id in owned]

    out: list[dict[str, Any]] = []
    for card in cards:
        versions = (
            await session.execute(
                select(GradeCardVersion)
                .where(GradeCardVersion.grade_card_id == card.id)
                .order_by(GradeCardVersion.version_number.desc())
            )
        ).scalars().all()
        student = await session.get(User, card.student_user_id)
        term = await session.get(AcademicTerm, card.academic_term_id)
        subjects = []
        sgpa = None
        if versions:
            current_snapshot = versions[0].grades_snapshot
            subjects = current_snapshot.get("subjects", [])
            sgpa = current_snapshot.get("sgpa")
        out.append(
            {
                "id": card.id,
                "student_user_id": card.student_user_id,
                "student_name": student.name if student else None,
                "usn": student.usn if student else None,
                "academic_term_id": card.academic_term_id,
                "academic_term_code": term.code if term else None,
                "is_finalised": card.is_finalised,
                "current_version_id": card.current_version_id,
                "versions": [
                    {
                        "id": v.id,
                        "grade_card_id": v.grade_card_id,
                        "version_number": v.version_number,
                        "generated_at": v.generated_at,
                        "generated_by_user_id": v.generated_by_user_id,
                        "trigger_reason": v.trigger_reason,
                        "pdf_url": v.pdf_url,
                    }
                    for v in versions
                ],
                "subjects": subjects,
                "sgpa": sgpa,
            }
        )
    return out


async def render_grade_card_pdf_for_version(
    session: AsyncSession, *, actor: User, version_id: UUID
) -> bytes:
    version = await session.get(GradeCardVersion, version_id)
    if version is None or version.college_id != actor.college_id:
        raise WorkflowError("not_found", "grade card version not found", 404)
    card = await session.get(GradeCard, version.grade_card_id)
    if card is None or card.deleted_at is not None:
        raise WorkflowError("not_found", "grade card not found", 404)
    if actor.role == UserRole.student:
        if card.student_user_id != actor.id:
            raise WorkflowError("forbidden", "not your grade card", 403)
        if not card.is_finalised:
            raise WorkflowError(
                "not_yet_released",
                "grade card not yet finalised",
                404,
            )
    if actor.role == UserRole.hod:
        from app.modules.academic.models import Batch

        enrollment = (
            await session.execute(
                select(Batch.department_id)
                .join(Section, Section.batch_id == Batch.id)
                .join(Enrollment, Enrollment.section_id == Section.id)
                .where(
                    Enrollment.student_user_id == card.student_user_id,
                    Enrollment.academic_term_id == card.academic_term_id,
                    Enrollment.enrollment_state == EnrollmentState.active,
                    Enrollment.withdrawn_at.is_(None),
                )
            )
        ).first()
        if enrollment is not None and enrollment[0] != actor.hod_of_department_id:
            raise WorkflowError("forbidden", "not your department's grade card", 403)
    return _render_grade_card_pdf(snapshot=version.grades_snapshot)
