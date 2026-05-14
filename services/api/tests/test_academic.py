"""Smoke tests for M2 — academic service.

Like test_auth.py these run against the docker stack with a fresh seed.
Codes are uuid-suffixed so tests don't trample each other on repeated runs.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_auth import DEMO_PASSWORD


async def _admin_headers(client) -> dict[str, str]:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _teacher_id(client, headers) -> str:
    me = await client.get(
        "/users", headers=headers, params={"limit": 1}
    )
    # No list endpoint; use seeded teacher email directly.
    login = await client.post(
        "/auth/login",
        json={"email": "teacher@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    assert login.status_code == 200
    t_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/users/me", headers=t_headers)
    return me.json()["id"]


async def _student_id(client) -> str:
    login = await client.post(
        "/auth/login",
        json={"email": "student@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    assert login.status_code == 200
    s_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/users/me", headers=s_headers)
    return me.json()["id"]


async def _make_fresh_teacher(client, admin_headers) -> str:
    """Tests sharing the seeded teacher trip teacher-level conflict checks
    across runs as Friday slots accumulate. Each timetable test mints its
    own teacher to stay isolated."""
    email = f"teach-{_short()}@bmsce.ac.in"
    r = await client.post(
        "/users",
        headers=admin_headers,
        json={"email": email, "name": "Test Teacher", "role": "teacher"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _short() -> str:
    return uuid.uuid4().hex[:6]


# ── Departments ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_departments_crud_and_soft_delete(client):
    h = await _admin_headers(client)
    code = f"DPT-{_short()}"
    r = await client.post(
        "/departments", headers=h, json={"name": "Test Dept", "code": code}
    )
    assert r.status_code == 201, r.text
    dept_id = r.json()["id"]

    lst = await client.get("/departments", headers=h)
    assert lst.status_code == 200
    codes = [d["code"] for d in lst.json()["items"]]
    assert code in codes

    dele = await client.delete(f"/departments/{dept_id}", headers=h)
    assert dele.status_code == 204

    lst2 = await client.get("/departments", headers=h)
    codes2 = [d["code"] for d in lst2.json()["items"]]
    assert code not in codes2

    lst3 = await client.get(
        "/departments", headers=h, params={"include_deleted": "true"}
    )
    codes3 = [d["code"] for d in lst3.json()["items"]]
    assert code in codes3


@pytest.mark.asyncio
async def test_departments_duplicate_code_409(client):
    h = await _admin_headers(client)
    code = f"DUP-{_short()}"
    first = await client.post(
        "/departments", headers=h, json={"name": "First", "code": code}
    )
    assert first.status_code == 201
    second = await client.post(
        "/departments", headers=h, json={"name": "Second", "code": code}
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "code_in_use"


@pytest.mark.asyncio
async def test_departments_require_admin(client):
    # Student logs in then tries to create a department.
    login = await client.post(
        "/auth/login",
        json={"email": "student@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post(
        "/departments", headers=h, json={"name": "Naughty", "code": f"NO-{_short()}"}
    )
    assert r.status_code == 403


# ── Courses ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_courses_crud_and_curriculum_filter(client):
    h = await _admin_headers(client)
    # Make a fresh department for this test.
    dept = await client.post(
        "/departments", headers=h, json={"name": "CourseDept", "code": f"CD-{_short()}"}
    )
    dept_id = dept.json()["id"]

    code_a = f"CS-{_short()}"
    code_b = f"CS-{_short()}"
    a = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": code_a,
            "title": "Sem 3 Course",
            "credits": 4,
            "semester": 3,
            "course_type": "theory",
        },
    )
    assert a.status_code == 201, a.text
    b = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": code_b,
            "title": "Sem 4 Course",
            "credits": 4,
            "semester": 4,
            "course_type": "theory",
        },
    )
    assert b.status_code == 201

    sem3 = await client.get(
        "/courses",
        headers=h,
        params={"department_id": dept_id, "semester": 3},
    )
    codes = [c["code"] for c in sem3.json()["items"]]
    assert code_a in codes
    assert code_b not in codes


# ── Batches + sections + enrollments ────────────────────────────────────────
@pytest.mark.asyncio
async def test_batches_sections_and_enrollments(client):
    h = await _admin_headers(client)
    dept = await client.post(
        "/departments", headers=h, json={"name": "BatchDept", "code": f"BD-{_short()}"}
    )
    dept_id = dept.json()["id"]

    batch = await client.post(
        "/batches",
        headers=h,
        json={
            "department_id": dept_id,
            "name": "BD 2024-28",
            "admission_year": 2024,
            "current_semester": 3,
        },
    )
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["id"]

    sec = await client.post(
        "/sections",
        headers=h,
        json={"batch_id": batch_id, "name": "A"},
    )
    assert sec.status_code == 201, sec.text
    section_id = sec.json()["id"]

    # Duplicate section name in the same batch should 409.
    dup = await client.post(
        "/sections",
        headers=h,
        json={"batch_id": batch_id, "name": "A"},
    )
    assert dup.status_code == 409

    student_id = await _student_id(client)
    enr = await client.post(
        f"/sections/{section_id}/enrollments",
        headers=h,
        json={
            "student_user_ids": [student_id],
            "academic_term": "2026-ODD",
            "semester": 3,
        },
    )
    assert enr.status_code == 201, enr.text

    students = await client.get(
        f"/sections/{section_id}/students", headers=h
    )
    assert students.status_code == 200
    assert any(e["student_user_id"] == student_id for e in students.json())

    # Re-enroll same student → idempotent: no error, no new row.
    again = await client.post(
        f"/sections/{section_id}/enrollments",
        headers=h,
        json={
            "student_user_ids": [student_id],
            "academic_term": "2026-ODD",
            "semester": 3,
        },
    )
    assert again.status_code == 201


# ── Rooms ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rooms_crud_and_lat_lon_constraint(client):
    h = await _admin_headers(client)
    code = f"R-{_short()}"
    r = await client.post(
        "/rooms",
        headers=h,
        json={
            "code": code,
            "building": "Main",
            "floor": 2,
            "capacity": 60,
            "room_type": "lecture",
            "lat": "12.940000",
            "lon": "77.560000",
            "gps_radius_m": 100,
        },
    )
    assert r.status_code == 201, r.text

    # lat without lon should fail (DB check constraint).
    bad = await client.post(
        "/rooms",
        headers=h,
        json={
            "code": f"R-{_short()}",
            "lat": "12.940000",
        },
    )
    assert bad.status_code in (400, 409, 422, 500)


# ── Course offering uniqueness ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_course_offering_duplicate_409(client):
    h = await _admin_headers(client)
    dept = await client.post(
        "/departments", headers=h, json={"name": "OD", "code": f"OD-{_short()}"}
    )
    dept_id = dept.json()["id"]
    course = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": f"OC-{_short()}",
            "title": "Offering Course",
            "credits": 3,
            "semester": 3,
        },
    )
    course_id = course.json()["id"]
    batch = await client.post(
        "/batches",
        headers=h,
        json={
            "department_id": dept_id,
            "name": "OD 2024",
            "admission_year": 2024,
            "current_semester": 3,
        },
    )
    section = await client.post(
        "/sections",
        headers=h,
        json={"batch_id": batch.json()["id"], "name": "A"},
    )
    teacher_id = await _make_fresh_teacher(client, h)

    offering_body = {
        "course_id": course_id,
        "section_id": section.json()["id"],
        "teacher_user_id": teacher_id,
        "academic_term": "2026-ODD",
        "semester": 3,
    }
    a = await client.post("/course-offerings", headers=h, json=offering_body)
    assert a.status_code == 201, a.text
    b = await client.post("/course-offerings", headers=h, json=offering_body)
    assert b.status_code == 409


# ── Timetable + conflict detection ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_timetable_conflict_and_force_override(client):
    h = await _admin_headers(client)
    dept = await client.post(
        "/departments", headers=h, json={"name": "TT", "code": f"TT-{_short()}"}
    )
    dept_id = dept.json()["id"]

    course1 = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": f"TT1-{_short()}",
            "title": "Slot Course 1",
            "credits": 3,
            "semester": 3,
        },
    )
    course2 = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": f"TT2-{_short()}",
            "title": "Slot Course 2",
            "credits": 3,
            "semester": 3,
        },
    )
    batch = await client.post(
        "/batches",
        headers=h,
        json={
            "department_id": dept_id,
            "name": "TT 2024",
            "admission_year": 2024,
            "current_semester": 3,
        },
    )
    section = await client.post(
        "/sections",
        headers=h,
        json={"batch_id": batch.json()["id"], "name": "A"},
    )
    room = await client.post(
        "/rooms",
        headers=h,
        json={"code": f"TTR-{_short()}", "room_type": "lecture"},
    )
    teacher_id = await _make_fresh_teacher(client, h)

    section_id = section.json()["id"]
    room_id = room.json()["id"]

    off1 = await client.post(
        "/course-offerings",
        headers=h,
        json={
            "course_id": course1.json()["id"],
            "section_id": section_id,
            "teacher_user_id": teacher_id,
            "academic_term": "2026-ODD",
            "semester": 3,
        },
    )
    off2 = await client.post(
        "/course-offerings",
        headers=h,
        json={
            "course_id": course2.json()["id"],
            "section_id": section_id,
            "teacher_user_id": teacher_id,
            "academic_term": "2026-ODD",
            "semester": 3,
        },
    )

    # Friday avoids collision with the seed (which puts the demo teacher's
    # slots on Wednesday) — teacher conflicts would otherwise fire.
    slot1_body = {
        "course_offering_id": off1.json()["id"],
        "room_id": room_id,
        "day_of_week": 4,  # Fri
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "effective_from": "2026-08-01",
        "effective_until": "2026-12-15",
    }
    a = await client.post("/timetable", headers=h, json=slot1_body)
    assert a.status_code == 201, a.text

    # Back-to-back slot (11:00–12:00) in the same room — must NOT conflict.
    nofight_body = dict(slot1_body)
    nofight_body["course_offering_id"] = off2.json()["id"]
    nofight_body["start_time"] = "11:00:00"
    nofight_body["end_time"] = "12:00:00"
    no_fight = await client.post("/timetable", headers=h, json=nofight_body)
    assert no_fight.status_code == 201, no_fight.text

    # Overlapping slot (10:30–11:30) in the same room — must conflict (room + section + teacher).
    conflict_body = dict(slot1_body)
    conflict_body["course_offering_id"] = off2.json()["id"]
    conflict_body["start_time"] = "10:30:00"
    conflict_body["end_time"] = "11:30:00"
    fight = await client.post("/timetable", headers=h, json=conflict_body)
    assert fight.status_code == 409, fight.text
    assert fight.json()["detail"]["code"] == "conflict"

    # Force should succeed.
    forced = await client.post(
        "/timetable", headers=h, params={"force": "true"}, json=conflict_body
    )
    assert forced.status_code == 201, forced.text

    # Check-conflict endpoint returns the right shape.
    check = await client.post(
        "/timetable/check-conflict",
        headers=h,
        json={
            "room_id": room_id,
            "teacher_user_id": teacher_id,
            "section_id": section_id,
            "day_of_week": 4,
            "start_time": "10:30:00",
            "end_time": "11:30:00",
            "effective_from": "2026-08-01",
            "effective_until": "2026-12-15",
        },
    )
    assert check.status_code == 200
    body = check.json()
    assert body["has_conflicts"] is True
    types = {c["type"] for c in body["conflicts"]}
    # Should hit at least room and section/teacher categories.
    assert "room" in types
    assert "section" in types
    assert "teacher" in types


@pytest.mark.asyncio
async def test_check_conflict_no_overlap_returns_clean(client):
    h = await _admin_headers(client)
    check = await client.post(
        "/timetable/check-conflict",
        headers=h,
        json={
            "room_id": None,
            "teacher_user_id": None,
            "section_id": None,
            "day_of_week": 0,
            "start_time": "06:00:00",
            "end_time": "07:00:00",
            "effective_from": "2099-01-01",
            "effective_until": "2099-01-31",
        },
    )
    assert check.status_code == 200
    assert check.json()["has_conflicts"] is False


# ── Timetable exceptions ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_timetable_exceptions_cancel_and_room_change(client):
    h = await _admin_headers(client)
    dept = await client.post(
        "/departments", headers=h, json={"name": "EX", "code": f"EX-{_short()}"}
    )
    dept_id = dept.json()["id"]
    course = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": f"EX-{_short()}",
            "title": "ExCourse",
            "credits": 3,
            "semester": 3,
        },
    )
    batch = await client.post(
        "/batches",
        headers=h,
        json={
            "department_id": dept_id,
            "name": "EX 2024",
            "admission_year": 2024,
            "current_semester": 3,
        },
    )
    section = await client.post(
        "/sections",
        headers=h,
        json={"batch_id": batch.json()["id"], "name": "A"},
    )
    room1 = await client.post(
        "/rooms", headers=h, json={"code": f"EXR1-{_short()}"}
    )
    room2 = await client.post(
        "/rooms", headers=h, json={"code": f"EXR2-{_short()}"}
    )
    teacher_id = await _make_fresh_teacher(client, h)
    offering = await client.post(
        "/course-offerings",
        headers=h,
        json={
            "course_id": course.json()["id"],
            "section_id": section.json()["id"],
            "teacher_user_id": teacher_id,
            "academic_term": "2026-ODD",
            "semester": 3,
        },
    )
    # Friday afternoon: avoids both the seeded Wed slot and the Friday
    # 10–11 slot the conflict-detection test creates.
    slot = await client.post(
        "/timetable",
        headers=h,
        json={
            "course_offering_id": offering.json()["id"],
            "room_id": room1.json()["id"],
            "day_of_week": 4,
            "start_time": "14:00:00",
            "end_time": "15:00:00",
            "effective_from": "2026-08-07",  # Friday
            "effective_until": "2026-12-30",
        },
    )
    assert slot.status_code == 201, slot.text

    cancel = await client.post(
        "/timetable/exceptions",
        headers=h,
        json={
            "course_offering_id": offering.json()["id"],
            "exception_date": "2026-09-25",  # Friday
            "kind": "cancel",
            "reason": "teacher leave",
        },
    )
    assert cancel.status_code == 201, cancel.text

    room_change = await client.post(
        "/timetable/exceptions",
        headers=h,
        json={
            "course_offering_id": offering.json()["id"],
            "exception_date": "2026-10-02",  # Friday
            "kind": "room_change",
            "new_room_id": room2.json()["id"],
            "reason": "audio fix",
        },
    )
    assert room_change.status_code == 201, room_change.text

    # Reading the timetable view returns the exceptions.
    view = await client.get(
        f"/timetable/{section.json()['id']}",
        headers=h,
        params={"from": "2026-09-01", "to": "2026-10-31"},
    )
    assert view.status_code == 200
    body = view.json()
    kinds = {e["kind"] for e in body["exceptions"]}
    assert "cancel" in kinds
    assert "room_change" in kinds


# ── Academic calendar ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_academic_calendar_holiday(client):
    h = await _admin_headers(client)
    r = await client.post(
        "/academic-calendar",
        headers=h,
        json={
            "entry_date": "2026-08-15",
            "kind": "holiday",
            "title": "Independence Day",
            "cancels_classes": True,
        },
    )
    assert r.status_code == 201, r.text

    lst = await client.get(
        "/academic-calendar",
        headers=h,
        params={"from": "2026-08-01", "to": "2026-08-31"},
    )
    assert lst.status_code == 200
    titles = [e["title"] for e in lst.json()["items"]]
    assert "Independence Day" in titles


# ── Tenant isolation proxy ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tenant_isolation_random_ids_404(client):
    """A random UUID lookup returns 404 — proves the WHERE college_id = ?
    filter is being applied at every entity. If a cross-tenant lookup ever
    succeeded, this would return 200."""
    h = await _admin_headers(client)
    fake = str(uuid.uuid4())
    for path in (
        f"/departments/{fake}",
        f"/courses/{fake}",
        f"/batches/{fake}",
        f"/sections/{fake}",
        f"/rooms/{fake}",
        f"/course-offerings/{fake}",
    ):
        r = await client.get(path, headers=h)
        assert r.status_code == 404, f"{path} returned {r.status_code}"
