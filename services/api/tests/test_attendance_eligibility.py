"""Critical-path tests for the student eligibility-summary endpoint
(audit Session 5).

The endpoint is a pure aggregator over `service_m10e.compute_subject_eligibility`,
so we re-use that module's fixture builder to plant attendance + CIE marks
at known thresholds and assert the badges the UI will render flip in the
right places (above 85%, between 60-85%, below 60%, NPTEL waiver, RBAC).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.academic.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    CourseType,
    TermType,
)
from tests.test_auth import DEMO_PASSWORD
from tests.test_m10e import HOD_EMAIL, _build_fixture, _login, _short


async def _login_student(client, email: str) -> dict[str, str]:
    return await _login(client, email)


# ── 1. Above 85% attendance + healthy CIE → all green ──────────────────────
@pytest.mark.asyncio
async def test_eligibility_summary_above_thresholds(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login_student(client, fx.student_email)
    r = await client.get("/attendance/me/eligibility-summary", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["academic_term_id"] == str(fx.term_id)
    assert body["academic_term_code"] == fx.term_code
    assert len(body["courses"]) == 1
    c = body["courses"][0]
    assert c["attendance_percent"] >= 85.0
    assert c["attendance_eligible"] is True
    assert c["cie_eligible"] is True
    assert c["overall_eligible"] is True
    assert c["reason"] is None


# ── 2. Between 60-85% attendance → attendance-ineligible, CIE OK ───────────
@pytest.mark.asyncio
async def test_eligibility_summary_attendance_below_85_above_60(client):
    fx = await _build_fixture(attendance_present_ratio=0.7, cie_percent=70.0)
    h = await _login_student(client, fx.student_email)
    r = await client.get("/attendance/me/eligibility-summary", headers=h)
    assert r.status_code == 200, r.text
    c = r.json()["courses"][0]
    # 70% attendance: below the 85% SEE threshold, still has CIE marks.
    assert 60.0 <= c["attendance_percent"] < 85.0
    assert c["attendance_eligible"] is False
    assert c["cie_eligible"] is True
    assert c["overall_eligible"] is False
    assert "attendance" in (c["reason"] or "").lower()


# ── 3. Below 60% attendance + low CIE → both badges red ────────────────────
@pytest.mark.asyncio
async def test_eligibility_summary_below_all_thresholds(client):
    fx = await _build_fixture(attendance_present_ratio=0.4, cie_percent=20.0)
    h = await _login_student(client, fx.student_email)
    r = await client.get("/attendance/me/eligibility-summary", headers=h)
    assert r.status_code == 200, r.text
    c = r.json()["courses"][0]
    assert c["attendance_percent"] < 60.0
    assert c["attendance_eligible"] is False
    assert c["cie_eligible"] is False
    assert c["overall_eligible"] is False
    reason = (c["reason"] or "").lower()
    assert "attendance" in reason
    assert "cie" in reason


# ── 4. NPTEL course is always waived → eligible regardless of attendance ──
@pytest.mark.asyncio
async def test_eligibility_summary_nptel_waived(client):
    fx = await _build_fixture(attendance_present_ratio=0.1, cie_percent=0.0)
    # Add a second offering with course_type='nptel' under the same section.
    async with SessionLocal() as s:
        course = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"NPTEL-{_short()}",
            title="NPTEL Demo",
            credits=3,
            semester=3,
            course_type=CourseType.nptel,
        )
        s.add(course)
        await s.flush()
        s.add(
            CourseOffering(
                college_id=fx.college_id,
                course_id=course.id,
                section_id=fx.section_id,
                teacher_user_id=fx.teacher_id,
                academic_term=fx.term_code,
                academic_term_id=fx.term_id,
                semester=3,
                is_active=True,
            )
        )
        await s.commit()

    h = await _login_student(client, fx.student_email)
    r = await client.get("/attendance/me/eligibility-summary", headers=h)
    assert r.status_code == 200, r.text
    courses = r.json()["courses"]
    assert len(courses) == 2
    nptel = next(c for c in courses if c["course_type"] == "nptel")
    theory = next(c for c in courses if c["course_type"] == "theory")
    # NPTEL is always eligible — no attendance / CIE checks apply.
    assert nptel["attendance_eligible"] is True
    assert nptel["cie_eligible"] is True
    assert nptel["overall_eligible"] is True
    # The theory course is below both thresholds — proves the per-subject
    # gating runs independently in the same response.
    assert theory["overall_eligible"] is False


# ── 5. Non-students blocked from the student-scoped endpoint ───────────────
@pytest.mark.asyncio
async def test_eligibility_summary_rbac_hod_blocked(client):
    h = await _login(client, HOD_EMAIL)
    r = await client.get("/attendance/me/eligibility-summary", headers=h)
    assert r.status_code == 403


# ── 6. term_id query param pins a specific term (round-trip the same one) ─
@pytest.mark.asyncio
async def test_eligibility_summary_term_id_param(client):
    fx = await _build_fixture(attendance_present_ratio=0.9, cie_percent=70.0)
    h = await _login_student(client, fx.student_email)
    r = await client.get(
        "/attendance/me/eligibility-summary",
        headers=h,
        params={"term_id": str(fx.term_id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["academic_term_id"] == str(fx.term_id)
    assert len(body["courses"]) == 1
