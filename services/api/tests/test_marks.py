"""Smoke tests for M4 — marks service.

Mirrors test_academic.py / test_attendance.py: hits Postgres + Redis live,
codes are UUID-suffixed so reruns don't collide. Each top-level test sets
up its own offering + enrolled students to stay isolated.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from tests.test_auth import DEMO_PASSWORD


# ── Auth helpers ────────────────────────────────────────────────────────────
async def _admin_headers(client) -> dict[str, str]:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _login_headers(client, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _short() -> str:
    return uuid.uuid4().hex[:6]


def _fresh_usn() -> str:
    """Mint a BMSCE-pattern USN unique across reruns of the suite.

    The USN format CHECK in migration 0009 enforces 1BM+YY+DD+RRR; the
    pre-rework seed value `USN-<suffix>-<idx>` no longer satisfies it.
    676×1000 = 676k slots in the AA..ZZ × 000..999 space — far more than
    a long-running test database will ever exhaust.
    """
    u = uuid.uuid4().bytes
    a = chr(ord("A") + (u[0] % 26))
    b = chr(ord("A") + (u[1] % 26))
    n = (u[2] * 256 + u[3]) % 1000
    return f"1BM99{a}{b}{n:03d}"


class _MarksSetup:
    def __init__(
        self,
        admin_headers: dict[str, str],
        teacher_headers: dict[str, str],
        student_headers: dict[str, str],
        teacher_id: str,
        seeded_student_id: str,
        section_id: str,
        offering_id: str,
        extra_student_ids: list[str],
        extra_student_uids: list[str],
        academic_term: str,
        slot_id: str,
    ) -> None:
        self.admin_headers = admin_headers
        self.teacher_headers = teacher_headers
        self.student_headers = student_headers
        self.teacher_id = teacher_id
        self.seeded_student_id = seeded_student_id
        self.section_id = section_id
        self.offering_id = offering_id
        self.extra_student_ids = extra_student_ids
        self.extra_student_uids = extra_student_uids
        self.academic_term = academic_term
        self.slot_id = slot_id


async def _build_marks_setup(client, *, extra_students: int = 2) -> _MarksSetup:
    """Self-contained marks fixture: a fresh dept/course/offering plus the
    seeded student enrolled + `extra_students` fresh students enrolled.

    The seeded teacher is the offering owner so the seeded teacher login can
    act as the writing teacher. force=true on the slot insert per the
    test-isolation memory note.
    """
    suffix = _short()
    admin_h = await _admin_headers(client)

    # Seeded teacher login (the offering owner — the writing teacher).
    teacher_h = await _login_headers(client, "teacher@bmsce.ac.in", DEMO_PASSWORD)
    me_t = await client.get("/users/me", headers=teacher_h)
    teacher_id = me_t.json()["id"]

    # Seeded student login (one of the enrolled students for self-history tests).
    student_h = await _login_headers(client, "student@bmsce.ac.in", DEMO_PASSWORD)
    me_s = await client.get("/users/me", headers=student_h)
    seeded_student_id = me_s.json()["id"]

    # Dept / batch / section / room / course.
    dept = await client.post(
        "/departments",
        headers=admin_h,
        json={"name": f"MK-{suffix}", "code": f"MK-{suffix}"},
    )
    dept_id = dept.json()["id"]
    batch = await client.post(
        "/batches",
        headers=admin_h,
        json={
            "department_id": dept_id,
            "name": f"MK {suffix}",
            "admission_year": 2024,
            "current_semester": 3,
        },
    )
    section = await client.post(
        "/sections",
        headers=admin_h,
        json={"batch_id": batch.json()["id"], "name": "A"},
    )
    section_id = section.json()["id"]

    course = await client.post(
        "/courses",
        headers=admin_h,
        json={
            "department_id": dept_id,
            "code": f"MK-{suffix}",
            "title": "Marks Course",
            "credits": 3,
            "semester": 3,
        },
    )
    term = f"MK-{suffix}"
    offering = await client.post(
        "/course-offerings",
        headers=admin_h,
        json={
            "course_id": course.json()["id"],
            "section_id": section_id,
            "teacher_user_id": teacher_id,
            "academic_term": term,
            "semester": 3,
        },
    )
    offering_id = offering.json()["id"]

    # Fresh students with USNs for CSV testing.
    extra_ids: list[str] = []
    extra_uids: list[str] = []
    for i in range(extra_students):
        uid = _fresh_usn()
        r = await client.post(
            "/users",
            headers=admin_h,
            json={
                "email": f"stud-{suffix}-{i}@bmsce.ac.in",
                "name": f"Test Student {i}",
                "role": "student",
                "usn": uid,
            },
        )
        assert r.status_code == 201, r.text
        extra_ids.append(r.json()["id"])
        extra_uids.append(uid)

    # Enroll all students (seeded + extras) into the section.
    enrol = await client.post(
        f"/sections/{section_id}/enrollments",
        headers=admin_h,
        json={
            "student_user_ids": [seeded_student_id, *extra_ids],
            "academic_term": term,
            "semester": 3,
        },
    )
    assert enrol.status_code == 201, enrol.text

    # Add a timetable slot for tomorrow's weekday so the offering is "real".
    target = date.today() + timedelta(days=1)
    # Pick a room from the seed (any one will do).
    rooms = await client.get("/rooms", headers=admin_h)
    room_id = rooms.json()["items"][0]["id"]
    # Offset the start_time by 5 minutes per setup to avoid teacher conflicts.
    minute = (int(suffix, 16) % 50)  # 0..49
    start = f"14:{minute:02d}:00"
    end_min = minute + 5
    end = f"14:{end_min:02d}:00"
    slot = await client.post(
        "/timetable?force=true",
        headers=admin_h,
        json={
            "course_offering_id": offering_id,
            "room_id": room_id,
            "day_of_week": target.weekday(),
            "start_time": start,
            "end_time": end,
            "effective_from": target.isoformat(),
            "effective_until": (target + timedelta(days=21)).isoformat(),
        },
    )
    assert slot.status_code == 201, slot.text

    return _MarksSetup(
        admin_headers=admin_h,
        teacher_headers=teacher_h,
        student_headers=student_h,
        teacher_id=teacher_id,
        seeded_student_id=seeded_student_id,
        section_id=section_id,
        offering_id=offering_id,
        extra_student_ids=extra_ids,
        extra_student_uids=extra_uids,
        academic_term=term,
        slot_id=slot.json()["id"],
    )


async def _make_assessment(
    client,
    headers: dict[str, str],
    offering_id: str,
    *,
    type_: str = "cie1",
    max_marks: float = 30,
    name: str | None = None,
) -> dict:
    name = name or f"CIE1 {_short()}"
    r = await client.post(
        "/assessments",
        headers=headers,
        json={
            "course_offering_id": offering_id,
            "type": type_,
            "name": name,
            "max_marks": str(max_marks),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Assessment CRUD ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_assessment_201_and_list(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    assert a["state"] == "draft"
    lst = await client.get(
        "/assessments",
        headers=s.admin_headers,
        params={"course_offering_id": s.offering_id},
    )
    assert lst.status_code == 200
    assert a["id"] in [x["id"] for x in lst.json()["items"]]


@pytest.mark.asyncio
async def test_create_assessment_non_owner_teacher_403(client):
    s = await _build_marks_setup(client)
    # Make a fresh teacher account (we can't log in as them — invited users
    # have no password) so instead exercise: a student tries to create.
    login = await client.post(
        "/auth/login",
        json={"email": "student@bmsce.ac.in", "password": DEMO_PASSWORD},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post(
        "/assessments",
        headers=h,
        json={
            "course_offering_id": s.offering_id,
            "type": "cie1",
            "name": "Naughty",
            "max_marks": "30",
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_assessment_while_draft_ok(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    r = await client.patch(
        f"/assessments/{a['id']}",
        headers=s.admin_headers,
        json={"max_marks": "40"},
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["max_marks"]) == 40


@pytest.mark.asyncio
async def test_delete_assessment_with_marks_rejected(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    # Enter a mark.
    mr = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.admin_headers,
        json={"marks_obtained": "20", "is_absent": False},
    )
    assert mr.status_code == 200, mr.text
    # Try to delete.
    d = await client.delete(
        f"/assessments/{a['id']}", headers=s.admin_headers
    )
    assert d.status_code == 409
    assert d.json()["detail"]["code"] == "has_marks"


@pytest.mark.asyncio
async def test_lock_assessment_freezes_child_marks(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    # Enter two marks.
    await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.admin_headers,
        json={"marks_obtained": "20", "is_absent": False},
    )
    await client.put(
        f"/marks/{a['id']}/{s.extra_student_ids[0]}",
        headers=s.admin_headers,
        json={"marks_obtained": "25", "is_absent": False},
    )
    # Lock.
    r = await client.patch(
        f"/assessments/{a['id']}/lock",
        headers=s.admin_headers,
        json={"lock": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "locked"
    # Try to update a mark — should 409 for teacher.
    bad = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "30", "is_absent": False},
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "locked"


@pytest.mark.asyncio
async def test_unlock_requires_admin_and_reason(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    await client.patch(
        f"/assessments/{a['id']}/lock",
        headers=s.admin_headers,
        json={"lock": True},
    )
    # Teacher tries to unlock.
    bad_role = await client.patch(
        f"/assessments/{a['id']}/lock",
        headers=s.teacher_headers,
        json={"lock": False, "reason": "fix"},
    )
    assert bad_role.status_code == 403
    # Admin without reason.
    bad_reason = await client.patch(
        f"/assessments/{a['id']}/lock",
        headers=s.admin_headers,
        json={"lock": False},
    )
    assert bad_reason.status_code == 400
    assert bad_reason.json()["detail"]["code"] == "reason_required"
    # Admin with reason.
    ok = await client.patch(
        f"/assessments/{a['id']}/lock",
        headers=s.admin_headers,
        json={"lock": False, "reason": "data entry error"},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "draft"


# ── Single mark entry ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_set_single_mark_happy_path(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    r = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "27", "is_absent": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert float(body["marks_obtained"]) == 27
    assert body["is_absent"] is False
    assert body["state"] == "entered"


@pytest.mark.asyncio
async def test_set_single_mark_above_max(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    r = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "999", "is_absent": False},
    )
    # Pydantic rejects 999 because Field(le=1000) on MarkEntry allows it.
    # But service compares to max_marks (30) → 409.
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "above_max_marks"


@pytest.mark.asyncio
async def test_set_single_mark_non_enrolled_student_403(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    # Create a student NOT enrolled in this offering.
    other = await client.post(
        "/users",
        headers=s.admin_headers,
        json={
            "email": f"other-{_short()}@bmsce.ac.in",
            "name": "Outsider",
            "role": "student",
            "usn": _fresh_usn(),
        },
    )
    other_id = other.json()["id"]
    r = await client.put(
        f"/marks/{a['id']}/{other_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "20", "is_absent": False},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "not_enrolled"


# ── Bulk CSV ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bulk_csv_best_effort(client):
    s = await _build_marks_setup(client, extra_students=3)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # 5 rows: 3 valid (the 3 extra students), 1 unknown UID, 1 above-max.
    csv_lines = ["student_uid,marks_obtained,is_absent"]
    for uid_ in s.extra_student_uids[:3]:
        csv_lines.append(f"{uid_},25,false")
    csv_lines.append(f"NOPE-{_short()},20,false")  # unknown
    csv_lines.append(f"{s.extra_student_uids[0]},999,false")  # above-max
    # The dup of extra_student_uids[0] is fine; first commit will write a
    # mark, the second row above-max errors → committed=3, errors=2.
    csv_data = "\n".join(csv_lines).encode("utf-8")
    files = {"file": ("marks.csv", csv_data, "text/csv")}
    data = {"assessment_id": a["id"], "dry_run": "false"}
    r = await client.put(
        "/marks/bulk", headers=s.teacher_headers, files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] == 3
    assert len(body["errors"]) == 2
    codes = sorted(e["code"] for e in body["errors"])
    assert codes == sorted(["unknown_student", "above_max_marks"])


@pytest.mark.asyncio
async def test_bulk_csv_dry_run_commits_nothing(client):
    s = await _build_marks_setup(client, extra_students=2)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    csv_lines = ["student_uid,marks_obtained,is_absent"]
    for uid_ in s.extra_student_uids:
        csv_lines.append(f"{uid_},22,false")
    csv_data = "\n".join(csv_lines).encode("utf-8")
    files = {"file": ("marks.csv", csv_data, "text/csv")}
    data = {"assessment_id": a["id"], "dry_run": "true"}
    r = await client.put(
        "/marks/bulk", headers=s.teacher_headers, files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] == 2
    assert body["errors"] == []
    assert body["dry_run"] is True
    # Verify nothing was actually written.
    stats = await client.get(
        f"/assessments/{a['id']}/stats", headers=s.teacher_headers
    )
    assert stats.json()["count"] == 0


# ── Stats ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_assessment_stats_computed(client):
    s = await _build_marks_setup(client, extra_students=3)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # 4 marks: 20, 25, 30, and one absent.
    values = [
        (s.seeded_student_id, 20, False),
        (s.extra_student_ids[0], 25, False),
        (s.extra_student_ids[1], 30, False),
        (s.extra_student_ids[2], None, True),
    ]
    for uid_, marks, absent in values:
        body = (
            {"is_absent": True}
            if absent
            else {"marks_obtained": str(marks), "is_absent": False}
        )
        r = await client.put(
            f"/marks/{a['id']}/{uid_}",
            headers=s.teacher_headers,
            json=body,
        )
        assert r.status_code == 200, r.text
    stats = await client.get(
        f"/assessments/{a['id']}/stats", headers=s.teacher_headers
    )
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["count"] == 4
    assert body["absent_count"] == 1
    assert body["mean"] == 25  # mean of 20, 25, 30
    assert body["median"] == 25


# ── Student history ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_student_history_self_only(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "22", "is_absent": False},
    )
    # Student fetches own.
    own = await client.get(
        f"/marks/{s.seeded_student_id}/history", headers=s.student_headers
    )
    assert own.status_code == 200, own.text
    items = own.json()["items"]
    assert any(item["assessment"]["id"] == a["id"] for item in items)
    # Student tries to fetch someone else's.
    bad = await client.get(
        f"/marks/{s.extra_student_ids[0]}/history", headers=s.student_headers
    )
    assert bad.status_code == 403


# ── Grade rules ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_grade_rules_must_sum_to_100(client):
    s = await _build_marks_setup(client)
    rules_ok = {
        "course_offering_id": s.offering_id,
        "rules": [
            {"assessment_type": "cie1", "weight_percent": "40"},
            {"assessment_type": "cie2", "weight_percent": "30"},
            {"assessment_type": "see", "weight_percent": "30"},
        ],
    }
    r = await client.put(
        "/grade-rules", headers=s.teacher_headers, json=rules_ok
    )
    assert r.status_code == 200, r.text
    # Now a bad set summing to 90.
    rules_bad = {
        "course_offering_id": s.offering_id,
        "rules": [
            {"assessment_type": "cie1", "weight_percent": "40"},
            {"assessment_type": "cie2", "weight_percent": "30"},
            {"assessment_type": "see", "weight_percent": "20"},
        ],
    }
    bad = await client.put(
        "/grade-rules", headers=s.teacher_headers, json=rules_bad
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "weights_sum"


@pytest.mark.asyncio
async def test_grade_rules_default_when_none_set(client):
    s = await _build_marks_setup(client)
    r = await client.get(
        "/grade-rules",
        headers=s.teacher_headers,
        params={"course_offering_id": s.offering_id},
    )
    assert r.status_code == 200, r.text
    rules = r.json()["rules"]
    types = [x["assessment_type"] for x in rules]
    assert types == ["cie1", "cie2", "cie3", "see", "assignment", "lab"]
    total = sum(float(x["weight_percent"]) for x in rules)
    assert total == 100


# ── Parent / guardian ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_parent_link_and_view(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # Enter a mark for the seeded student.
    await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "27", "is_absent": False},
    )
    # Admin creates the parent link with a brand-new parent email.
    parent_email = f"parent-{_short()}@bmsce.ac.in"
    link_resp = await client.post(
        "/admin/guardian-links",
        headers=s.admin_headers,
        json={
            "parent_email": parent_email,
            "parent_name": "Test Parent",
            "student_user_id": s.seeded_student_id,
            "relationship": "father",
        },
    )
    assert link_resp.status_code == 201, link_resp.text
    body = link_resp.json()
    assert body["link"]["verified_at"] is not None
    parent_pw = body["parent_initial_password"]
    # Login as the parent and fetch /parent/marks.
    parent_h = await _login_headers(client, parent_email, parent_pw)
    children = await client.get("/parent/children", headers=parent_h)
    assert children.status_code == 200
    assert len(children.json()) == 1
    assert children.json()[0]["id"] == s.seeded_student_id
    pmv = await client.get("/parent/marks", headers=parent_h)
    assert pmv.status_code == 200, pmv.text
    pmv_body = pmv.json()
    assert len(pmv_body["children"]) == 1
    child = pmv_body["children"][0]
    assert child["student"]["id"] == s.seeded_student_id
    # Should have the assessment with the mark.
    items = child["history"]["items"]
    assert any(
        item["assessment"]["id"] == a["id"]
        and item["mark"] is not None
        and float(item["mark"]["marks_obtained"]) == 27
        for item in items
    )
    # The parent must NOT see another student's history directly.
    other_id = s.extra_student_ids[0]
    forbidden = await client.get(
        f"/marks/{other_id}/history", headers=parent_h
    )
    assert forbidden.status_code == 403


# ── Mark audit ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_marks_audit_endpoint(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # Enter, then update.
    r1 = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "20", "is_absent": False},
    )
    assert r1.status_code == 200, r1.text
    mark_id = r1.json()["id"]
    r2 = await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "22", "is_absent": False},
    )
    assert r2.status_code == 200, r2.text
    # Fetch audit.
    audit = await client.get(
        f"/marks/{mark_id}/audit", headers=s.teacher_headers
    )
    assert audit.status_code == 200, audit.text
    rows = audit.json()
    assert len(rows) == 2
    assert rows[0]["action"] == "mark.create"
    assert rows[1]["action"] == "mark.update"
    assert float(rows[1]["old_value"]["marks_obtained"]) == 20
    assert float(rows[1]["new_value"]["marks_obtained"]) == 22


# ── Tenant isolation ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_assessment_for_other_offering_not_found(client):
    s = await _build_marks_setup(client)
    a = await _make_assessment(client, s.admin_headers, s.offering_id)
    # Make a totally unrelated offering (same college, different teacher
    # already covered indirectly). Here we just confirm 404 for unknown UUID.
    bogus = uuid.uuid4()
    r = await client.get(
        f"/assessments/{bogus}", headers=s.admin_headers
    )
    assert r.status_code == 404


# ── Default grade-rules across types ────────────────────────────────────────
@pytest.mark.asyncio
async def test_assessment_create_unknown_offering_400(client):
    s = await _build_marks_setup(client)
    r = await client.post(
        "/assessments",
        headers=s.admin_headers,
        json={
            "course_offering_id": str(uuid.uuid4()),
            "type": "cie1",
            "name": "Bogus",
            "max_marks": "30",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bad_offering"


@pytest.mark.asyncio
async def test_duplicate_assessment_name_409(client):
    s = await _build_marks_setup(client)
    name = f"CIE1 dup {_short()}"
    a1 = await _make_assessment(
        client, s.admin_headers, s.offering_id, type_="cie1", name=name
    )
    r = await client.post(
        "/assessments",
        headers=s.admin_headers,
        json={
            "course_offering_id": s.offering_id,
            "type": "cie1",
            "name": name,
            "max_marks": "30",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "name_in_use"
    assert a1["name"] == name


@pytest.mark.asyncio
async def test_assessment_roster_with_marks(client):
    s = await _build_marks_setup(client, extra_students=2)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # Enter a mark for one of the students.
    await client.put(
        f"/marks/{a['id']}/{s.extra_student_ids[0]}",
        headers=s.teacher_headers,
        json={"marks_obtained": "24", "is_absent": False},
    )
    r = await client.get(
        f"/assessments/{a['id']}/roster", headers=s.teacher_headers
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    # 3 enrolled total (seeded + 2 extras).
    assert len(rows) == 3
    by_uid = {row["student_user_id"]: row for row in rows}
    # The marked student has marks_obtained=24.
    assert by_uid[s.extra_student_ids[0]]["marks_obtained"] is not None
    assert float(by_uid[s.extra_student_ids[0]]["marks_obtained"]) == 24
    # The other students have no mark yet.
    assert by_uid[s.seeded_student_id]["mark_id"] is None


@pytest.mark.asyncio
async def test_absent_mark_excludes_from_stats(client):
    s = await _build_marks_setup(client, extra_students=2)
    a = await _make_assessment(client, s.admin_headers, s.offering_id, max_marks=30)
    # 1 numeric (20), 1 absent.
    await client.put(
        f"/marks/{a['id']}/{s.seeded_student_id}",
        headers=s.teacher_headers,
        json={"marks_obtained": "20", "is_absent": False},
    )
    await client.put(
        f"/marks/{a['id']}/{s.extra_student_ids[0]}",
        headers=s.teacher_headers,
        json={"is_absent": True},
    )
    stats = (
        await client.get(
            f"/assessments/{a['id']}/stats", headers=s.teacher_headers
        )
    ).json()
    assert stats["count"] == 2
    assert stats["absent_count"] == 1
    assert stats["mean"] == 20.0
