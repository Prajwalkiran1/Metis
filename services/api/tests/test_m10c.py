"""Critical-path tests for M10c — lab batches, per-offering scheme picker,
and department-owned scheme templates.

Run against the live docker-compose Postgres + Redis after migrations
0007–0012 are applied. The seed has BMSCE college + CSE dept + the
hod/teacher/admin users; the institutional templates seeded in 0008 are
relied on heavily (lookup by name).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.academic.models import (
    AcademicTerm,
    AssessmentScheme,
    AssessmentSchemeComponent,
    AssessmentSchemeTemplate,
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Enrollment,
    EnrollmentState,
    Section,
    TermType,
)
from app.modules.users.models import College, User, UserRole, UserStatus
from app.modules.workflow.models import (
    AcademicOverride,
    LabBatch,
    LabBatchAssignment,
    LabBatchMember,
    OverrideType,
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
    batch_id: uuid.UUID
    section_id: uuid.UUID
    term_id: uuid.UUID
    term_code: str
    hod_id: uuid.UUID
    teacher_id: uuid.UUID
    integrated_offering_id: uuid.UUID
    theory_offering_id: uuid.UUID
    lab_side_offering_id: uuid.UUID
    student_ids: list[uuid.UUID]
    enrollment_ids: list[int]
    extra_teacher_id: uuid.UUID


async def _build_fixture(*, num_students: int = 6) -> Fixture:
    fx = Fixture()
    fx.student_ids = []
    fx.enrollment_ids = []

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

        # Fresh term so (dept, term) is unique.
        fx.term_code = f"T-{_short()}"
        term = AcademicTerm(
            college_id=fx.college_id,
            code=fx.term_code,
            term_type=TermType.regular,
        )
        s.add(term)
        await s.flush()
        fx.term_id = term.id

        # Reuse the most recent existing CSE batch+section when one is
        # already in place; otherwise create one. The admission_year
        # window [1900, 2100] fills up across many test runs on the
        # docker volume, so falling back to "any existing pair" keeps
        # the suite stable without a schema change.
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
            section_row, batch_row = existing_pair
            fx.batch_id = batch_row.id
            fx.section_id = section_row.id
            # Skip the explicit batch/section creation below.
            _existing_section_reused = True
        else:
            _existing_section_reused = False
            used_years = (
                await s.execute(
                    select(Batch.admission_year).where(
                        Batch.college_id == fx.college_id,
                        Batch.department_id == fx.dept_id,
                    )
                )
            ).scalars().all()
            used = set(used_years)
            admission_year = next(
                (y for y in range(1900, 2100) if y not in used), None
            )
            assert admission_year is not None
            batch = Batch(
                college_id=fx.college_id,
                department_id=fx.dept_id,
                name=f"CSE Test {_short()}",
                admission_year=admission_year,
                program_duration_years=4,
                current_semester=3,
            )
            s.add(batch)
            await s.flush()
            fx.batch_id = batch.id

            section = Section(
                college_id=fx.college_id,
                batch_id=fx.batch_id,
                name="A",
            )
            s.add(section)
            await s.flush()
            fx.section_id = section.id

        # Students + enrollments.
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

        for i in range(num_students):
            usn = _next_usn()
            stu = User(
                college_id=fx.college_id,
                email=f"m10cstud-{_short()}@bmsce.ac.in",
                name=f"M10c Student {i}",
                role=UserRole.student,
                status=UserStatus.active,
                password_hash=hash_password(DEMO_PASSWORD),
                usn=usn,
            )
            s.add(stu)
            await s.flush()
            fx.student_ids.append(stu.id)
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
            fx.enrollment_ids.append(enr.id)

        # An extra teacher (HOD-override target).
        from app.core.security import hash_password as _hp

        extra = User(
            college_id=fx.college_id,
            email=f"m10cteach-{_short()}@bmsce.ac.in",
            name="M10c Extra Teacher",
            role=UserRole.teacher,
            status=UserStatus.active,
            password_hash=_hp(DEMO_PASSWORD),
        )
        s.add(extra)
        await s.flush()
        fx.extra_teacher_id = extra.id

        # Courses + offerings: one integrated, one theory, plus a lab-side
        # offering with parent_offering_id pointing at the integrated.
        integrated = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"INT-{_short()}",
            title="Integrated Course",
            credits=4,
            semester=3,
            course_type=CourseType.integrated,
        )
        theory = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"TH-{_short()}",
            title="Theory Course",
            credits=3,
            semester=3,
            course_type=CourseType.theory,
        )
        s.add_all([integrated, theory])
        await s.flush()

        int_off = CourseOffering(
            college_id=fx.college_id,
            course_id=integrated.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        th_off = CourseOffering(
            college_id=fx.college_id,
            course_id=theory.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        s.add_all([int_off, th_off])
        await s.flush()
        fx.integrated_offering_id = int_off.id
        fx.theory_offering_id = th_off.id

        # Lab side of integrated — uses parent_offering_id. The same course
        # is fine here since the unique index is on (section, course, term);
        # we use a fresh lab course to keep things distinct.
        lab_course = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"INT-LAB-{_short()}",
            title="Integrated Course Lab",
            credits=1,
            semester=3,
            course_type=CourseType.lab,
        )
        s.add(lab_course)
        await s.flush()
        lab_off = CourseOffering(
            college_id=fx.college_id,
            course_id=lab_course.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
            parent_offering_id=int_off.id,
        )
        s.add(lab_off)
        await s.flush()
        fx.lab_side_offering_id = lab_off.id

        await s.commit()

    return fx


# ── Tests ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hod_creates_lab_batch_on_integrated(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches",
        headers=h,
        json={"name": "Batch A", "display_order": 1},
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Batch A"
    assert r.json()["member_count"] == 0


@pytest.mark.asyncio
async def test_non_integrated_rejects_lab_batch(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/course-offerings/{fx.theory_offering_id}/lab-batches",
        headers=h,
        json={"name": "Bad", "display_order": 1},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "course_type_incompatible"


@pytest.mark.asyncio
async def test_member_already_in_other_batch_rejected(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    b1 = (
        await client.post(
            f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches",
            headers=h,
            json={"name": "B1", "display_order": 1},
        )
    ).json()
    b2 = (
        await client.post(
            f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches",
            headers=h,
            json={"name": "B2", "display_order": 2},
        )
    ).json()
    r1 = await client.post(
        f"/workflow/lab-batches/{b1['id']}/members",
        headers=h,
        json={"student_user_ids": [str(fx.student_ids[0])]},
    )
    assert r1.status_code == 200
    assert r1.json()["added_count"] == 1

    r2 = await client.post(
        f"/workflow/lab-batches/{b2['id']}/members",
        headers=h,
        json={"student_user_ids": [str(fx.student_ids[0])]},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "student_already_in_batch"


@pytest.mark.asyncio
async def test_auto_compose_round_robin_distribution(client):
    fx = await _build_fixture(num_students=6)
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches/auto-compose",
        headers=h,
        json={"batch_count": 3, "name_prefix": "Batch"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batches_total"] == 3
    assert body["batches_created"] == 3
    assert body["students_assigned"] == 6
    # 6 students into 3 batches → exactly 2 each.
    assert sorted(body["distribution"].values()) == [2, 2, 2]
    # Event was emitted.
    assert body["event"]["event"] == "lab_batch.composed"
    assert body["event"]["data"]["students_assigned"] == 6


@pytest.mark.asyncio
async def test_teacher_assigns_own_incharge_and_hod_overrides(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    b = (
        await client.post(
            f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches",
            headers=h,
            json={"name": "B1", "display_order": 1},
        )
    ).json()
    # Teacher (owner of offering) assigns themselves as incharge.
    t = await _login(client, TEACHER_EMAIL)
    r1 = await client.post(
        f"/workflow/lab-batches/{b['id']}/assignments",
        headers=t,
        json={"teacher_user_id": str(fx.teacher_id), "role": "batch_incharge"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["previous_incharge_id"] is None
    assert r1.json()["assignment"]["role"] == "batch_incharge"

    # HOD overrides with another teacher.
    r2 = await client.post(
        f"/workflow/lab-batches/{b['id']}/assignments",
        headers=h,
        json={
            "teacher_user_id": str(fx.extra_teacher_id),
            "role": "batch_incharge",
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["previous_incharge_id"] == str(fx.teacher_id)
    assert body["event"]["event"] == "lab_batch.reassigned"
    assert body["event"]["data"]["from_teacher_user_id"] == str(fx.teacher_id)
    assert body["event"]["data"]["to_teacher_user_id"] == str(fx.extra_teacher_id)

    # academic_overrides row should exist.
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(AcademicOverride).where(
                    AcademicOverride.target_entity_id == uuid.UUID(b["id"]),
                    AcademicOverride.override_type
                    == OverrideType.lab_batch_reassignment,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id == fx.hod_id


@pytest.mark.asyncio
async def test_teacher_replaces_scheme_with_template(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    # Pick the institutional Integrated Standard template.
    async with SessionLocal() as s:
        tpl = (
            await s.execute(
                select(AssessmentSchemeTemplate).where(
                    AssessmentSchemeTemplate.college_id == fx.college_id,
                    AssessmentSchemeTemplate.owner_department_id.is_(None),
                    AssessmentSchemeTemplate.name == "Integrated Standard",
                )
            )
        ).scalar_one()
        tpl_id = tpl.id

    r = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={"template_id": str(tpl_id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_id"] == str(tpl_id)
    assert len(body["components"]) >= 1
    assert body["event"]["event"] == "assessment.scheme_configured"


@pytest.mark.asyncio
async def test_teacher_aat_above_20_rejected(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    # Replace with a custom scheme that already has AAT=10, then try to bump to 25.
    r = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 40,
                    "ordinal": 1,
                },
                {
                    "kind": "aat",
                    "label": "AAT",
                    "max_marks": 10,
                    "weight_percent": 10,
                    "ordinal": 2,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 3,
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    aat_comp_id = next(
        c["id"] for c in r.json()["components"] if c["kind"] == "aat"
    )
    # Teacher bumps to 25 → rejected.
    r2 = await client.patch(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme/components/{aat_comp_id}",
        headers=t,
        json={"weight_percent": 25},
    )
    assert r2.status_code == 403, r2.text
    assert r2.json()["detail"]["code"] == "aat_requires_hod"


@pytest.mark.asyncio
async def test_hod_can_push_aat_to_40_and_writes_override(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    # Seed at 10% AAT.
    await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 40,
                    "ordinal": 1,
                },
                {
                    "kind": "aat",
                    "label": "AAT",
                    "max_marks": 10,
                    "weight_percent": 10,
                    "ordinal": 2,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 3,
                },
            ]
        },
    )
    h = await _login(client, HOD_EMAIL)
    fresh = await client.get(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=h,
    )
    aat_comp_id = next(
        c["id"] for c in fresh.json()["components"] if c["kind"] == "aat"
    )
    r = await client.patch(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme/components/{aat_comp_id}",
        headers=h,
        json={"weight_percent": 30},
    )
    assert r.status_code == 200, r.text
    assert r.json()["aat_total_percent"] == 30.0

    # Override row written.
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(AcademicOverride).where(
                    AcademicOverride.target_entity_id == uuid.UUID(aat_comp_id),
                    AcademicOverride.override_type
                    == OverrideType.assessment_scheme_unlock,
                )
            )
        ).scalars().all()
        assert len(rows) >= 1


@pytest.mark.asyncio
async def test_aat_above_40_always_rejected(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=h,
        json={
            "components": [
                {
                    "kind": "aat",
                    "label": "AAT",
                    "max_marks": 50,
                    "weight_percent": 45,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 55,
                    "ordinal": 2,
                },
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "aat_weight_exceeded"


@pytest.mark.asyncio
async def test_lock_blocks_edits_and_unlock_writes_override(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    # Start with a valid scheme.
    await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 50,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 2,
                },
            ]
        },
    )
    # Teacher locks.
    r1 = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme/lock",
        headers=t,
        json={"reason": "marks entry starts"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["is_locked"] is True
    # Component edit attempts now fail.
    cid = r1.json()["components"][0]["id"]
    r2 = await client.patch(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme/components/{cid}",
        headers=t,
        json={"weight_percent": 51},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "scheme_locked"
    # HOD unlocks.
    h = await _login(client, HOD_EMAIL)
    r3 = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme/unlock",
        headers=h,
        json={"reason": "need to re-weight CIE after committee feedback"},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["is_locked"] is False
    # academic_overrides row exists for assessment_scheme_unlock.
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(AcademicOverride).where(
                    AcademicOverride.target_course_offering_id
                    == fx.integrated_offering_id,
                    AcademicOverride.override_type
                    == OverrideType.assessment_scheme_unlock,
                )
            )
        ).scalars().all()
        assert any(r.reason == "need to re-weight CIE after committee feedback" for r in rows)


@pytest.mark.asyncio
async def test_dept_template_create_and_other_dept_blocked(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/scheme-templates",
        headers=h,
        json={
            "name": f"CSE Custom Theory {_short()}",
            "applies_to_course_type": "theory",
            "default_components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 50,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 2,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    tpl_id = r.json()["id"]

    # A teacher cannot PATCH this template (only HOD-of-dept can).
    t = await _login(client, TEACHER_EMAIL)
    r2 = await client.patch(
        f"/workflow/scheme-templates/{tpl_id}",
        headers=t,
        json={"description": "trying to edit"},
    )
    assert r2.status_code == 403, r2.text


@pytest.mark.asyncio
async def test_template_delete_blocked_while_in_use(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    # Create a dept template.
    r = await client.post(
        "/workflow/scheme-templates",
        headers=h,
        json={
            "name": f"InUse Theory {_short()}",
            "applies_to_course_type": "theory",
            "default_components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 50,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 2,
                },
            ],
        },
    )
    tpl_id = r.json()["id"]

    # Use it on the theory offering.
    t = await _login(client, TEACHER_EMAIL)
    used = await client.post(
        f"/workflow/course-offerings/{fx.theory_offering_id}/scheme",
        headers=t,
        json={"template_id": tpl_id},
    )
    assert used.status_code == 200, used.text

    # Delete now fails.
    d = await client.delete(
        f"/workflow/scheme-templates/{tpl_id}", headers=h
    )
    assert d.status_code == 409, d.text
    assert d.json()["detail"]["code"] == "template_in_use"


@pytest.mark.asyncio
async def test_lab_side_scheme_writes_rejected_with_inherited_code(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    # GET on the lab side returns the parent's scheme as inherited.
    # First make sure parent has a scheme.
    await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 50,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 2,
                },
            ]
        },
    )
    g = await client.get(
        f"/workflow/course-offerings/{fx.lab_side_offering_id}/scheme",
        headers=t,
    )
    assert g.status_code == 200, g.text
    assert g.json()["inherited_from_offering_id"] == str(fx.integrated_offering_id)

    # Writes on the lab side fail with scheme_inherited.
    r = await client.post(
        f"/workflow/course-offerings/{fx.lab_side_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 100,
                    "ordinal": 1,
                }
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "scheme_inherited"


@pytest.mark.asyncio
async def test_replace_soft_deletes_old_components(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    first = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 50,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 50,
                    "ordinal": 2,
                },
            ]
        },
    )
    old_ids = {c["id"] for c in first.json()["components"]}

    # Second replace uses different labels so we know they're a fresh set.
    second = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=t,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "Quiz-1",
                    "max_marks": 20,
                    "weight_percent": 40,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "Final",
                    "max_marks": 100,
                    "weight_percent": 60,
                    "ordinal": 2,
                },
            ]
        },
    )
    new_ids = {c["id"] for c in second.json()["components"]}
    assert new_ids.isdisjoint(old_ids)

    async with SessionLocal() as s:
        # Old components still exist but soft-deleted; new ones live.
        old_alive = (
            await s.execute(
                select(AssessmentSchemeComponent).where(
                    AssessmentSchemeComponent.id.in_([uuid.UUID(i) for i in old_ids]),
                    AssessmentSchemeComponent.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        old_dead = (
            await s.execute(
                select(AssessmentSchemeComponent).where(
                    AssessmentSchemeComponent.id.in_([uuid.UUID(i) for i in old_ids]),
                    AssessmentSchemeComponent.deleted_at.is_not(None),
                )
            )
        ).scalars().all()
        assert len(old_alive) == 0
        assert len(old_dead) == len(old_ids)
        new_alive = (
            await s.execute(
                select(AssessmentSchemeComponent).where(
                    AssessmentSchemeComponent.id.in_([uuid.UUID(i) for i in new_ids]),
                    AssessmentSchemeComponent.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(new_alive) == len(new_ids)


@pytest.mark.asyncio
async def test_event_payload_shapes(client):
    """Verify the three M10c events match the AI_DEFERRAL_PLAN.md shape."""
    fx = await _build_fixture(num_students=4)
    h = await _login(client, HOD_EMAIL)

    # 1. assessment.scheme_configured
    r1 = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/scheme",
        headers=h,
        json={
            "components": [
                {
                    "kind": "cie",
                    "label": "CIE-1",
                    "max_marks": 40,
                    "weight_percent": 60,
                    "ordinal": 1,
                },
                {
                    "kind": "see",
                    "label": "SEE",
                    "max_marks": 100,
                    "weight_percent": 40,
                    "ordinal": 2,
                },
            ]
        },
    )
    assert r1.status_code == 200
    ev = r1.json()["event"]
    assert ev["event"] == "assessment.scheme_configured"
    assert ev["version"] == 1
    assert set(["occurred_at", "college_id", "actor_user_id", "data"]) <= ev.keys()
    assert ev["data"]["course_offering_id"] == str(fx.integrated_offering_id)
    assert ev["data"]["locked"] is False

    # 2. lab_batch.composed
    r2 = await client.post(
        f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches/auto-compose",
        headers=h,
        json={"batch_count": 2, "name_prefix": "Batch"},
    )
    assert r2.status_code == 200
    ev2 = r2.json()["event"]
    assert ev2["event"] == "lab_batch.composed"
    assert ev2["data"]["batches_total"] == 2

    # 3. lab_batch.reassigned: assign incharge, then HOD swaps it.
    bid = (
        await client.get(
            f"/workflow/course-offerings/{fx.integrated_offering_id}/lab-batches",
            headers=h,
        )
    ).json()[0]["id"]
    await client.post(
        f"/workflow/lab-batches/{bid}/assignments",
        headers=h,
        json={"teacher_user_id": str(fx.teacher_id), "role": "batch_incharge"},
    )
    swap = await client.post(
        f"/workflow/lab-batches/{bid}/assignments",
        headers=h,
        json={
            "teacher_user_id": str(fx.extra_teacher_id),
            "role": "batch_incharge",
        },
    )
    assert swap.status_code == 200
    ev3 = swap.json()["event"]
    assert ev3 is not None
    assert ev3["event"] == "lab_batch.reassigned"
    assert ev3["data"]["lab_batch_id"] == bid
    assert ev3["data"]["from_teacher_user_id"] == str(fx.teacher_id)
    assert ev3["data"]["to_teacher_user_id"] == str(fx.extra_teacher_id)
