"""Critical-path tests for M10b — elective registration + dissolution + cascade.

Runs against the live docker-compose Postgres after migrations 0007–0012 are
applied. The seed must contain at least the BMSCE college, the CSE
department, hod@bmsce.ac.in linked to it, and the admin user.

The cascade is the highest-risk surface in the codebase — these tests
prove every downstream table is either correctly mutated or correctly
preserved, AND that any partial failure rolls back the entire migration.
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
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    EnrollmentState,
    Section,
    TermType,
)
from app.modules.users.models import College, User, UserRole, UserStatus
from app.modules.workflow import service_m10b
from app.modules.workflow.models import (
    AcademicOverride,
    CourseRegistration,
    ElectiveGroup,
    ElectiveGroupOption,
    LabBatch,
    LabBatchMember,
    SemesterSetup,
    SemesterSetupState,
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


# ── Fixture builder ─────────────────────────────────────────────────────────
class Fixture:
    """Holds the IDs every test refers back to. Built once per test.

    Builds a clean scenario keyed on a fresh AcademicTerm so the partial
    unique index on semester_setups (dept, term) never collides with
    other tests' setups.
    """

    college_id: uuid.UUID
    dept_id: uuid.UUID
    batch_id: uuid.UUID
    section_id: uuid.UUID
    term_id: uuid.UUID
    term_code: str
    hod_id: uuid.UUID
    teacher_id: uuid.UUID
    course_alpha_id: uuid.UUID  # elective option A
    course_beta_id: uuid.UUID  # elective option B
    offering_alpha_id: uuid.UUID
    offering_beta_id: uuid.UUID
    setup_id: uuid.UUID
    eg_id: uuid.UUID
    option_alpha_id: uuid.UUID
    option_beta_id: uuid.UUID
    student_ids: list[uuid.UUID]
    enrollment_ids: list[int]


async def _build_fixture(
    *,
    num_students: int = 3,
    student_emails: list[str] | None = None,
) -> Fixture:
    """Build a complete M10b scenario from scratch.

    Steps:
      1. Find BMSCE college + CSE dept + HOD + admin.
      2. Create a fresh AcademicTerm `T-{shortcode}` so we can own a new
         semester_setup uniquely.
      3. Create a fresh batch (year=YY) + section under CSE.
      4. Create N student users + their section enrollments (with
         enrollment_state='active' and academic_term_id set).
      5. Create two courses (alpha, beta).
      6. Create two course_offerings for the (course, section) pairs.
      7. Create the semester setup in draft, add an elective group with
         two options pointing at alpha + beta.
      8. Set state='active', published_at=now (mimics publish without
         going through the M10a flow which fan-outs an event we don't
         want here).
      9. Set registration window: opens 1 min ago, closes 1 day from now.

    Everything happens via direct ORM so we don't have to navigate the
    HTTP surface for fixture setup.
    """
    fx = Fixture()
    fx.student_ids = []
    fx.enrollment_ids = []

    async with SessionLocal() as s:
        # 1. tenant + dept + actors
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

        # 2. fresh term
        from app.core.db import utcnow

        fx.term_code = f"T-{_short()}"
        term = AcademicTerm(
            college_id=fx.college_id,
            code=fx.term_code,
            term_type=TermType.regular,
        )
        s.add(term)
        await s.flush()
        fx.term_id = term.id

        # 3. batch + section. The CHECK constraint pins admission_year to
        # [1900, 2100] so once that window fills (across many M10x runs on
        # the same docker volume) the fresh-batch path stops working.
        # Tests don't actually need a brand-new batch — the cascade only
        # cares about a fresh ACADEMIC TERM, fresh USNs, and fresh
        # course_offerings. We reuse the most recent existing CSE
        # batch+section when one exists and fall back to creating new ones.
        from sqlalchemy import func as _func

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
        else:
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
            assert admission_year is not None, "ran out of admission_year slots"
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

        # 4. student users + active enrollments
        student_emails = student_emails or [
            f"m10bstud-{_short()}@bmsce.ac.in" for _ in range(num_students)
        ]
        from app.core.security import hash_password

        # USN format is `1BM\d{2}[A-Z]{2}\d{3}` (exactly 3 trailing digits).
        # We scan the full namespace for a free slot in the (YY, RRR) plane,
        # keeping dept code 'CS'. 100 * 1000 = 100k slots — comfortably more
        # than the test suite ever produces against this DB.
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

        for i, email in enumerate(student_emails):
            usn = _next_usn()
            stu = User(
                college_id=fx.college_id,
                email=email,
                name=f"M10b Student {i}",
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

        # 5. courses
        alpha = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"EL-A-{_short()}",
            title="Elective Alpha",
            credits=3,
            semester=3,
            course_type=CourseType.theory,
        )
        beta = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"EL-B-{_short()}",
            title="Elective Beta",
            credits=3,
            semester=3,
            course_type=CourseType.theory,
        )
        s.add_all([alpha, beta])
        await s.flush()
        fx.course_alpha_id = alpha.id
        fx.course_beta_id = beta.id

        # 6. offerings for each (course, section) under the fresh term
        offering_alpha = CourseOffering(
            college_id=fx.college_id,
            course_id=alpha.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        offering_beta = CourseOffering(
            college_id=fx.college_id,
            course_id=beta.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        s.add_all([offering_alpha, offering_beta])
        await s.flush()
        fx.offering_alpha_id = offering_alpha.id
        fx.offering_beta_id = offering_beta.id

        # 7. setup + group + options
        setup = SemesterSetup(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            academic_term_id=fx.term_id,
            state=SemesterSetupState.active,
            drafted_by_user_id=fx.hod_id,
            published_at=utcnow(),
            registration_opens_at=utcnow() - timedelta(minutes=1),
            registration_closes_at=utcnow() + timedelta(days=1),
        )
        s.add(setup)
        await s.flush()
        fx.setup_id = setup.id

        eg = ElectiveGroup(
            college_id=fx.college_id,
            semester_setup_id=fx.setup_id,
            name="Test Elective Group",
            min_enrollment_to_run=2,
        )
        s.add(eg)
        await s.flush()
        fx.eg_id = eg.id

        opt_a = ElectiveGroupOption(
            college_id=fx.college_id,
            elective_group_id=fx.eg_id,
            course_id=alpha.id,
            tentative_teacher_id=fx.teacher_id,
        )
        opt_b = ElectiveGroupOption(
            college_id=fx.college_id,
            elective_group_id=fx.eg_id,
            course_id=beta.id,
            tentative_teacher_id=fx.teacher_id,
        )
        s.add_all([opt_a, opt_b])
        await s.flush()
        fx.option_alpha_id = opt_a.id
        fx.option_beta_id = opt_b.id

        await s.commit()

    return fx


async def _login_student_by_id(client, student_id: uuid.UUID) -> dict[str, str]:
    """Login the freshly-created student using their email."""
    async with SessionLocal() as s:
        stu = await s.get(User, student_id)
        assert stu is not None
    return await _login(client, stu.email)


async def _register_student(
    client,
    *,
    headers: dict[str, str],
    fx: Fixture,
    option_id: uuid.UUID,
    rank_2_option_id: uuid.UUID | None = None,
    rank_3_option_id: uuid.UUID | None = None,
) -> dict:
    """Audit Session 4 — submits a ranked preference list.

    Pass only `option_id` for backwards-compatible single-pick behaviour
    (rank-1 only). Pass `rank_2_option_id` / `rank_3_option_id` to set the
    fallbacks.
    """
    ranked = [str(option_id)]
    if rank_2_option_id is not None:
        ranked.append(str(rank_2_option_id))
    if rank_3_option_id is not None:
        ranked.append(str(rank_3_option_id))
    r = await client.post(
        "/student/registration/electives",
        headers=headers,
        json={
            "choices": [
                {
                    "elective_group_id": str(fx.eg_id),
                    "ranked_option_ids": ranked,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Student can register electives during open window ───────────────────
@pytest.mark.asyncio
async def test_student_registers_during_window(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])

    view = await client.get("/student/registration", headers=h)
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["window"]["is_open"] is True
    assert body["window"]["reason"] == "open"
    assert len(body["groups"]) == 1
    assert body["groups"][0]["preferences"] == []

    rows = await _register_student(
        client, headers=h, fx=fx, option_id=fx.option_alpha_id
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "approved"
    assert rows[0]["elective_group_option_id"] == str(fx.option_alpha_id)

    # Re-fetch the view; preferences is the rank-ordered list.
    view2 = await client.get("/student/registration", headers=h)
    prefs = view2.json()["groups"][0]["preferences"]
    assert prefs == [{"option_id": str(fx.option_alpha_id), "rank": 1}]


# ── 2. Outside-window registration blocked ─────────────────────────────────
@pytest.mark.asyncio
async def test_student_cannot_register_outside_window(client):
    fx = await _build_fixture(num_students=1)
    # Move the window into the past so the API sees it as closed.
    async with SessionLocal() as s:
        setup = await s.get(SemesterSetup, fx.setup_id)
        setup.registration_opens_at = datetime.now(timezone.utc) - timedelta(
            days=2
        )
        setup.registration_closes_at = datetime.now(timezone.utc) - timedelta(
            days=1
        )
        await s.commit()
    h = await _login_student_by_id(client, fx.student_ids[0])
    r = await client.post(
        "/student/registration/electives",
        headers=h,
        json={
            "choices": [
                {
                    "elective_group_id": str(fx.eg_id),
                    "ranked_option_ids": [str(fx.option_alpha_id)],
                }
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "window_closed"


# ── 3. RBAC: non-students blocked from /student/registration writes ────────
@pytest.mark.asyncio
async def test_non_student_blocked_from_student_endpoints(client):
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/student/registration/electives",
        headers=hod_h,
        json={"choices": []},
    )
    assert r.status_code == 403


# ── 4. Re-submission while open is idempotent ──────────────────────────────
@pytest.mark.asyncio
async def test_student_can_update_registration_idempotently(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    rows1 = await _register_student(
        client, headers=h, fx=fx, option_id=fx.option_alpha_id
    )
    reg_id_1 = rows1[0]["id"]
    rows2 = await _register_student(
        client, headers=h, fx=fx, option_id=fx.option_beta_id
    )
    # Same row mutated, not a new one.
    assert rows2[0]["id"] == reg_id_1
    assert rows2[0]["elective_group_option_id"] == str(fx.option_beta_id)
    # And there's exactly one approved row for this group.
    async with SessionLocal() as s:
        approved = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id == fx.student_ids[0],
                    CourseRegistration.elective_group_id == fx.eg_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).scalars().all()
    assert len(approved) == 1


# ── 5. HOD dissolve runs cascade across all tables (in one tx) ─────────────
@pytest.mark.asyncio
async def test_hod_dissolve_cascades(client):
    fx = await _build_fixture(num_students=3)
    # Register all 3 students with rank-1=alpha, rank-2=beta so the cascade
    # walks them onto beta when alpha dissolves.
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
        )
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "low enrolment"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_migrated"] == 3
    assert body["summary"]["students_needing_intervention"] == 0
    # elective.dissolved event payload shape (no target_option_id anymore)
    ev = body["event"]
    assert ev["event"] == "elective.dissolved"
    assert ev["data"]["student_count_migrated"] == 3
    assert ev["data"]["dissolved_option_id"] == str(fx.option_alpha_id)
    assert ev["data"]["students_needing_intervention"] == 0
    assert "target_option_id" not in ev["data"]

    # course_registrations: 3 'migrated' + 3 new 'approved' on beta
    async with SessionLocal() as s:
        all_rows = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id.in_(fx.student_ids),
                    CourseRegistration.elective_group_id == fx.eg_id,
                    CourseRegistration.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        migrated = [r for r in all_rows if r.status == "migrated"]
        approved = [r for r in all_rows if r.status == "approved"]
        assert len(migrated) == 3
        assert len(approved) == 3
        assert all(r.elective_group_option_id == fx.option_beta_id for r in approved)

        # academic_overrides: 3 student_migration rows
        overrides = (
            await s.execute(
                select(AcademicOverride).where(
                    AcademicOverride.target_student_user_id.in_(fx.student_ids),
                )
            )
        ).scalars().all()
        assert len(overrides) >= 3
        student_migs = [
            o for o in overrides
            if o.override_type.value == "student_migration"
        ]
        assert len(student_migs) == 3

        # option flipped — no specific migrated_to_option_id now (cascade
        # may have fanned to multiple targets; we leave the pointer NULL).
        opt_a = await s.get(ElectiveGroupOption, fx.option_alpha_id)
        assert opt_a.is_dissolved is True
        assert opt_a.migrated_to_option_id is None


# ── 6. Preview returns counts without mutating ─────────────────────────────
@pytest.mark.asyncio
async def test_dissolve_preview_does_not_mutate(client):
    fx = await _build_fixture(num_students=2)
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
        )
    hod_h = await _login(client, HOD_EMAIL)
    pre = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve/preview",
        headers=hod_h,
        json={"reason": "test"},
    )
    assert pre.status_code == 200, pre.text
    body = pre.json()
    assert body["students_migrated"] == 2
    assert body["enrollment_rows_mutated"] == 0  # same section

    # No mutation: option_alpha still has 2 approved
    async with SessionLocal() as s:
        approved = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.elective_group_option_id
                    == fx.option_alpha_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).scalars().all()
        assert len(approved) == 2
        opt_a = await s.get(ElectiveGroupOption, fx.option_alpha_id)
        assert opt_a.is_dissolved is False


# ── 7. HOD of another dept can't dissolve in this dept (403) ───────────────
@pytest.mark.asyncio
async def test_dissolve_blocked_for_wrong_dept(client):
    fx = await _build_fixture(num_students=1)
    # Create a fresh dept + fresh HOD assigned to that dept, get their login.
    async with SessionLocal() as s:
        from app.core.security import hash_password

        other_dept = Department(
            college_id=fx.college_id,
            name="M10bOther",
            code=f"M10B-{_short()}",
        )
        s.add(other_dept)
        await s.flush()
        other_hod = User(
            college_id=fx.college_id,
            email=f"m10bhod-{_short()}@bmsce.ac.in",
            name="M10b Other HOD",
            role=UserRole.hod,
            status=UserStatus.active,
            password_hash=hash_password(DEMO_PASSWORD),
            hod_of_department_id=other_dept.id,
        )
        s.add(other_hod)
        await s.commit()
        await s.refresh(other_hod)
        other_email = other_hod.email
    h = await _login(client, other_email)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=h,
        json={"reason": "test"},
    )
    assert r.status_code == 403, r.text


# ── 8. Manual single-student migration ─────────────────────────────────────
@pytest.mark.asyncio
async def test_manual_migration(client):
    fx = await _build_fixture(num_students=1)
    sh = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(
        client, headers=sh, fx=fx, option_id=fx.option_alpha_id
    )
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/migrate-student",
        headers=hod_h,
        json={
            "student_id": str(fx.student_ids[0]),
            "from_option_id": str(fx.option_alpha_id),
            "to_option_id": str(fx.option_beta_id),
            "reason": "student request",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_migrated"] == 1
    assert body["event"]["event"] == "student.migrated"
    assert body["event"]["data"]["reason"] == "manual_migration"

    # Manual into dissolved → rejected.
    async with SessionLocal() as s:
        opt = await s.get(ElectiveGroupOption, fx.option_alpha_id)
        opt.is_dissolved = True
        await s.commit()
    r2 = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/migrate-student",
        headers=hod_h,
        json={
            "student_id": str(fx.student_ids[0]),
            "from_option_id": str(fx.option_beta_id),
            "to_option_id": str(fx.option_alpha_id),
            "reason": "test",
        },
    )
    assert r2.status_code == 400, r2.text
    assert r2.json()["detail"]["code"] == "target_dissolved"


# ── 9. Cap with by_registration_order displaces latest registrants ─────────
@pytest.mark.asyncio
async def test_cap_by_registration_order(client):
    fx = await _build_fixture(num_students=4)
    # Register 4 students on alpha, in known order.
    registered_in_order: list[uuid.UUID] = []
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client, headers=sh, fx=fx, option_id=fx.option_alpha_id
        )
        registered_in_order.append(sid)
        # Tiny delay so created_at sort is unambiguous.
        await asyncio.sleep(0.01)
    hod_h = await _login(client, HOD_EMAIL)
    # Cap alpha at 2 → the latest 2 registrants are displaced to beta.
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/cap",
        headers=hod_h,
        json={
            "max_enrollment": 2,
            "redistribute_to_option_id": str(fx.option_beta_id),
            "redistribute_strategy": "by_registration_order",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_max"] == 2
    assert body["summary"]["students_migrated"] == 2

    # The two LATER registrants ended up on beta, the two EARLIER on alpha.
    async with SessionLocal() as s:
        alpha_students = (
            await s.execute(
                select(CourseRegistration.student_user_id).where(
                    CourseRegistration.elective_group_option_id
                    == fx.option_alpha_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).all()
        beta_students = (
            await s.execute(
                select(CourseRegistration.student_user_id).where(
                    CourseRegistration.elective_group_option_id
                    == fx.option_beta_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).all()
    alpha_ids = {r[0] for r in alpha_students}
    beta_ids = {r[0] for r in beta_students}
    assert alpha_ids == set(registered_in_order[:2])
    assert beta_ids == set(registered_in_order[2:])


# ── 10. Cap with manual returns displaced list without mutating ────────────
@pytest.mark.asyncio
async def test_cap_manual_returns_displaced(client):
    fx = await _build_fixture(num_students=3)
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client, headers=sh, fx=fx, option_id=fx.option_alpha_id
        )
        await asyncio.sleep(0.01)
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/cap",
        headers=hod_h,
        json={
            "max_enrollment": 1,
            "redistribute_to_option_id": str(fx.option_beta_id),
            "redistribute_strategy": "manual",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_max"] == 1
    assert len(body["displaced"]) == 2
    assert body["summary"] is None
    # No cascade ran — option_alpha still has 3 approved rows.
    async with SessionLocal() as s:
        n = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.elective_group_option_id
                    == fx.option_alpha_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).scalars().all()
        assert len(n) == 3


# ── 11. student.migrated payload shape after commit ────────────────────────
@pytest.mark.asyncio
async def test_student_migrated_event_shape(client, monkeypatch):
    captured: list[tuple[str, dict[str, Any]]] = []

    from app.modules.workflow import router as wf_router

    real_publish = wf_router.publish_event if hasattr(wf_router, "publish_event") else None

    # Monkey-patch the publisher used by the router.
    from app.core import event_bus

    async def _capture(event, data, *, college_id, actor_user_id):
        payload = event_bus.build_event_payload(
            event, data, college_id=college_id, actor_user_id=actor_user_id
        )
        captured.append((event, payload))
        return payload

    monkeypatch.setattr(event_bus, "publish", _capture)
    # The router imports publish locally inside each handler — patch the
    # already-imported reference path used by router.py.
    import sys

    sys.modules["app.modules.workflow.router"].publish_event = _capture  # type: ignore[attr-defined]

    fx = await _build_fixture(num_students=1)
    sh = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(
        client, headers=sh, fx=fx, option_id=fx.option_alpha_id
    )
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/migrate-student",
        headers=hod_h,
        json={
            "student_id": str(fx.student_ids[0]),
            "from_option_id": str(fx.option_alpha_id),
            "to_option_id": str(fx.option_beta_id),
            "reason": "test",
        },
    )
    assert r.status_code == 200, r.text
    # The publish call ran once for student.migrated.
    types = [c[0] for c in captured]
    assert "student.migrated" in types
    sm = next(c[1] for c in captured if c[0] == "student.migrated")
    assert set(sm.keys()) == {
        "event",
        "version",
        "occurred_at",
        "college_id",
        "actor_user_id",
        "data",
    }
    # Manual migrate keeps the legacy payload (no rank metadata since this
    # path doesn't walk preferences). Dissolve cascade adds from_rank /
    # to_rank / chain_depth — covered by test_elective_dissolved_event_shape.
    assert set(sm["data"].keys()) == {
        "student_id",
        "from_course_offering_id",
        "to_course_offering_id",
        "elective_group_id",
        "reason",
    }
    assert sm["data"]["reason"] == "manual_migration"


# ── 12. elective.dissolved payload shape ───────────────────────────────────
@pytest.mark.asyncio
async def test_elective_dissolved_event_shape(client, monkeypatch):
    captured: list[tuple[str, dict[str, Any]]] = []

    from app.core import event_bus

    async def _capture(event, data, *, college_id, actor_user_id):
        payload = event_bus.build_event_payload(
            event, data, college_id=college_id, actor_user_id=actor_user_id
        )
        captured.append((event, payload))
        return payload

    monkeypatch.setattr(event_bus, "publish", _capture)
    import sys

    sys.modules["app.modules.workflow.router"].publish_event = _capture  # type: ignore[attr-defined]

    fx = await _build_fixture(num_students=2)
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
        )
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "low enrolment"},
    )
    assert r.status_code == 200, r.text
    types = [c[0] for c in captured]
    assert "elective.dissolved" in types
    ed = next(c[1] for c in captured if c[0] == "elective.dissolved")
    # Audit Session 4 — payload no longer carries target_option_id; instead
    # it reports students_needing_intervention.
    assert set(ed["data"].keys()) == {
        "elective_group_id",
        "dissolved_option_id",
        "student_count_migrated",
        "students_needing_intervention",
        "reason",
    }
    assert ed["data"]["student_count_migrated"] == 2
    assert ed["data"]["students_needing_intervention"] == 0
    # Two student.migrated events also captured.
    student_events = [c for c in captured if c[0] == "student.migrated"]
    assert len(student_events) == 2
    # student.migrated payload now carries rank metadata (additive keys).
    sm = student_events[0][1]
    assert sm["data"]["from_rank"] == 1
    assert sm["data"]["to_rank"] == 2
    assert sm["data"]["chain_depth"] == 2


# ── 13. Cascade failure → full rollback ────────────────────────────────────
@pytest.mark.asyncio
async def test_cascade_partial_failure_rolls_back(client, monkeypatch):
    fx = await _build_fixture(num_students=3)
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
        )
    # Monkey-patch the per-student helper to raise on the 2nd call.
    call_count = {"n": 0}
    real = service_m10b._perform_student_migration

    async def _exploding(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated downstream failure")
        return await real(*args, **kwargs)

    monkeypatch.setattr(
        service_m10b, "_perform_student_migration", _exploding
    )

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "test"},
    )
    assert r.status_code == 500, r.text
    assert r.json()["detail"]["code"] == "cascade_failed"

    # Verify NOTHING changed for any of the 3 students.
    async with SessionLocal() as s:
        for sid in fx.student_ids:
            approved = (
                await s.execute(
                    select(CourseRegistration).where(
                        CourseRegistration.student_user_id == sid,
                        CourseRegistration.status == "approved",
                        CourseRegistration.elective_group_id == fx.eg_id,
                        CourseRegistration.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            assert len(approved) == 1
            assert approved[0].elective_group_option_id == fx.option_alpha_id
            migrated = (
                await s.execute(
                    select(CourseRegistration).where(
                        CourseRegistration.student_user_id == sid,
                        CourseRegistration.status == "migrated",
                        CourseRegistration.elective_group_id == fx.eg_id,
                    )
                )
            ).scalars().all()
            assert len(migrated) == 0
        # option_alpha NOT marked dissolved
        opt_a = await s.get(ElectiveGroupOption, fx.option_alpha_id)
        assert opt_a.is_dissolved is False
        # No academic_overrides for these students
        overrides = (
            await s.execute(
                select(AcademicOverride).where(
                    AcademicOverride.target_student_user_id.in_(fx.student_ids)
                )
            )
        ).scalars().all()
        student_migs = [
            o for o in overrides if o.override_type.value == "student_migration"
        ]
        assert len(student_migs) == 0


# ── 14. Attendance + marks for old offering preserved after migration ─────
@pytest.mark.asyncio
async def test_attendance_and_marks_preserved(client):
    fx = await _build_fixture(num_students=1)
    sh = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(
        client, headers=sh, fx=fx, option_id=fx.option_alpha_id
    )
    # Plant 1 attendance record + 1 mark on the OLD offering (alpha).
    from datetime import date as _date, time as _time

    from app.modules.attendance.models import (
        AttendanceRecord,
        AttendanceRecordState,
        ClassSession,
        ClassSessionState,
    )
    from app.modules.marks.models import (
        Assessment,
        AssessmentState,
        AssessmentType,
        Mark,
        MarkState,
    )
    from app.core.db import utcnow

    async with SessionLocal() as s:
        class_session = ClassSession(
            college_id=fx.college_id,
            course_offering_id=fx.offering_alpha_id,
            scheduled_date=_date.today(),
            start_time=_time(9, 0),
            end_time=_time(10, 0),
            state=ClassSessionState.closed,
        )
        s.add(class_session)
        await s.flush()
        att = AttendanceRecord(
            college_id=fx.college_id,
            class_session_id=class_session.id,
            student_user_id=fx.student_ids[0],
            state=AttendanceRecordState.verified,
            submitted_at=utcnow(),
            face_match=True,
            face_confidence=Decimal("0.95"),
        )
        s.add(att)
        assessment = Assessment(
            college_id=fx.college_id,
            course_offering_id=fx.offering_alpha_id,
            type=AssessmentType.cie1,
            name=f"CIE-test-{_short()}",
            max_marks=Decimal("40"),
            state=AssessmentState.open,
        )
        s.add(assessment)
        await s.flush()
        mark = Mark(
            college_id=fx.college_id,
            assessment_id=assessment.id,
            student_user_id=fx.student_ids[0],
            marks_obtained=Decimal("32"),
            is_absent=False,
            state=MarkState.entered,
            entered_by_user_id=fx.hod_id,
            last_modified_by_user_id=fx.hod_id,
        )
        s.add(mark)
        await s.commit()
        att_id = att.id
        mark_id = mark.id

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/migrate-student",
        headers=hod_h,
        json={
            "student_id": str(fx.student_ids[0]),
            "from_option_id": str(fx.option_alpha_id),
            "to_option_id": str(fx.option_beta_id),
            "reason": "test",
        },
    )
    assert r.status_code == 200, r.text

    # Attendance + marks rows still exist.
    async with SessionLocal() as s:
        assert await s.get(AttendanceRecord, att_id) is not None
        assert await s.get(Mark, mark_id) is not None


# ════════════════════════════════════════════════════════════════════════════
#                        Audit Session 4 — ranked preferences
# ════════════════════════════════════════════════════════════════════════════
# The cascade is the highest-risk surface in the new shape. Every test
# below proves a single edge of the rank-walking algorithm: where the
# student lands, what the running capacity counter does, when the chain
# exhausts, and what the events look like.


async def _add_third_option(fx: Fixture) -> uuid.UUID:
    """Augment the fixture with a third option ('gamma') so 3-rank tests
    have a target for rank-3. Returns the new option id; also creates the
    backing course and an offering for the fixture's section.
    """
    async with SessionLocal() as s:
        gamma = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"EL-G-{_short()}",
            title="Elective Gamma",
            credits=3,
            semester=3,
            course_type=CourseType.theory,
        )
        s.add(gamma)
        await s.flush()
        offering_gamma = CourseOffering(
            college_id=fx.college_id,
            course_id=gamma.id,
            section_id=fx.section_id,
            teacher_user_id=fx.teacher_id,
            academic_term=fx.term_code,
            academic_term_id=fx.term_id,
            semester=3,
            is_active=True,
        )
        s.add(offering_gamma)
        await s.flush()
        opt_g = ElectiveGroupOption(
            college_id=fx.college_id,
            elective_group_id=fx.eg_id,
            course_id=gamma.id,
            tentative_teacher_id=fx.teacher_id,
        )
        s.add(opt_g)
        await s.flush()
        await s.commit()
        return opt_g.id


async def _set_option_cap(option_id: uuid.UUID, cap: int) -> None:
    async with SessionLocal() as s:
        opt = await s.get(ElectiveGroupOption, option_id)
        opt.max_enrollment = cap
        await s.commit()


# ── 15. Submit with full rank-1/2/3 writes 3 prefs + 1 course_reg ──────────
@pytest.mark.asyncio
async def test_submit_full_three_ranked_prefs(client):
    fx = await _build_fixture(num_students=1)
    opt_g = await _add_third_option(fx)
    h = await _login_student_by_id(client, fx.student_ids[0])
    rows = await _register_student(
        client,
        headers=h,
        fx=fx,
        option_id=fx.option_alpha_id,
        rank_2_option_id=fx.option_beta_id,
        rank_3_option_id=opt_g,
    )
    # One committed row at rank-1
    assert len(rows) == 1
    assert rows[0]["elective_group_option_id"] == str(fx.option_alpha_id)
    # Three preference rows
    from app.modules.workflow.models import CourseRegistrationPreference

    async with SessionLocal() as s:
        prefs = (
            await s.execute(
                select(CourseRegistrationPreference)
                .where(
                    CourseRegistrationPreference.student_user_id == fx.student_ids[0],
                    CourseRegistrationPreference.elective_group_id == fx.eg_id,
                    CourseRegistrationPreference.deleted_at.is_(None),
                )
                .order_by(CourseRegistrationPreference.preference_rank)
            )
        ).scalars().all()
    assert len(prefs) == 3
    assert [p.preference_rank for p in prefs] == [1, 2, 3]
    assert prefs[0].elective_group_option_id == fx.option_alpha_id
    assert prefs[1].elective_group_option_id == fx.option_beta_id
    assert prefs[2].elective_group_option_id == opt_g


# ── 16. Submit with rank-1 only is accepted (back-compat) ──────────────────
@pytest.mark.asyncio
async def test_submit_rank_1_only(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(client, headers=h, fx=fx, option_id=fx.option_alpha_id)
    from app.modules.workflow.models import CourseRegistrationPreference

    async with SessionLocal() as s:
        prefs = (
            await s.execute(
                select(CourseRegistrationPreference).where(
                    CourseRegistrationPreference.student_user_id == fx.student_ids[0],
                    CourseRegistrationPreference.elective_group_id == fx.eg_id,
                    CourseRegistrationPreference.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(prefs) == 1
    assert prefs[0].preference_rank == 1


# ── 17. Submit rejects duplicate options within a group ────────────────────
@pytest.mark.asyncio
async def test_submit_rejects_duplicate_options_in_group(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    r = await client.post(
        "/student/registration/electives",
        headers=h,
        json={
            "choices": [
                {
                    "elective_group_id": str(fx.eg_id),
                    "ranked_option_ids": [
                        str(fx.option_alpha_id),
                        str(fx.option_alpha_id),
                    ],
                }
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "duplicate_option_in_group"


# ── 18. Submit rejects rank-2 pointing at a dissolved option ───────────────
@pytest.mark.asyncio
async def test_submit_rejects_rank_2_dissolved(client):
    fx = await _build_fixture(num_students=1)
    # Dissolve beta out-of-band; rank-2=beta should reject.
    async with SessionLocal() as s:
        beta = await s.get(ElectiveGroupOption, fx.option_beta_id)
        beta.is_dissolved = True
        await s.commit()
    h = await _login_student_by_id(client, fx.student_ids[0])
    r = await client.post(
        "/student/registration/electives",
        headers=h,
        json={
            "choices": [
                {
                    "elective_group_id": str(fx.eg_id),
                    "ranked_option_ids": [
                        str(fx.option_alpha_id),
                        str(fx.option_beta_id),
                    ],
                }
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "option_dissolved"


# ── 19. Submit allows rank-2 pointing at a currently-full option ───────────
@pytest.mark.asyncio
async def test_submit_allows_rank_2_full(client):
    # Build a fixture, register S1 to fill beta's cap (1), then S2 submits
    # rank-1=alpha, rank-2=beta(full). Accepted — fallbacks tolerate full.
    fx = await _build_fixture(num_students=2)
    await _set_option_cap(fx.option_beta_id, 1)
    s1, s2 = fx.student_ids
    h1 = await _login_student_by_id(client, s1)
    await _register_student(client, headers=h1, fx=fx, option_id=fx.option_beta_id)
    # Now beta is full. S2 submits with beta as rank-2 fallback.
    h2 = await _login_student_by_id(client, s2)
    rows = await _register_student(
        client,
        headers=h2,
        fx=fx,
        option_id=fx.option_alpha_id,
        rank_2_option_id=fx.option_beta_id,
    )
    assert rows[0]["status"] == "approved"


# ── 20. Re-submit replaces preferences; rank-1 course_reg created_at stable
@pytest.mark.asyncio
async def test_resubmit_replaces_prefs_and_preserves_created_at(client):
    fx = await _build_fixture(num_students=1)
    opt_g = await _add_third_option(fx)
    h = await _login_student_by_id(client, fx.student_ids[0])
    rows1 = await _register_student(
        client,
        headers=h,
        fx=fx,
        option_id=fx.option_alpha_id,
        rank_2_option_id=fx.option_beta_id,
    )
    reg_id_1 = rows1[0]["id"]
    created_at_1 = rows1[0]["created_at"]
    await asyncio.sleep(0.05)

    # Re-submit with a fully different set of prefs.
    rows2 = await _register_student(
        client,
        headers=h,
        fx=fx,
        option_id=fx.option_beta_id,
        rank_2_option_id=opt_g,
        rank_3_option_id=fx.option_alpha_id,
    )
    # Same course_registrations row id, same created_at — patched in place.
    assert rows2[0]["id"] == reg_id_1
    assert rows2[0]["created_at"] == created_at_1
    assert rows2[0]["elective_group_option_id"] == str(fx.option_beta_id)

    from app.modules.workflow.models import CourseRegistrationPreference

    async with SessionLocal() as s:
        live = (
            await s.execute(
                select(CourseRegistrationPreference)
                .where(
                    CourseRegistrationPreference.student_user_id == fx.student_ids[0],
                    CourseRegistrationPreference.elective_group_id == fx.eg_id,
                    CourseRegistrationPreference.deleted_at.is_(None),
                )
                .order_by(CourseRegistrationPreference.preference_rank)
            )
        ).scalars().all()
        soft_deleted = (
            await s.execute(
                select(CourseRegistrationPreference).where(
                    CourseRegistrationPreference.student_user_id == fx.student_ids[0],
                    CourseRegistrationPreference.elective_group_id == fx.eg_id,
                    CourseRegistrationPreference.deleted_at.is_not(None),
                )
            )
        ).scalars().all()
    assert len(live) == 3
    assert live[0].elective_group_option_id == fx.option_beta_id
    assert live[1].elective_group_option_id == opt_g
    assert live[2].elective_group_option_id == fx.option_alpha_id
    # Old prefs got soft-deleted, not hard-removed.
    assert len(soft_deleted) >= 2


# ── 21. Dissolve cohort splits: rank-2 capped → some walk to rank-3 ────────
@pytest.mark.asyncio
async def test_dissolve_cohort_splits_between_rank_2_and_rank_3(client):
    """3 students register rank-1=alpha, rank-2=beta(cap=1), rank-3=gamma.
    When alpha dissolves, only one student fits on beta; the other two
    walk to gamma. FIFO order on alpha decides who gets beta.
    """
    fx = await _build_fixture(num_students=3)
    opt_g = await _add_third_option(fx)
    await _set_option_cap(fx.option_beta_id, 1)

    registered_in_order: list[uuid.UUID] = []
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
            rank_3_option_id=opt_g,
        )
        registered_in_order.append(sid)
        await asyncio.sleep(0.01)

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_migrated"] == 3
    assert body["summary"]["students_needing_intervention"] == 0

    # First registrant goes to beta (rank-2). Other two to gamma (rank-3).
    async with SessionLocal() as s:
        beta_students = (
            await s.execute(
                select(CourseRegistration.student_user_id).where(
                    CourseRegistration.elective_group_option_id == fx.option_beta_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).all()
        gamma_students = (
            await s.execute(
                select(CourseRegistration.student_user_id).where(
                    CourseRegistration.elective_group_option_id == opt_g,
                    CourseRegistration.status == "approved",
                )
            )
        ).all()
    beta_ids = {r[0] for r in beta_students}
    gamma_ids = {r[0] for r in gamma_students}
    assert beta_ids == {registered_in_order[0]}
    assert gamma_ids == set(registered_in_order[1:])


# ── 22. Chain exhausted → needs_intervention row + event ───────────────────
@pytest.mark.asyncio
async def test_dissolve_exhausts_chain_writes_needs_intervention(client, monkeypatch):
    """Student registers rank-1=alpha only. Alpha dissolves. Chain is
    immediately exhausted (no rank-2/3). The student gets a
    needs_intervention row + a student.needs_intervention event.
    """
    captured: list[tuple[str, dict[str, Any]]] = []
    from app.core import event_bus

    async def _capture(event, data, *, college_id, actor_user_id):
        payload = event_bus.build_event_payload(
            event, data, college_id=college_id, actor_user_id=actor_user_id
        )
        captured.append((event, payload))
        return payload

    monkeypatch.setattr(event_bus, "publish", _capture)
    import sys

    sys.modules["app.modules.workflow.router"].publish_event = _capture  # type: ignore[attr-defined]

    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(client, headers=h, fx=fx, option_id=fx.option_alpha_id)

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "ran out of rank fallbacks"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_migrated"] == 0
    assert body["summary"]["students_needing_intervention"] == 1

    # needs_intervention row exists in course_registrations.
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id == fx.student_ids[0],
                    CourseRegistration.elective_group_id == fx.eg_id,
                    CourseRegistration.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        statuses = sorted(r.status for r in rows)
        # 'migrated' (the old approved row) + 'needs_intervention' (placeholder)
        assert statuses == ["migrated", "needs_intervention"]
        intervention = next(r for r in rows if r.status == "needs_intervention")
        assert intervention.elective_group_option_id is None
        assert intervention.course_id == fx.course_alpha_id

    types = [c[0] for c in captured]
    assert "student.needs_intervention" in types
    ni = next(c[1] for c in captured if c[0] == "student.needs_intervention")
    assert ni["data"]["student_id"] == str(fx.student_ids[0])
    assert ni["data"]["dissolved_option_id"] == str(fx.option_alpha_id)


# ── 23. Dissolve preview matches commit-time outcomes ──────────────────────
@pytest.mark.asyncio
async def test_dissolve_preview_projects_outcomes(client):
    """Preview must report the same per-student rank/outcome as commit
    would produce for the same inputs.
    """
    fx = await _build_fixture(num_students=3)
    opt_g = await _add_third_option(fx)
    await _set_option_cap(fx.option_beta_id, 1)
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
            rank_3_option_id=opt_g,
        )
        await asyncio.sleep(0.01)

    hod_h = await _login(client, HOD_EMAIL)
    pre = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve/preview",
        headers=hod_h,
        json={"reason": "preview"},
    )
    assert pre.status_code == 200, pre.text
    body = pre.json()
    assert body["students_migrated"] == 3
    assert body["students_needing_intervention"] == 0
    # First student lands on rank-2; others on rank-3.
    ranks = sorted([p["to_rank"] for p in body["per_student"] if "to_rank" in p])
    assert ranks == [2, 3, 3]


# ── 24. Cap by_registration_order without target → walks own chain ─────────
@pytest.mark.asyncio
async def test_cap_by_registration_order_no_target_walks_chain(client):
    """4 students register rank-1=alpha, rank-2=beta. Cap alpha at 2 with
    no explicit target. The 2 latest registrants walk their chain and land
    on beta.
    """
    fx = await _build_fixture(num_students=4)
    registered_in_order: list[uuid.UUID] = []
    for sid in fx.student_ids:
        sh = await _login_student_by_id(client, sid)
        await _register_student(
            client,
            headers=sh,
            fx=fx,
            option_id=fx.option_alpha_id,
            rank_2_option_id=fx.option_beta_id,
        )
        registered_in_order.append(sid)
        await asyncio.sleep(0.01)

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/cap",
        headers=hod_h,
        json={
            "max_enrollment": 2,
            "redistribute_strategy": "by_registration_order",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_migrated"] == 2
    assert body["summary"]["students_needing_intervention"] == 0

    # The two LATER registrants landed on beta.
    async with SessionLocal() as s:
        beta_students = (
            await s.execute(
                select(CourseRegistration.student_user_id).where(
                    CourseRegistration.elective_group_option_id == fx.option_beta_id,
                    CourseRegistration.status == "approved",
                )
            )
        ).all()
    beta_ids = {r[0] for r in beta_students}
    assert beta_ids == set(registered_in_order[2:])


# ── 25. HOD resolves a needs_intervention row → status flips to approved ──
@pytest.mark.asyncio
async def test_resolve_needs_intervention_flips_to_approved(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(client, headers=h, fx=fx, option_id=fx.option_alpha_id)

    # Dissolve alpha — no fallbacks → needs_intervention row.
    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "no fallbacks"},
    )
    assert r.status_code == 200, r.text

    # HOD picks beta as the resolution.
    resolve = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/resolve-needs-intervention",
        headers=hod_h,
        json={
            "student_id": str(fx.student_ids[0]),
            "to_option_id": str(fx.option_beta_id),
            "reason": "HOD picked beta",
        },
    )
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["summary"]["students_migrated"] == 1

    # The intervention row is now status='approved' on beta.
    async with SessionLocal() as s:
        approved = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id == fx.student_ids[0],
                    CourseRegistration.elective_group_id == fx.eg_id,
                    CourseRegistration.status == "approved",
                    CourseRegistration.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        needs = (
            await s.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id == fx.student_ids[0],
                    CourseRegistration.elective_group_id == fx.eg_id,
                    CourseRegistration.status == "needs_intervention",
                    CourseRegistration.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(approved) == 1
    assert approved[0].elective_group_option_id == fx.option_beta_id
    assert len(needs) == 0


# ── 26. Migration 0014 backfill: legacy approved regs preserve dissolution
@pytest.mark.asyncio
async def test_backfilled_rank_1_pref_drives_cascade(client):
    """A student whose rank-1 came from the 0014 backfill (no explicit
    rank-2/3) behaves the same as a fresh rank-1-only submission: when
    their option dissolves, they land in needs_intervention.

    Simulated by writing only a course_registrations row + a rank-1 pref
    (mimicking the backfill), then dissolving the option.
    """
    fx = await _build_fixture(num_students=1)
    sid = fx.student_ids[0]
    # Write the equivalent of a 0014-backfilled state: one approved
    # course_registrations row + a single rank-1 preference, no rank-2/3.
    async with SessionLocal() as s:
        from app.modules.workflow.models import CourseRegistrationPreference

        s.add(
            CourseRegistration(
                college_id=fx.college_id,
                student_user_id=sid,
                semester_setup_id=fx.setup_id,
                elective_group_id=fx.eg_id,
                elective_group_option_id=fx.option_alpha_id,
                course_id=fx.course_alpha_id,
                status="approved",
                is_backlog=False,
            )
        )
        s.add(
            CourseRegistrationPreference(
                college_id=fx.college_id,
                semester_setup_id=fx.setup_id,
                student_user_id=sid,
                elective_group_id=fx.eg_id,
                elective_group_option_id=fx.option_alpha_id,
                preference_rank=1,
            )
        )
        await s.commit()

    hod_h = await _login(client, HOD_EMAIL)
    r = await client.post(
        f"/workflow/elective-groups/{fx.eg_id}/options/{fx.option_alpha_id}/dissolve",
        headers=hod_h,
        json={"reason": "no fallbacks ever set"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["students_needing_intervention"] == 1


# ── 27. Student committed view: locked-in unified list (B6 + B7) ───────────
@pytest.mark.asyncio
async def test_committed_view_after_window_close(client):
    fx = await _build_fixture(num_students=1)
    h = await _login_student_by_id(client, fx.student_ids[0])
    await _register_student(client, headers=h, fx=fx, option_id=fx.option_alpha_id)

    # Close the window (move it into the past).
    async with SessionLocal() as s:
        setup = await s.get(SemesterSetup, fx.setup_id)
        setup.registration_opens_at = datetime.now(timezone.utc) - timedelta(days=2)
        setup.registration_closes_at = datetime.now(timezone.utc) - timedelta(days=1)
        await s.commit()

    r = await client.get("/student/registration/committed", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # Elective row present with status='enrolled'.
    courses = body["courses"]
    elective_rows = [c for c in courses if c["course_code"].startswith("EL-A-")]
    assert len(elective_rows) == 1
    assert elective_rows[0]["status"] == "enrolled"
    assert elective_rows[0]["offering_id"] is not None
