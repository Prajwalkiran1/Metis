"""Critical-path tests for M10a (semester setup + self-publish flow).

These run against the live docker-compose Postgres after migrations
0007/0008/0009/0010 have applied. The seed must have placed at least
the BMSCE college plus `hod@bmsce.ac.in` linked to CSE.

Covered (from the M10a starter prompt):
- HOD can create a draft semester setup for their dept
- HOD cannot create a setup for another dept (403)
- HOD cannot create two setups for the same (dept, term) — UNIQUE
- HOD can add a course, then publish; state transitions correctly
- HOD cannot edit a setup after publish (only draft is editable)
- Admin can list publish events but cannot publish or edit
- Teacher with no HOD role gets 403 on /workflow/* writes
- Cross-department course assignment works without admin involvement
- Auto-scheme-link is idempotent (no duplicate, no constraint break)
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_auth import DEMO_PASSWORD


HOD_EMAIL = "hod@bmsce.ac.in"
ADMIN_EMAIL = "admin@bmsce.ac.in"
TEACHER_EMAIL = "teacher@bmsce.ac.in"


def _short() -> str:
    return uuid.uuid4().hex[:6]


async def _login(client, email: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client):
    return await _login(client, ADMIN_EMAIL)


async def _hod(client):
    return await _login(client, HOD_EMAIL)


async def _ensure_term(client, *, headers) -> str:
    """Return id of an academic term with no setup attached. Creates a fresh
    one each call so tests don't trip the (dept, term) unique index.

    The terms API ships read-only in M10a, so we hit the DB through the
    /admin/academic test surface — admin can create terms via a seed
    helper or directly via the academic-terms list endpoint. To keep this
    self-contained we use a raw SQL insert through the SessionLocal.
    """
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.academic.models import AcademicTerm, TermType
    from app.modules.users.models import User

    async with SessionLocal() as s:
        admin = (
            await s.execute(select(User).where(User.email == ADMIN_EMAIL))
        ).scalar_one()
        code = f"T-{_short()}"
        term = AcademicTerm(
            college_id=admin.college_id,
            code=code,
            term_type=TermType.regular,
        )
        s.add(term)
        await s.commit()
        await s.refresh(term)
        return str(term.id)


async def _get_hod_dept_id(client, *, headers) -> str:
    r = await client.get("/hod/dashboard", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["department"]["id"]


async def _pick_other_dept(client, *, headers, exclude: str) -> str | None:
    """Return any department id that isn't `exclude`, or None."""
    r = await client.get("/departments", headers=headers, params={"limit": 50})
    assert r.status_code == 200, r.text
    for d in r.json()["items"]:
        if d["id"] != exclude:
            return d["id"]
    return None


# ── HOD creates a draft ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hod_creates_draft(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)

    r = await client.post(
        "/workflow/semester-setups",
        headers=h,
        json={"department_id": dept, "academic_term_id": term, "notes": "n1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "draft"
    assert body["department_id"] == dept
    assert body["academic_term_id"] == term
    assert body["published_at"] is None


# ── HOD cannot create for another department ───────────────────────────────
@pytest.mark.asyncio
async def test_hod_blocked_for_other_dept(client):
    h = await _hod(client)
    a = await _admin(client)
    own = await _get_hod_dept_id(client, headers=h)
    other = await _pick_other_dept(client, headers=a, exclude=own)
    if other is None:
        # Seed only has CSE; create one so the test can run.
        r = await client.post(
            "/departments",
            headers=a,
            json={"name": "EE Test", "code": f"EE-{_short()}"},
        )
        assert r.status_code == 201, r.text
        other = r.json()["id"]
    term = await _ensure_term(client, headers=a)

    r = await client.post(
        "/workflow/semester-setups",
        headers=h,
        json={"department_id": other, "academic_term_id": term},
    )
    assert r.status_code == 403, r.text


# ── Duplicate (dept, term) setup blocked ───────────────────────────────────
@pytest.mark.asyncio
async def test_hod_cannot_create_duplicate_setup(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)

    r1 = await client.post(
        "/workflow/semester-setups",
        headers=h,
        json={"department_id": dept, "academic_term_id": term},
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        "/workflow/semester-setups",
        headers=h,
        json={"department_id": dept, "academic_term_id": term},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "duplicate_setup"


# ── Add course + publish + state transition ────────────────────────────────
async def _make_course_and_section(client, *, headers, dept_id: str):
    code = f"CS{_short()[:4]}"
    cr = await client.post(
        "/courses",
        headers=headers,
        json={
            "department_id": dept_id,
            "code": code,
            "title": f"Test {code}",
            "credits": 3,
            "semester": 3,
            "course_type": "theory",
        },
    )
    assert cr.status_code == 201, cr.text
    course_id = cr.json()["id"]

    # Find any active section for the same college.
    sec = await client.get("/sections", headers=headers, params={"limit": 1})
    assert sec.status_code == 200, sec.text
    if sec.json()["total"] == 0:
        pytest.skip("no sections seeded")
    section_id = sec.json()["items"][0]["id"]
    return course_id, section_id


async def _make_teacher(client, *, headers) -> str:
    r = await client.post(
        "/users",
        headers=headers,
        json={
            "email": f"teach-{_short()}@bmsce.ac.in",
            "name": "T Test",
            "role": "teacher",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_hod_add_course_then_publish(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)

    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()
    setup_id = setup["id"]

    course_id, section_id = await _make_course_and_section(
        client, headers=a, dept_id=dept
    )
    teacher_id = await _make_teacher(client, headers=a)

    add = await client.post(
        f"/workflow/semester-setups/{setup_id}/courses",
        headers=h,
        json={
            "course_id": course_id,
            "section_id": section_id,
            "teacher_user_id": teacher_id,
        },
    )
    assert add.status_code == 201, add.text
    assert add.json()["course_id"] == course_id
    # Auto-scheme-link kicked in.
    assert add.json()["assessment_scheme_id"] is not None

    pub = await client.post(
        f"/workflow/semester-setups/{setup_id}/publish", headers=h
    )
    assert pub.status_code == 200, pub.text
    payload = pub.json()
    assert payload["setup"]["state"] == "active"
    assert payload["setup"]["published_at"] is not None
    # Event payload shape matches AI_DEFERRAL_PLAN.md.
    ev = payload["event"]
    assert ev["event"] == "semester_setup.published"
    assert ev["version"] == 1
    assert "occurred_at" in ev
    assert "college_id" in ev
    assert ev["data"]["semester_setup_id"] == setup_id
    assert ev["data"]["department_id"] == dept


# ── Edits blocked after publish ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_published_setup_is_read_only(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)

    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()
    setup_id = setup["id"]

    course_id, section_id = await _make_course_and_section(
        client, headers=a, dept_id=dept
    )
    teacher_id = await _make_teacher(client, headers=a)
    await client.post(
        f"/workflow/semester-setups/{setup_id}/courses",
        headers=h,
        json={
            "course_id": course_id,
            "section_id": section_id,
            "teacher_user_id": teacher_id,
        },
    )
    pub = await client.post(
        f"/workflow/semester-setups/{setup_id}/publish", headers=h
    )
    assert pub.status_code == 200

    # PATCH after publish → 409 not_draft
    bad = await client.patch(
        f"/workflow/semester-setups/{setup_id}",
        headers=h,
        json={"notes": "tried to edit"},
    )
    assert bad.status_code == 409, bad.text
    assert bad.json()["detail"]["code"] == "not_draft"


# ── Publish requires courses + teachers ────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_validates_at_least_one_course(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)

    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()
    pub = await client.post(
        f"/workflow/semester-setups/{setup['id']}/publish", headers=h
    )
    assert pub.status_code == 409, pub.text
    assert pub.json()["detail"]["code"] == "publish_no_courses"


# ── Admin: read-only on workflow ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_admin_can_list_setups_but_cannot_publish(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)
    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()

    # Admin can list across departments.
    listr = await client.get("/workflow/semester-setups", headers=a)
    assert listr.status_code == 200, listr.text
    assert any(s["id"] == setup["id"] for s in listr.json())

    # Admin cannot publish (require_hod blocks).
    pub = await client.post(
        f"/workflow/semester-setups/{setup['id']}/publish", headers=a
    )
    assert pub.status_code == 403, pub.text

    # Admin cannot edit notes either.
    patch = await client.patch(
        f"/workflow/semester-setups/{setup['id']}",
        headers=a,
        json={"notes": "admin override"},
    )
    assert patch.status_code == 403, patch.text


# ── Admin notifications feed populated on publish ──────────────────────────
@pytest.mark.asyncio
async def test_admin_notifications_populated_on_publish(client):
    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)
    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()
    course_id, section_id = await _make_course_and_section(
        client, headers=a, dept_id=dept
    )
    teacher_id = await _make_teacher(client, headers=a)
    await client.post(
        f"/workflow/semester-setups/{setup['id']}/courses",
        headers=h,
        json={
            "course_id": course_id,
            "section_id": section_id,
            "teacher_user_id": teacher_id,
        },
    )
    await client.post(
        f"/workflow/semester-setups/{setup['id']}/publish", headers=h
    )

    feed = await client.get("/admin/notifications", headers=a)
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert body["total"] >= 1
    matched = [
        n
        for n in body["items"]
        if n["event_type"] == "semester_setup.published"
        and n["payload"].get("semester_setup_id") == setup["id"]
    ]
    assert len(matched) == 1


# ── Teacher (no HOD role) blocked from writes ──────────────────────────────
@pytest.mark.asyncio
async def test_teacher_blocked_from_workflow_writes(client):
    t = await _login(client, TEACHER_EMAIL)
    a = await _admin(client)
    term = await _ensure_term(client, headers=a)
    depts = await client.get("/departments", headers=a, params={"limit": 1})
    if depts.json()["total"] == 0:
        pytest.skip("no departments")
    dept_id = depts.json()["items"][0]["id"]

    r = await client.post(
        "/workflow/semester-setups",
        headers=t,
        json={"department_id": dept_id, "academic_term_id": term},
    )
    assert r.status_code == 403, r.text


# ── Cross-department course assignment ─────────────────────────────────────
@pytest.mark.asyncio
async def test_cross_department_course_assignment(client):
    """HOD of one dept can add a course owned by a different dept to their
    setup — no admin approval required.
    """
    h = await _hod(client)
    a = await _admin(client)
    own_dept = await _get_hod_dept_id(client, headers=h)
    other_dept = await _pick_other_dept(
        client, headers=a, exclude=own_dept
    )
    if other_dept is None:
        r = await client.post(
            "/departments",
            headers=a,
            json={"name": "Test Other", "code": f"OT-{_short()}"},
        )
        assert r.status_code == 201
        other_dept = r.json()["id"]

    term = await _ensure_term(client, headers=a)
    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": own_dept, "academic_term_id": term},
        )
    ).json()

    # Course owned by OTHER dept.
    course_id, section_id = await _make_course_and_section(
        client, headers=a, dept_id=other_dept
    )
    teacher_id = await _make_teacher(client, headers=a)
    r = await client.post(
        f"/workflow/semester-setups/{setup['id']}/courses",
        headers=h,
        json={
            "course_id": course_id,
            "section_id": section_id,
            "teacher_user_id": teacher_id,
        },
    )
    assert r.status_code == 201, r.text


# ── Auto-scheme-link is idempotent ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_auto_scheme_link_is_idempotent(client):
    """Re-creating + removing courses should not collide on the
    `uq_assessment_schemes_offering_active` unique index. The service
    layer checks `offering.assessment_scheme_id is None` before
    instantiating a fresh scheme.
    """
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.academic.models import AssessmentScheme

    h = await _hod(client)
    a = await _admin(client)
    dept = await _get_hod_dept_id(client, headers=h)
    term = await _ensure_term(client, headers=a)
    setup = (
        await client.post(
            "/workflow/semester-setups",
            headers=h,
            json={"department_id": dept, "academic_term_id": term},
        )
    ).json()
    course_id, section_id = await _make_course_and_section(
        client, headers=a, dept_id=dept
    )
    teacher_id = await _make_teacher(client, headers=a)

    r1 = await client.post(
        f"/workflow/semester-setups/{setup['id']}/courses",
        headers=h,
        json={
            "course_id": course_id,
            "section_id": section_id,
            "teacher_user_id": teacher_id,
        },
    )
    assert r1.status_code == 201, r1.text
    first_offering = r1.json()["id"]
    first_scheme = r1.json()["assessment_scheme_id"]
    assert first_scheme is not None

    # Patching the offering must not touch the scheme link.
    second_teacher = await _make_teacher(client, headers=a)
    p = await client.patch(
        f"/workflow/semester-setups/{setup['id']}/courses/{first_offering}",
        headers=h,
        json={"teacher_user_id": second_teacher},
    )
    assert p.status_code == 200, p.text
    assert p.json()["assessment_scheme_id"] == first_scheme

    # And there must be exactly one active scheme row for this offering.
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(AssessmentScheme).where(
                    AssessmentScheme.course_offering_id == first_offering,
                    AssessmentScheme.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(rows) == 1


# ── Event payload shape (independent of router) ────────────────────────────
@pytest.mark.asyncio
async def test_event_payload_shape_matches_ai_deferral():
    """build_event_payload is the contract M5/M7/M8 will subscribe to.
    Any unintended drift in keys should fail loudly here.
    """
    from uuid import uuid4

    from app.core.event_bus import build_event_payload

    college_id = uuid4()
    actor = uuid4()
    payload = build_event_payload(
        "semester_setup.published",
        {
            "semester_setup_id": str(uuid4()),
            "department_id": str(uuid4()),
            "academic_term_id": str(uuid4()),
            "published_at": "2026-05-15T00:00:00+00:00",
        },
        college_id=college_id,
        actor_user_id=actor,
    )
    assert set(payload.keys()) == {
        "event",
        "version",
        "occurred_at",
        "college_id",
        "actor_user_id",
        "data",
    }
    assert payload["event"] == "semester_setup.published"
    assert payload["version"] == 1
    assert payload["college_id"] == str(college_id)
    assert payload["actor_user_id"] == str(actor)
    assert set(payload["data"].keys()) == {
        "semester_setup_id",
        "department_id",
        "academic_term_id",
        "published_at",
    }
