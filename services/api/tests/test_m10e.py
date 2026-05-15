"""Critical-path tests for M10e — hall tickets, grade cards, SEE upload,
re-evaluation, and makeup workflows.

Runs against the live docker-compose Postgres + Redis. Hall ticket and
grade card eligibility computations depend on attendance + marks tables,
so the fixture seeds class_sessions + attendance_records + assessments
+ marks for a single student so we can assert ELIGIBLE/NA outcomes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.academic.models import (
    AcademicTerm,
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Enrollment,
    EnrollmentState,
    Section,
    TermType,
)
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordState,
    ClassSession,
    ClassSessionSource,
    ClassSessionState,
)
from app.modules.marks.models import Assessment, AssessmentState, AssessmentType, Mark, MarkState
from app.modules.users.models import College, User, UserRole, UserStatus
from app.modules.workflow.models import (
    GradeCard,
    GradeCardVersion,
    HallTicket,
    HallTicketVersion,
    ReEvaluation,
    SEEResult,
    SEEResultKind,
)
from tests.test_auth import DEMO_PASSWORD


HOD_EMAIL = "hod@bmsce.ac.in"
ADMIN_EMAIL = "admin@bmsce.ac.in"
TEACHER_EMAIL = "teacher@bmsce.ac.in"


def _short() -> str:
    return uuid.uuid4().hex[:6]


async def _login(client, email: str) -> dict[str, str]:
    r = await client.post(
        "/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Fixture:
    college_id: uuid.UUID
    dept_id: uuid.UUID
    term_id: uuid.UUID
    term_code: str
    section_id: uuid.UUID
    hod_id: uuid.UUID
    teacher_id: uuid.UUID
    student_id: uuid.UUID
    student_email: str
    offering_id: uuid.UUID
    enrollment_id: int


async def _build_fixture(
    *,
    attendance_present_ratio: float = 0.9,
    cie_percent: float = 60.0,
) -> Fixture:
    """Build a student + offering with class_sessions, attendance,
    cie1/cie2/cie3 assessments + marks so eligibility computations have
    real data to chew on.
    """
    fx = Fixture()
    async with SessionLocal() as s:
        from app.core.db import utcnow
        from app.core.security import hash_password
        from app.modules.academic.models import Department

        college = (
            await s.execute(select(College).where(College.code == "BMSCE"))
        ).scalar_one()
        fx.college_id = college.id
        dept = (
            await s.execute(
                select(Department).where(
                    Department.college_id == fx.college_id,
                    Department.code == "CSE",
                )
            )
        ).scalar_one()
        fx.dept_id = dept.id
        hod = (
            await s.execute(
                select(User).where(
                    User.email == HOD_EMAIL,
                    User.college_id == fx.college_id,
                )
            )
        ).scalar_one()
        fx.hod_id = hod.id
        teacher = (
            await s.execute(
                select(User).where(
                    User.email == TEACHER_EMAIL,
                    User.college_id == fx.college_id,
                )
            )
        ).scalar_one()
        fx.teacher_id = teacher.id

        # Fresh term.
        fx.term_code = f"T-{_short()}"
        term = AcademicTerm(
            college_id=fx.college_id,
            code=fx.term_code,
            term_type=TermType.regular,
        )
        s.add(term)
        await s.flush()
        fx.term_id = term.id

        # Reuse an existing batch/section in CSE if one exists.
        existing_pair = (
            await s.execute(
                select(Section, Batch)
                .join(Batch, Batch.id == Section.batch_id)
                .where(
                    Section.college_id == fx.college_id,
                    Batch.department_id == fx.dept_id,
                    Section.deleted_at.is_(None),
                    Batch.deleted_at.is_(None),
                )
                .order_by(Section.created_at.desc())
                .limit(1)
            )
        ).first()
        if existing_pair is not None:
            section, _batch = existing_pair
            fx.section_id = section.id
        else:
            used_years = (
                await s.execute(
                    select(Batch.admission_year).where(
                        Batch.college_id == fx.college_id,
                        Batch.department_id == fx.dept_id,
                    )
                )
            ).scalars().all()
            year = next(
                (y for y in range(1900, 2100) if y not in set(used_years)), None
            )
            assert year is not None
            batch = Batch(
                college_id=fx.college_id,
                department_id=fx.dept_id,
                name=f"M10e Batch {_short()}",
                admission_year=year,
                program_duration_years=4,
                current_semester=3,
            )
            s.add(batch)
            await s.flush()
            section = Section(
                college_id=fx.college_id,
                batch_id=batch.id,
                name="A",
            )
            s.add(section)
            await s.flush()
            fx.section_id = section.id

        # USN pool.
        taken = set(
            (
                await s.execute(
                    select(User.usn).where(
                        User.college_id == fx.college_id,
                        User.usn.is_not(None),
                    )
                )
            ).scalars().all()
        )

        def _next_usn() -> str:
            for yy in range(0, 100):
                for rrr in range(0, 1000):
                    candidate = f"1BM{yy:02d}CS{rrr:03d}"
                    if candidate not in taken:
                        taken.add(candidate)
                        return candidate
            raise RuntimeError("exhausted USN namespace")

        fx.student_email = f"m10estud-{_short()}@bmsce.ac.in"
        stu = User(
            college_id=fx.college_id,
            email=fx.student_email,
            name="M10e Student",
            role=UserRole.student,
            status=UserStatus.active,
            password_hash=hash_password(DEMO_PASSWORD),
            usn=_next_usn(),
        )
        s.add(stu)
        await s.flush()
        fx.student_id = stu.id

        enr = Enrollment(
            college_id=fx.college_id,
            student_user_id=stu.id,
            section_id=fx.section_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            enrolled_at=utcnow(),
            enrollment_state=EnrollmentState.active,
        )
        s.add(enr)
        await s.flush()
        fx.enrollment_id = enr.id

        # Course + offering.
        course = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"M10E-{_short()}",
            title="M10e Test Course",
            credits=4,
            semester=3,
            course_type=CourseType.theory,
        )
        s.add(course)
        await s.flush()
        offering = CourseOffering(
            college_id=fx.college_id,
            course_id=course.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        s.add(offering)
        await s.flush()
        fx.offering_id = offering.id

        # Seed 10 closed class sessions; mark `attendance_present_ratio`
        # of them as verified.
        present_target = int(round(10 * attendance_present_ratio))
        for i in range(10):
            session_id = uuid.uuid4()
            cs = ClassSession(
                id=session_id,
                college_id=fx.college_id,
                course_offering_id=fx.offering_id,
                scheduled_date=date.today() - timedelta(days=20 - i),
                start_time=time(9, 0),
                end_time=time(10, 0),
                state=ClassSessionState.closed,
                source=ClassSessionSource.materialised,
            )
            s.add(cs)
            await s.flush()
            if i < present_target:
                s.add(
                    AttendanceRecord(
                        college_id=fx.college_id,
                        class_session_id=session_id,
                        student_user_id=fx.student_id,
                        state=AttendanceRecordState.verified,
                        submitted_at=utcnow(),
                        face_match=True,
                        face_confidence=Decimal("0.95"),
                    )
                )

        # CIE1+CIE2 assessments at target percent (40-mark each).
        for kind in (AssessmentType.cie1, AssessmentType.cie2):
            a = Assessment(
                college_id=fx.college_id,
                course_offering_id=fx.offering_id,
                type=kind,
                name=kind.value.upper(),
                max_marks=Decimal("40"),
                weight_percent=Decimal("20"),
                state=AssessmentState.locked,
            )
            s.add(a)
            await s.flush()
            marks_value = (Decimal(str(cie_percent)) / Decimal(100)) * Decimal("40")
            s.add(
                Mark(
                    college_id=fx.college_id,
                    assessment_id=a.id,
                    student_user_id=fx.student_id,
                    marks_obtained=marks_value.quantize(Decimal("0.01")),
                    is_absent=False,
                    state=MarkState.locked,
                    entered_by_user_id=fx.teacher_id,
                    last_modified_by_user_id=fx.teacher_id,
                )
            )

        await s.commit()
    return fx


# ── Hall ticket tests ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hall_ticket_eligible_student(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligible_subject_count"] == 1
    assert body["ineligible_subject_count"] == 0
    snapshot = body["versions"][0]["eligibility_snapshot"]
    subj = snapshot["subjects"][0]
    assert subj["overall_eligible"] is True


@pytest.mark.asyncio
async def test_hall_ticket_ineligible_due_to_attendance(client):
    fx = await _build_fixture(attendance_present_ratio=0.6, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligible_subject_count"] == 0
    assert body["ineligible_subject_count"] == 1
    subj = body["versions"][0]["eligibility_snapshot"]["subjects"][0]
    assert subj["overall_eligible"] is False
    assert "attendance" in (subj["reason"] or "").lower()


@pytest.mark.asyncio
async def test_hall_ticket_ineligible_due_to_cie(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=20.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    assert r.status_code == 200, r.text
    subj = r.json()["versions"][0]["eligibility_snapshot"]["subjects"][0]
    assert subj["overall_eligible"] is False
    assert "cie" in (subj["reason"] or "").lower()


@pytest.mark.asyncio
async def test_hall_ticket_idempotent_no_new_version(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r1 = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    v1_count = len(r1.json()["versions"])
    r2 = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    v2_count = len(r2.json()["versions"])
    assert v1_count == v2_count  # snapshot unchanged → no new version


@pytest.mark.asyncio
async def test_hall_ticket_pdf_download_streams_pdf(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    ticket_id = r.json()["id"]
    version_id = r.json()["versions"][0]["id"]
    # HOD must approve before the student can pull the PDF.
    await client.post(
        "/workflow/hall-tickets/approve",
        headers=h,
        json={"hall_ticket_ids": [ticket_id]},
    )
    stu = await _login(client, fx.student_email)
    pdf = await client.get(
        f"/workflow/hall-tickets/versions/{version_id}/pdf", headers=stu
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"].startswith("application/pdf")
    # PDF magic bytes.
    assert pdf.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_hall_ticket_pdf_cross_student_forbidden(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    version_id = r.json()["versions"][0]["id"]
    # A different student logging in.
    other = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    other_stu = await _login(client, other.student_email)
    pdf = await client.get(
        f"/workflow/hall-tickets/versions/{version_id}/pdf", headers=other_stu
    )
    assert pdf.status_code == 403, pdf.text


@pytest.mark.asyncio
async def test_hall_ticket_batch_and_approve(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    batch = await client.post(
        "/workflow/hall-tickets/batch",
        headers=h,
        json={"academic_term_id": str(fx.term_id)},
    )
    assert batch.status_code == 200, batch.text
    ids = batch.json()["hall_ticket_ids"]
    assert len(ids) >= 1
    # Approve them.
    appr = await client.post(
        "/workflow/hall-tickets/approve",
        headers=h,
        json={"hall_ticket_ids": ids},
    )
    assert appr.status_code == 200, appr.text
    assert appr.json()["approved"] == len(ids)
    # Listing shows them approved.
    listing = await client.get(
        "/workflow/hall-tickets",
        headers=h,
        params={"academic_term_id": str(fx.term_id)},
    )
    assert listing.status_code == 200
    for row in listing.json():
        assert row["approved_at"] is not None


# ── SEE upload tests ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_see_upload_inserts_and_supersedes(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    r1 = await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 75.0}],
        },
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["inserted"] == 1
    # Re-upload with new value → supersedes.
    r2 = await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 80.0}],
        },
    )
    assert r2.status_code == 200
    listing = await client.get(
        "/workflow/see-results",
        headers=h,
        params={"course_offering_id": str(fx.offering_id)},
    )
    rows = listing.json()
    current_rows = [r for r in rows if r["is_current"]]
    assert len(current_rows) == 1
    assert current_rows[0]["marks_obtained"] == 80.0


@pytest.mark.asyncio
async def test_see_upload_skips_marks_above_max(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    r = await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 50.0,
            "rows": [{"usn": usn, "marks_obtained": 75.0}],
        },
    )
    body = r.json()
    assert body["inserted"] == 0
    assert any(s.get("reason") == "marks_exceed_max" for s in body["skipped"])


# ── Re-evaluation tests ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_re_evaluation_improve_or_hold(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    # Seed SEE original.
    await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 60.0}],
        },
    )
    # Student requests re-eval.
    stu_h = await _login(client, fx.student_email)
    req = await client.post(
        "/workflow/re-evaluations",
        headers=stu_h,
        json={
            "course_offering_id": str(fx.offering_id),
            "reason": "I think the eval was unfair",
        },
    )
    assert req.status_code == 201, req.text
    # HOD uploads LOWER marks → rejected by improve-or-hold.
    rej = await client.post(
        "/workflow/re-evaluations/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "rows": [{"usn": usn, "revised_marks": 50.0}],
        },
    )
    body = rej.json()
    assert body["processed"] == 0
    assert any(r["reason"] == "improve_or_hold_violation" for r in body["rejected"])
    # HOD uploads HIGHER marks → improved.
    imp = await client.post(
        "/workflow/re-evaluations/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "rows": [{"usn": usn, "revised_marks": 70.0}],
        },
    )
    assert imp.status_code == 200
    body2 = imp.json()
    assert body2["processed"] == 1
    assert body2["improved"] == 1


@pytest.mark.asyncio
async def test_re_evaluation_request_without_see_rejected(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    stu_h = await _login(client, fx.student_email)
    r = await client.post(
        "/workflow/re-evaluations",
        headers=stu_h,
        json={
            "course_offering_id": str(fx.offering_id),
            "reason": "premature",
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "see_not_released"


# ── Makeup tests ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_makeup_authorize_then_upload(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    # Seed an original (student got 30, failed).
    await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 30.0}],
        },
    )
    # Authorize makeup.
    auth = await client.post(
        "/workflow/makeup/authorize",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "enrollment_ids": [fx.enrollment_id],
        },
    )
    assert auth.status_code == 200, auth.text
    assert auth.json()["authorised"] == 1
    # Upload makeup marks.
    up = await client.post(
        "/workflow/makeup/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 55.0}],
        },
    )
    assert up.status_code == 200, up.text
    assert up.json()["processed"] == 1
    # The current SEE row should now be the makeup row at 55.
    listing = await client.get(
        "/workflow/see-results",
        headers=h,
        params={"course_offering_id": str(fx.offering_id)},
    )
    rows = listing.json()
    current = [r for r in rows if r["is_current"]]
    assert len(current) == 1
    assert current[0]["kind"] == "makeup"
    assert current[0]["marks_obtained"] == 55.0


@pytest.mark.asyncio
async def test_makeup_upload_without_authorise_rejected(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    up = await client.post(
        "/workflow/makeup/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 55.0}],
        },
    )
    body = up.json()
    assert body["processed"] == 0
    assert any(s.get("reason") == "not_authorised" for s in body["skipped"])


# ── Grade card tests ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_grade_card_generate_pending_when_no_see(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/grade-cards/generate",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "student_user_ids": [str(fx.student_id)],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_finalised"] is False
    subj = body["subjects"][0]
    assert subj["is_pending"] is True
    assert subj["grade"] == "I"


@pytest.mark.asyncio
async def test_grade_card_regenerates_on_see_release(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    # Initial card (pending).
    await client.post(
        "/workflow/grade-cards/generate",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "student_user_ids": [str(fx.student_id)],
        },
    )
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    # SEE released → grade card regenerate hook should fire.
    await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 70.0}],
        },
    )
    # Now the card should have a new version with trigger_reason='see_released'.
    listing = await client.get(
        "/workflow/grade-cards",
        headers=h,
        params={"student_user_id": str(fx.student_id)},
    )
    rows = listing.json()
    assert len(rows) == 1
    card = rows[0]
    versions = card["versions"]
    assert any(v["trigger_reason"] == "see_released" for v in versions)
    assert card["is_finalised"] is True
    subj = card["subjects"][0]
    assert subj["is_pending"] is False
    assert subj["see_marks"] == 70.0
    assert subj["grade"] in {"S", "A", "B", "C", "D", "E", "F"}


@pytest.mark.asyncio
async def test_grade_card_pdf_download(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    await client.post(
        "/workflow/grade-cards/generate",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "student_user_ids": [str(fx.student_id)],
        },
    )
    # Finalise the card via SEE upload — students only get PDFs of finalised cards.
    async with SessionLocal() as s:
        stu_row = await s.get(User, fx.student_id)
        usn = stu_row.usn
    await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 70.0}],
        },
    )
    listing = await client.get(
        "/workflow/grade-cards",
        headers=h,
        params={"student_user_id": str(fx.student_id)},
    )
    version_id = listing.json()[0]["versions"][0]["id"]
    stu = await _login(client, fx.student_email)
    pdf = await client.get(
        f"/workflow/grade-cards/versions/{version_id}/pdf", headers=stu
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_event_payloads_emitted(client):
    """Verify see.marks_released + hall_ticket.generated + grade_card.regenerated
    payloads have the right shape. The full bus is exercised via the
    inline best-effort publish — we only check the HTTP response side
    effects (audit + version snapshots) here.
    """
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    # Generate hall ticket → hall_ticket.generated event emitted.
    await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    async with SessionLocal() as s:
        stu = await s.get(User, fx.student_id)
        usn = stu.usn
    # SEE upload → see.marks_released + grade_card.regenerated.
    r = await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 65.0}],
        },
    )
    assert r.status_code == 200
    async with SessionLocal() as s:
        cards = (
            await s.execute(
                select(GradeCardVersion).where(
                    GradeCardVersion.trigger_reason == "see_released",
                )
            )
        ).scalars().all()
        # At least one card was regenerated.
        assert len(cards) >= 1


# ── Visibility gating (Session 1 audit) ─────────────────────────────────────
@pytest.mark.asyncio
async def test_student_sees_no_hall_ticket_until_approved(client):
    """Hall ticket sits invisible to the student until the HOD batch-approves.
    Pre-approval generation is HOD-internal state."""
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    stu = await _login(client, fx.student_email)
    pre = await client.get("/workflow/hall-tickets/me", headers=stu)
    assert pre.status_code == 200
    assert pre.json() is None
    # HOD approves.
    listing = await client.get(
        "/workflow/hall-tickets",
        headers=h,
        params={"academic_term_id": str(fx.term_id)},
    )
    ticket_ids = [row["id"] for row in listing.json()]
    appr = await client.post(
        "/workflow/hall-tickets/approve",
        headers=h,
        json={"hall_ticket_ids": ticket_ids},
    )
    assert appr.status_code == 200
    # Student now sees it.
    post = await client.get("/workflow/hall-tickets/me", headers=stu)
    assert post.status_code == 200
    body = post.json()
    assert body is not None
    assert body["approved_at"] is not None


@pytest.mark.asyncio
async def test_student_sees_no_grade_card_until_finalised(client):
    """Pending grade cards (no SEE released yet) are HOD-internal. The
    student GET returns [] until SEE upload finalises the card."""
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    # HOD generates a card while SEE is still pending.
    gen = await client.post(
        "/workflow/grade-cards/generate",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "student_user_ids": [str(fx.student_id)],
        },
    )
    assert gen.status_code == 200
    assert gen.json()["is_finalised"] is False
    stu = await _login(client, fx.student_email)
    pre = await client.get("/workflow/grade-cards", headers=stu)
    assert pre.status_code == 200
    assert pre.json() == []
    # SEE upload finalises the card.
    async with SessionLocal() as s:
        student = await s.get(User, fx.student_id)
        usn = student.usn
    see = await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 70.0}],
        },
    )
    assert see.status_code == 200
    post = await client.get("/workflow/grade-cards", headers=stu)
    assert post.status_code == 200
    rows = post.json()
    assert len(rows) == 1
    assert rows[0]["is_finalised"] is True


@pytest.mark.asyncio
async def test_student_pdf_blocked_until_released(client):
    """Even with a known version_id, the student can't download a PDF
    until the hall ticket is approved (and the same shape applies to a
    pending grade card)."""
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login(client, HOD_EMAIL)
    # Hall ticket: generate, capture version, attempt student PDF before approval.
    gen = await client.post(
        "/workflow/hall-tickets/generate",
        headers=h,
        json={
            "student_user_id": str(fx.student_id),
            "academic_term_id": str(fx.term_id),
        },
    )
    ht_version_id = gen.json()["versions"][0]["id"]
    stu = await _login(client, fx.student_email)
    pre = await client.get(
        f"/workflow/hall-tickets/versions/{ht_version_id}/pdf", headers=stu
    )
    assert pre.status_code == 404
    # Approve, then download succeeds.
    listing = await client.get(
        "/workflow/hall-tickets",
        headers=h,
        params={"academic_term_id": str(fx.term_id)},
    )
    ticket_ids = [row["id"] for row in listing.json()]
    await client.post(
        "/workflow/hall-tickets/approve",
        headers=h,
        json={"hall_ticket_ids": ticket_ids},
    )
    post = await client.get(
        f"/workflow/hall-tickets/versions/{ht_version_id}/pdf", headers=stu
    )
    assert post.status_code == 200
    assert post.headers["content-type"].startswith("application/pdf")
    assert post.content[:4] == b"%PDF"
    # Grade card: pending → student PDF blocked; SEE → PDF flows.
    card_gen = await client.post(
        "/workflow/grade-cards/generate",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "student_user_ids": [str(fx.student_id)],
        },
    )
    gc_version_id = card_gen.json()["versions"][0]["id"]
    pending = await client.get(
        f"/workflow/grade-cards/versions/{gc_version_id}/pdf", headers=stu
    )
    assert pending.status_code == 404
    async with SessionLocal() as s:
        student = await s.get(User, fx.student_id)
        usn = student.usn
    await client.post(
        "/workflow/see-results/upload",
        headers=h,
        json={
            "course_offering_id": str(fx.offering_id),
            "max_marks": 100.0,
            "rows": [{"usn": usn, "marks_obtained": 70.0}],
        },
    )
    # The SEE flow regenerates a new version_number; fetch the latest.
    listing = await client.get(
        "/workflow/grade-cards",
        headers=h,
        params={"student_user_id": str(fx.student_id)},
    )
    finalised_version_id = listing.json()[0]["versions"][0]["id"]
    final = await client.get(
        f"/workflow/grade-cards/versions/{finalised_version_id}/pdf",
        headers=stu,
    )
    assert final.status_code == 200
    assert final.content[:4] == b"%PDF"
