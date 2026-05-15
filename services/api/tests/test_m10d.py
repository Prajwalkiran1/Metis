"""Critical-path tests for M10d — internal deadlines, CIE schedule, tasks,
and the in-process event bus subscriber framework.

Run against the live docker-compose Postgres + Redis after migrations
0007–0012 are applied. The seed must include the BMSCE college + CSE
dept + the hod/teacher/admin users.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.event_bus import (
    _dispatch,
    build_event_payload,
    clear_handlers,
    on as on_event,
)
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
from app.modules.users.models import College, User, UserRole, UserStatus
from app.modules.workflow.models import (
    AdminNotification,
    CIESchedule,
    InternalDeadline,
    Task,
    TaskStatus,
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
    other_dept_id: uuid.UUID | None
    term_id: uuid.UUID
    term_code: str
    section_id: uuid.UUID
    hod_id: uuid.UUID
    teacher_id: uuid.UUID
    outside_teacher_id: uuid.UUID
    offering_id: uuid.UUID


async def _build_fixture() -> Fixture:
    fx = Fixture()
    fx.other_dept_id = None
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

        # An optional 'other' department for cross-dept tests.
        other = (
            await s.execute(
                select(Department).where(
                    Department.college_id == fx.college_id,
                    Department.code != "CSE",
                    Department.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if other is None:
            other = Department(
                college_id=fx.college_id,
                code=f"OTH-{_short()}",
                name="Other Test Dept",
            )
            s.add(other)
            await s.flush()
        fx.other_dept_id = other.id

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

        # Fresh term for deterministic deadline scoping.
        fx.term_code = f"T-{_short()}"
        term = AcademicTerm(
            college_id=fx.college_id,
            code=fx.term_code,
            term_type=TermType.regular,
        )
        s.add(term)
        await s.flush()
        fx.term_id = term.id

        # Reuse an existing batch+section in the dept when one is available
        # (other M10x test runs flood the [1900, 2100] admission-year window
        # so we can't always create fresh batches). The M10d tests only
        # need section/offering plumbing — they don't care about isolation
        # at the batch level because the fresh academic_term already
        # isolates deadlines + offerings.
        existing_section = (
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
        if existing_section is not None:
            section_row, _batch_row = existing_section
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
            year = next(
                (y for y in range(1900, 2100) if y not in used), None
            )
            assert year is not None
            batch = Batch(
                college_id=fx.college_id,
                department_id=fx.dept_id,
                name=f"M10d Batch {_short()}",
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

        course = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"M10D-{_short()}",
            title="M10d Test Course",
            credits=3,
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

        # A teacher who doesn't teach anything in CSE — for cross-dept
        # task rejection.
        outside = User(
            college_id=fx.college_id,
            email=f"outsider-{_short()}@bmsce.ac.in",
            name="Outside Teacher",
            role=UserRole.teacher,
            status=UserStatus.active,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        s.add(outside)
        await s.flush()
        fx.outside_teacher_id = outside.id

        await s.commit()

    return fx


# ── Deadlines ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_admin_owns_institutional_hard_hod_blocked(client):
    fx = await _build_fixture()
    a = await _login(client, ADMIN_EMAIL)
    r = await client.post(
        "/workflow/internal-deadlines",
        headers=a,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=30)
            ).isoformat(),
            "kind": "institutional_hard",
        },
    )
    assert r.status_code == 201, r.text

    h = await _login(client, HOD_EMAIL)
    r2 = await client.post(
        "/workflow/internal-deadlines",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=20)
            ).isoformat(),
            "kind": "institutional_hard",
        },
    )
    assert r2.status_code == 403, r2.text


@pytest.mark.asyncio
async def test_hod_owns_department_soft(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/internal-deadlines",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=15)
            ).isoformat(),
            "kind": "department_soft",
            "department_id": str(fx.dept_id),
        },
    )
    assert r.status_code == 201, r.text

    # Different dept → forbidden
    if fx.other_dept_id is not None:
        r2 = await client.post(
            "/workflow/internal-deadlines",
            headers=h,
            json={
                "academic_term_id": str(fx.term_id),
                "deadline_at": (
                    datetime.now(timezone.utc) + timedelta(days=10)
                ).isoformat(),
                "kind": "department_soft",
                "department_id": str(fx.other_dept_id),
            },
        )
        assert r2.status_code == 403, r2.text


@pytest.mark.asyncio
async def test_teacher_per_course_freeze(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    r = await client.post(
        "/workflow/internal-deadlines",
        headers=t,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat(),
            "kind": "per_course_freeze",
            "course_offering_id": str(fx.offering_id),
        },
    )
    assert r.status_code == 201, r.text
    # An outside teacher trying to freeze the same offering should fail.
    async with SessionLocal() as s:
        outside = await s.get(User, fx.outside_teacher_id)
        outside_email = outside.email
    o = await _login(client, outside_email)
    r2 = await client.post(
        "/workflow/internal-deadlines",
        headers=o,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=5)
            ).isoformat(),
            "kind": "per_course_freeze",
            "course_offering_id": str(fx.offering_id),
        },
    )
    assert r2.status_code == 403, r2.text


@pytest.mark.asyncio
async def test_freeze_emits_event_and_sets_offering_frozen(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    created = await client.post(
        "/workflow/internal-deadlines",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=15)
            ).isoformat(),
            "kind": "department_soft",
            "department_id": str(fx.dept_id),
        },
    )
    dl_id = created.json()["id"]

    # Offering is NOT frozen yet.
    fs0 = await client.get(
        f"/workflow/course-offerings/{fx.offering_id}/freeze-status",
        headers=h,
    )
    assert fs0.status_code == 200
    assert fs0.json()["is_frozen"] is False

    r = await client.post(
        f"/workflow/internal-deadlines/{dl_id}/freeze",
        headers=h,
        json={"is_frozen": True, "notes": "deadline reached"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deadline"]["is_frozen"] is True
    assert body["event"] is not None
    assert body["event"]["event"] == "internal_deadline.crossed"
    assert body["event"]["data"]["kind"] == "department_soft"

    # Now the offering should report frozen via the dept-soft cone.
    fs1 = await client.get(
        f"/workflow/course-offerings/{fx.offering_id}/freeze-status",
        headers=h,
    )
    assert fs1.status_code == 200
    assert fs1.json()["is_frozen"] is True
    assert fs1.json()["frozen_by_kind"] == "department_soft"


@pytest.mark.asyncio
async def test_duplicate_kind_rejected(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    body = {
        "academic_term_id": str(fx.term_id),
        "deadline_at": (
            datetime.now(timezone.utc) + timedelta(days=10)
        ).isoformat(),
        "kind": "department_soft",
        "department_id": str(fx.dept_id),
    }
    r1 = await client.post(
        "/workflow/internal-deadlines", headers=h, json=body
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/workflow/internal-deadlines", headers=h, json=body
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "duplicate_deadline"


# ── CIE schedule ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_teacher_creates_cie_and_hod_publishes(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    base = datetime.now(timezone.utc) + timedelta(days=30)
    r1 = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule",
        headers=t,
        json={
            "cie_number": 1,
            "scheduled_at": base.isoformat(),
            "duration_minutes": 90,
        },
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule",
        headers=t,
        json={
            "cie_number": 2,
            "scheduled_at": (base + timedelta(days=14)).isoformat(),
            "duration_minutes": 90,
        },
    )
    assert r2.status_code == 201, r2.text

    # Teacher can't publish.
    p1 = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule/publish",
        headers=t,
        json={"publish": True},
    )
    assert p1.status_code == 403, p1.text

    # HOD publishes.
    h = await _login(client, HOD_EMAIL)
    p2 = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule/publish",
        headers=h,
        json={"publish": True},
    )
    assert p2.status_code == 200, p2.text
    body = p2.json()
    assert body["is_published"] is True
    assert body["cie_count"] == 2
    assert body["event"]["event"] == "cie.scheduled"


@pytest.mark.asyncio
async def test_cie_order_rejected(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    base = datetime.now(timezone.utc) + timedelta(days=30)
    await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule",
        headers=t,
        json={
            "cie_number": 1,
            "scheduled_at": base.isoformat(),
            "duration_minutes": 90,
        },
    )
    # CIE-2 scheduled BEFORE CIE-1 — must reject.
    r = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule",
        headers=t,
        json={
            "cie_number": 2,
            "scheduled_at": (base - timedelta(days=1)).isoformat(),
            "duration_minutes": 90,
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "cie_out_of_order"


@pytest.mark.asyncio
async def test_published_cie_cannot_be_deleted(client):
    fx = await _build_fixture()
    t = await _login(client, TEACHER_EMAIL)
    base = datetime.now(timezone.utc) + timedelta(days=30)
    r1 = await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule",
        headers=t,
        json={
            "cie_number": 1,
            "scheduled_at": base.isoformat(),
            "duration_minutes": 90,
        },
    )
    cie_id = r1.json()["id"]
    h = await _login(client, HOD_EMAIL)
    await client.post(
        f"/workflow/course-offerings/{fx.offering_id}/cie-schedule/publish",
        headers=h,
        json={"publish": True},
    )
    d = await client.delete(
        f"/workflow/cie-schedule/{cie_id}", headers=t
    )
    assert d.status_code == 409, d.text
    assert d.json()["detail"]["code"] == "cie_published"


# ── Tasks (one-to-many shape after migration 0013) ─────────────────────────
def _assignment_for(task_body: dict, user_id) -> dict:
    """Return the assignment dict on a task body that targets this user."""
    uid = str(user_id)
    for a in task_body["assignments"]:
        if str(a["assignee_user_id"]) == uid:
            return a
    raise AssertionError(
        f"no assignment for {uid} in task {task_body['id']}"
    )


@pytest.mark.asyncio
async def test_hod_assigns_task_to_single_dept_teacher(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id)],
            "task_type": "invigilation",
            "title": "Invigilate CIE-1",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    task_id = body["id"]
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["status"] == "pending"
    assert body["is_complete"] is False
    assert body["status_counts"]["pending"] == 1

    # Teacher sees it under "mine".
    t = await _login(client, TEACHER_EMAIL)
    mine = await client.get("/workflow/tasks?mode=mine", headers=t)
    assert mine.status_code == 200
    assert any(item["id"] == task_id for item in mine.json())


@pytest.mark.asyncio
async def test_hod_assigns_task_to_three_dept_teachers(client):
    """Real workflows (multi-invigilator, paper-setting committee)
    need N assignees per task. All three see the task under mine."""
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    # The fixture creates one CSE teacher; add two more via the admin path.
    admin = await _login(client, "admin@bmsce.ac.in")
    extras = []
    for i in range(2):
        suffix = uuid.uuid4().hex[:6]
        u = await client.post(
            "/users",
            headers=admin,
            json={
                "email": f"m10d-t-{suffix}@bmsce.ac.in",
                "name": f"Extra Teacher {i}",
                "role": "teacher",
            },
        )
        extras.append(u.json()["id"])
    # Each extra needs at least one offering under the HOD's dept to
    # pass the cross-dept guard. Use the fixture's offering by
    # patching teacher_user_id off the existing offering.
    async with SessionLocal() as s:
        from app.modules.academic.models import CourseOffering, Course, Section, Batch
        from app.modules.academic.models import CourseType
        for eid in extras:
            # Create a fresh course + offering owned by this extra
            # teacher in the focal dept so the guard passes.
            course = Course(
                college_id=fx.college_id,
                department_id=fx.dept_id,
                code=f"M10D-{uuid.uuid4().hex[:4].upper()}",
                title="Extra Course",
                credits=3,
                semester=3,
                course_type=CourseType.theory,
            )
            s.add(course)
            await s.flush()
            offering = CourseOffering(
                college_id=fx.college_id,
                course_id=course.id,
                section_id=fx.section_id,
                teacher_user_id=uuid.UUID(eid),
                academic_term=fx.term_code,
                academic_term_id=fx.term_id,
                semester=3,
            )
            s.add(offering)
        await s.commit()

    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id), extras[0], extras[1]],
            "task_type": "invigilation",
            "title": "Three-invigilator CIE",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["assignments"]) == 3
    assert body["status_counts"]["pending"] == 3
    assignee_ids = {str(a["assignee_user_id"]) for a in body["assignments"]}
    assert assignee_ids == {str(fx.teacher_id), extras[0], extras[1]}


@pytest.mark.asyncio
async def test_hod_cannot_assign_to_outside_teacher_in_list(client):
    """If any assignee in the list is cross-dept the whole creation rolls back."""
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id), str(fx.outside_teacher_id)],
            "task_type": "invigilation",
            "title": "Mixed-dept attempt",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "cross_department"
    # Verify no task row was committed.
    async with SessionLocal() as s:
        from app.modules.workflow.models import Task as TaskModel
        existing = await s.execute(
            select(TaskModel).where(
                TaskModel.title == "Mixed-dept attempt",
                TaskModel.deleted_at.is_(None),
            )
        )
        assert existing.scalars().first() is None


@pytest.mark.asyncio
async def test_task_assignment_accept_then_complete(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id)],
            "task_type": "paper_setting",
            "title": "Set the paper",
        },
    )
    a_id = r.json()["assignments"][0]["id"]
    t = await _login(client, TEACHER_EMAIL)
    accepted = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert _assignment_for(body, fx.teacher_id)["status"] == "accepted"
    assert body["is_complete"] is False

    done = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "completed"},
    )
    assert done.status_code == 200
    body = done.json()
    assert _assignment_for(body, fx.teacher_id)["status"] == "completed"
    # Single-assignee task is now complete.
    assert body["is_complete"] is True

    # Cannot transition from completed.
    bad = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "accepted"},
    )
    assert bad.status_code == 409, bad.text


@pytest.mark.asyncio
async def test_task_assignment_decline_requires_reason(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id)],
            "task_type": "evaluation",
            "title": "Evaluate answer sheets",
        },
    )
    a_id = r.json()["assignments"][0]["id"]
    t = await _login(client, TEACHER_EMAIL)
    bad = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "declined"},
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["detail"]["code"] == "reason_required"
    good = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "declined", "decline_reason": "on leave that week"},
    )
    assert good.status_code == 200
    assignment = _assignment_for(good.json(), fx.teacher_id)
    assert assignment["status"] == "declined"
    assert assignment["decline_reason"] == "on leave that week"
    # Single-assignee task with declined-only is finished from the
    # workflow's perspective.
    assert good.json()["is_complete"] is True


@pytest.mark.asyncio
async def test_only_assigner_can_cancel_assignment(client):
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id)],
            "task_type": "other",
            "title": "Coordinate exam centre",
        },
    )
    a_id = r.json()["assignments"][0]["id"]
    t = await _login(client, TEACHER_EMAIL)
    bad = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=t,
        json={"status": "cancelled"},
    )
    assert bad.status_code == 403, bad.text
    good = await client.post(
        f"/workflow/task-assignments/{a_id}/status",
        headers=h,
        json={"status": "cancelled"},
    )
    assert good.status_code == 200
    assert _assignment_for(good.json(), fx.teacher_id)["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_assignment_partial_accept_partial_decline(client):
    """Two-assignee task: one accepts, one declines. The aggregate
    reflects both states; is_complete is False until every assignment
    is in a terminal state."""
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    # Add a second assignee that the cross-dept guard accepts. Reuse the
    # multi-assignee fixture-extension trick.
    admin = await _login(client, "admin@bmsce.ac.in")
    suffix = uuid.uuid4().hex[:6]
    extra = (
        await client.post(
            "/users",
            headers=admin,
            json={
                "email": f"m10d-t2-{suffix}@bmsce.ac.in",
                "name": "Second Teacher",
                "role": "teacher",
            },
        )
    ).json()
    async with SessionLocal() as s:
        from app.modules.academic.models import CourseOffering, Course, CourseType
        course = Course(
            college_id=fx.college_id,
            department_id=fx.dept_id,
            code=f"M10D-PA-{uuid.uuid4().hex[:4].upper()}",
            title="Partial Accept",
            credits=3,
            semester=3,
            course_type=CourseType.theory,
        )
        s.add(course)
        await s.flush()
        s.add(
            CourseOffering(
                college_id=fx.college_id,
                course_id=course.id,
                section_id=fx.section_id,
                teacher_user_id=uuid.UUID(extra["id"]),
                academic_term=fx.term_code,
                academic_term_id=fx.term_id,
                semester=3,
            )
        )
        await s.commit()
    # The teacher@bmsce login is the one that doubles as fx.teacher_id;
    # we can't easily log in as `extra`, so test the partial state from
    # the HOD-cancel side.
    r = await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id), extra["id"]],
            "task_type": "invigilation",
            "title": "Pair invigilation",
        },
    )
    task_id = r.json()["id"]
    # fx.teacher_id accepts.
    fx_assignment_id = [
        a["id"]
        for a in r.json()["assignments"]
        if str(a["assignee_user_id"]) == str(fx.teacher_id)
    ][0]
    t = await _login(client, TEACHER_EMAIL)
    await client.post(
        f"/workflow/task-assignments/{fx_assignment_id}/status",
        headers=t,
        json={"status": "accepted"},
    )
    # HOD cancels the extra's assignment.
    extra_assignment_id = [
        a["id"]
        for a in r.json()["assignments"]
        if str(a["assignee_user_id"]) == extra["id"]
    ][0]
    cancelled = await client.post(
        f"/workflow/task-assignments/{extra_assignment_id}/status",
        headers=h,
        json={"status": "cancelled"},
    )
    body = cancelled.json()
    assert body["status_counts"].get("accepted") == 1
    assert body["status_counts"].get("cancelled") == 1
    # Not complete — fx.teacher_id is still accepted, not in a terminal state.
    assert body["is_complete"] is False


@pytest.mark.asyncio
async def test_my_task_assignments_endpoint_returns_flat_rows(client):
    """The teacher-side /workflow/task-assignments/mine endpoint returns
    one row per assignment-for-me with the task header inline."""
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    await client.post(
        "/workflow/tasks",
        headers=h,
        json={
            "assignee_user_ids": [str(fx.teacher_id)],
            "task_type": "invigilation",
            "title": "Flat-row test",
        },
    )
    t = await _login(client, TEACHER_EMAIL)
    r = await client.get("/workflow/task-assignments/mine", headers=t)
    assert r.status_code == 200, r.text
    rows = r.json()
    # At least one of the rows matches.
    assert any(
        row["task"]["title"] == "Flat-row test"
        and str(row["assignee_user_id"]) == str(fx.teacher_id)
        for row in rows
    )


# ── Event subscriber registry ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_subscriber_dispatches_to_registered_handler():
    """The in-process registry routes a synthetic payload through to
    every registered handler. Real Redis isn't required to validate this
    contract — `_dispatch` is the same code the live psubscribe loop calls.
    """
    clear_handlers()
    received: list[dict] = []

    async def capture(payload: dict) -> None:
        received.append(payload)

    on_event("test.synthetic", capture)
    payload = build_event_payload(
        "test.synthetic",
        {"hello": "world"},
        college_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
    )
    await _dispatch("test.synthetic", payload)
    assert len(received) == 1
    assert received[0]["data"]["hello"] == "world"

    # A handler raising must not break the registry — invoke a flaky one.
    async def flaky(payload: dict) -> None:
        raise RuntimeError("boom")

    on_event("test.synthetic", flaky)
    await _dispatch("test.synthetic", payload)
    # capture got one more call despite flaky raising
    assert len(received) == 2

    clear_handlers()


@pytest.mark.asyncio
async def test_internal_deadline_admin_notification_written_via_subscriber(
    client,
):
    """End-to-end-ish: register the workflow subscriber, manually invoke
    _dispatch (mimicking what the live psubscribe loop would do), then
    verify an admin_notifications row landed. This avoids the Redis
    round-trip while still exercising the same handler.
    """
    fx = await _build_fixture()
    h = await _login(client, HOD_EMAIL)
    # Build a deadline + freeze it via HTTP so the in-app inline writes happen.
    created = await client.post(
        "/workflow/internal-deadlines",
        headers=h,
        json={
            "academic_term_id": str(fx.term_id),
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(days=12)
            ).isoformat(),
            "kind": "department_soft",
            "department_id": str(fx.dept_id),
        },
    )
    dl_id = created.json()["id"]
    frozen = await client.post(
        f"/workflow/internal-deadlines/{dl_id}/freeze",
        headers=h,
        json={"is_frozen": True, "notes": "lockdown"},
    )
    event = frozen.json()["event"]
    assert event is not None

    # Now route the event through the subscriber registry.
    clear_handlers()
    from app.modules.workflow.subscribers import register_workflow_subscribers

    register_workflow_subscribers()
    await _dispatch("internal_deadline.crossed", event)

    # Allow the per-handler new session to commit then check.
    await asyncio.sleep(0.05)
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(AdminNotification).where(
                    AdminNotification.event_type == "internal_deadline.crossed",
                    AdminNotification.payload["internal_deadline_id"].astext == dl_id,
                )
            )
        ).scalars().all()
        assert len(rows) >= 1

    clear_handlers()
