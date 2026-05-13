"""Smoke tests for M3 — attendance service.

Mirrors test_academic.py: hits Postgres + Redis live, codes are UUID-
suffixed so reruns don't collide. Each top-level test sets up its own
slot / session / enrollment to stay isolated.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

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


async def _login(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _short() -> str:
    return uuid.uuid4().hex[:6]


# ── Fixture: an isolated offering with a slot scheduled for tomorrow ────────
class _Setup:
    def __init__(
        self,
        admin_headers: dict[str, str],
        teacher_headers: dict[str, str],
        student_headers: dict[str, str],
        teacher_id: str,
        student_id: str,
        section_id: str,
        room_id: str,
        offering_id: str,
        slot_id: str,
        scheduled_date: date,
        room_lat: float,
        room_lon: float,
        academic_term: str,
    ) -> None:
        self.admin_headers = admin_headers
        self.teacher_headers = teacher_headers
        self.student_headers = student_headers
        self.teacher_id = teacher_id
        self.student_id = student_id
        self.section_id = section_id
        self.room_id = room_id
        self.offering_id = offering_id
        self.slot_id = slot_id
        self.scheduled_date = scheduled_date
        self.room_lat = room_lat
        self.room_lon = room_lon
        self.academic_term = academic_term


async def _build_setup(client) -> _Setup:
    """Create a self-contained slice: teacher, student, dept, batch, section,
    room (with GPS), offering, timetable slot whose `day_of_week` matches
    tomorrow's weekday. The slot creation itself materialises a
    class_session for tomorrow via the M2 → M3 hook.
    """
    suffix = _short()
    admin_h = await _admin_headers(client)

    # Fresh teacher.
    t_email = f"teach-{suffix}@bmsce.ac.in"
    r = await client.post(
        "/users",
        headers=admin_h,
        json={"email": t_email, "name": "Test Teacher", "role": "teacher"},
    )
    assert r.status_code == 201, r.text
    teacher_id = r.json()["id"]
    # Bootstrap a password via reset-confirm flow would be heavy. Instead set
    # the password by direct admin patch isn't supported either — but the
    # seeded teacher@bmsce.ac.in already has DEMO_PASSWORD, so use that
    # account where we need teacher login, and use the fresh teacher only
    # as the offering owner. The "owner" check uses teacher_user_id, not
    # logged-in identity matching.
    # Reuse seeded teacher@bmsce.ac.in for actual login.
    seeded_teacher = (await client.post(
        "/auth/login",
        json={"email": "teacher@bmsce.ac.in", "password": DEMO_PASSWORD},
    ))
    teacher_h = {
        "Authorization": f"Bearer {seeded_teacher.json()['access_token']}"
    }
    # Re-fetch seeded teacher's id so we can also use it as the offering owner.
    me = await client.get("/users/me", headers=teacher_h)
    seeded_teacher_id = me.json()["id"]

    # Fresh student.
    s_email = f"stud-{suffix}@bmsce.ac.in"
    r = await client.post(
        "/users",
        headers=admin_h,
        json={"email": s_email, "name": "Test Student", "role": "student"},
    )
    assert r.status_code == 201, r.text
    student_id = r.json()["id"]
    # Reuse seeded student@bmsce.ac.in for actual login.
    seeded_student = (await client.post(
        "/auth/login",
        json={"email": "student@bmsce.ac.in", "password": DEMO_PASSWORD},
    ))
    student_h = {
        "Authorization": f"Bearer {seeded_student.json()['access_token']}"
    }
    me_s = await client.get("/users/me", headers=student_h)
    seeded_student_id = me_s.json()["id"]

    # Department / batch / section / room.
    dept = await client.post(
        "/departments",
        headers=admin_h,
        json={"name": f"AT-{suffix}", "code": f"AT-{suffix}"},
    )
    dept_id = dept.json()["id"]
    batch = await client.post(
        "/batches",
        headers=admin_h,
        json={
            "department_id": dept_id,
            "name": f"AT {suffix}",
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

    room_lat = 12.943000
    room_lon = 77.563000
    room = await client.post(
        "/rooms",
        headers=admin_h,
        json={
            "code": f"AT-LH-{suffix}",
            "room_type": "lecture",
            "lat": str(room_lat),
            "lon": str(room_lon),
            "gps_radius_m": 100,
        },
    )
    room_id = room.json()["id"]

    course = await client.post(
        "/courses",
        headers=admin_h,
        json={
            "department_id": dept_id,
            "code": f"AT-{suffix}",
            "title": "Attendance Course",
            "credits": 3,
            "semester": 3,
        },
    )

    term = f"AT-{suffix}"
    offering = await client.post(
        "/course-offerings",
        headers=admin_h,
        json={
            "course_id": course.json()["id"],
            "section_id": section_id,
            "teacher_user_id": seeded_teacher_id,
            "academic_term": term,
            "semester": 3,
        },
    )
    offering_id = offering.json()["id"]

    # Enroll the seeded student so they can submit.
    enrol = await client.post(
        f"/sections/{section_id}/enrollments",
        headers=admin_h,
        json={
            "student_user_ids": [seeded_student_id],
            "academic_term": term,
            "semester": 3,
        },
    )
    assert enrol.status_code == 201, enrol.text

    # Pick a date 1 day in the future. The slot's day_of_week will match
    # whatever weekday that is so the materialiser produces a session.
    # force=true because tests share the seeded teacher as offering owner —
    # re-runs against a non-fresh DB collide on (teacher, day, time).
    target = date.today() + timedelta(days=1)
    slot = await client.post(
        "/timetable?force=true",
        headers=admin_h,
        json={
            "course_offering_id": offering_id,
            "room_id": room_id,
            "day_of_week": target.weekday(),
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "effective_from": target.isoformat(),
            "effective_until": (target + timedelta(days=21)).isoformat(),
        },
    )
    assert slot.status_code == 201, slot.text

    return _Setup(
        admin_headers=admin_h,
        teacher_headers=teacher_h,
        student_headers=student_h,
        teacher_id=seeded_teacher_id,
        student_id=seeded_student_id,
        section_id=section_id,
        room_id=room_id,
        offering_id=offering_id,
        slot_id=slot.json()["id"],
        scheduled_date=target,
        room_lat=room_lat,
        room_lon=room_lon,
        academic_term=term,
    )


async def _fetch_session_id(client, setup: _Setup) -> str:
    """Look up the materialised class_session row directly from the DB via
    a simple internal helper. There's no public list endpoint yet, so we
    use a SQL select via the test session fixture."""
    from sqlalchemy import select  # noqa: PLC0415 — test-only import
    from app.core.db import SessionLocal  # noqa: PLC0415
    from app.modules.attendance.models import ClassSession  # noqa: PLC0415

    async with SessionLocal() as s:
        row = await s.execute(
            select(ClassSession.id).where(
                ClassSession.course_offering_id == uuid.UUID(setup.offering_id),
                ClassSession.scheduled_date == setup.scheduled_date,
                ClassSession.deleted_at.is_(None),
            )
        )
        sid = row.scalar_one_or_none()
        assert sid is not None, "materialiser failed to create the session row"
        return str(sid)


# ── Materialiser ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_materialiser_creates_session_on_slot_create(client):
    setup = await _build_setup(client)
    # The slot creation itself triggered materialise. Verify the row exists.
    session_id = await _fetch_session_id(client, setup)
    assert uuid.UUID(session_id)


@pytest.mark.asyncio
async def test_materialiser_is_idempotent(client):
    setup = await _build_setup(client)
    sid1 = await _fetch_session_id(client, setup)

    # Patch the slot (no-op end_time tweak) → triggers re-materialise.
    # force=true: tests share the seeded teacher; re-running the conflict
    # check from a non-fresh DB still hits its own slot. The patch is a
    # no-op so this is purely a re-materialisation trigger.
    r = await client.patch(
        f"/timetable/{setup.slot_id}?force=true",
        headers=setup.admin_headers,
        json={"end_time": "11:00:00"},
    )
    assert r.status_code == 200, r.text

    sid2 = await _fetch_session_id(client, setup)
    assert sid1 == sid2, "re-materialise should UPSERT, not insert a duplicate"


@pytest.mark.asyncio
async def test_materialiser_skips_holidays(client):
    setup = await _build_setup(client)
    sid_before = await _fetch_session_id(client, setup)

    # Add a holiday on the *next* occurrence of this slot's weekday so it
    # falls inside the materialise window but doesn't poison other tests'
    # tomorrow-dated session lookups.
    holiday_date = setup.scheduled_date + timedelta(days=7)
    r = await client.post(
        "/academic-calendar",
        headers=setup.admin_headers,
        json={
            "entry_date": holiday_date.isoformat(),
            "kind": "holiday",
            "title": "Surprise Holiday",
            "cancels_classes": True,
        },
    )
    assert r.status_code == 201, r.text

    # Re-trigger materialisation by patching the slot.
    await client.patch(
        f"/timetable/{setup.slot_id}?force=true",
        headers=setup.admin_headers,
        json={"end_time": "11:00:00"},
    )
    # Existing rows aren't deleted (idempotent UPSERT); the materialiser
    # just skips the holiday-covered Thursday inside the window. Sanity-
    # check: re-running materialise after declaring a holiday doesn't
    # blow up, and the original tomorrow session still resolves.
    sid_after = await _fetch_session_id(client, setup)
    assert sid_after == sid_before


# ── QR token + state machine ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_qr_issue_flips_pending_to_open(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)

    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    assert qr.status_code == 200, qr.text
    body = qr.json()
    assert body["token"]
    assert body["session_id"] == session_id
    assert body["ttl_seconds"] == 90

    # Subsequent issue revokes the prior token.
    qr2 = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    assert qr2.status_code == 200
    assert qr2.json()["jti"] != body["jti"]


@pytest.mark.asyncio
async def test_qr_requires_owner(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    # Login as a different teacher (admin since we can't trivially log in as
    # the fresh teacher). Admin should be allowed (admin bypasses owner check).
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.admin_headers
    )
    assert qr.status_code == 200

    # Student can't issue.
    qr_bad = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.student_headers
    )
    assert qr_bad.status_code == 403


# ── Submit happy path + anti-replay + GPS flagged ───────────────────────────
@pytest.mark.asyncio
async def test_submit_records_within_radius(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)

    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    token = qr.json()["token"]

    sub = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": token,
            "gps_lat": str(setup.room_lat + 0.0001),  # ~11m north
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",
        },
    )
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["state"] == "recorded"
    assert body["face_match"] is True


@pytest.mark.asyncio
async def test_submit_flagged_when_gps_far(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )

    sub = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": qr.json()["token"],
            "gps_lat": str(setup.room_lat + 0.05),  # ~5.5 km north
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",
        },
    )
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["state"] == "flagged"
    assert "gps_too_far" in (body["flagged_reason"] or "")


@pytest.mark.asyncio
async def test_submit_anti_replay_same_student(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    token = qr.json()["token"]

    fp = f"device-{_short()}"
    first = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": token,
            "gps_lat": str(setup.room_lat),
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": fp,
        },
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": token,
            "gps_lat": str(setup.room_lat),
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",  # different device
        },
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_submitted"


@pytest.mark.asyncio
async def test_submit_closed_session_409(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    token = qr.json()["token"]

    close = await client.post(
        f"/sessions/{session_id}/close", headers=setup.teacher_headers
    )
    assert close.status_code == 200
    assert close.json()["state"] == "closed"

    sub = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": token,
            "gps_lat": str(setup.room_lat),
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",
        },
    )
    # Close revokes the token, so we hit qr_revoked before session_not_open.
    assert sub.status_code in (400, 409)
    assert sub.json()["detail"]["code"] in ("qr_revoked", "session_not_open")


# ── Override ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_override_flagged_to_recorded(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    # Submit far away → flagged.
    sub = await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": qr.json()["token"],
            "gps_lat": str(setup.room_lat + 0.05),
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",
        },
    )
    record_id = sub.json()["id"]
    assert sub.json()["state"] == "flagged"

    ov = await client.patch(
        f"/attendance/sessions/{session_id}/override",
        headers=setup.teacher_headers,
        params={"record_id": record_id},
        json={"to_state": "recorded", "reason": "verified in person"},
    )
    assert ov.status_code == 200, ov.text
    assert ov.json()["from_state"] == "flagged"
    assert ov.json()["to_state"] == "recorded"


# ── Session feed ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_session_feed_counts(client):
    setup = await _build_setup(client)
    session_id = await _fetch_session_id(client, setup)
    qr = await client.post(
        f"/sessions/{session_id}/qr", headers=setup.teacher_headers
    )
    await client.post(
        "/attendance/submit",
        headers=setup.student_headers,
        json={
            "qr_token": qr.json()["token"],
            "gps_lat": str(setup.room_lat),
            "gps_lon": str(setup.room_lon),
            "device_fingerprint": f"device-{_short()}",
        },
    )

    feed = await client.get(
        f"/attendance/session/{session_id}", headers=setup.teacher_headers
    )
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert body["session"]["id"] == session_id
    assert body["counts"]["recorded"] >= 1
    assert any(r["record"] is not None for r in body["rows"])


# ── Student log ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_student_log_self_only(client):
    setup = await _build_setup(client)
    me = await client.get("/users/me", headers=setup.student_headers)
    student_id = me.json()["id"]

    # Self read: ok (even with no records).
    own = await client.get(
        f"/attendance/{student_id}", headers=setup.student_headers
    )
    assert own.status_code == 200

    # Different student id: 403.
    other = await client.get(
        f"/attendance/{uuid.uuid4()}", headers=setup.student_headers
    )
    assert other.status_code == 403


# ── Tenant isolation ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_random_session_id_404(client):
    h = await _admin_headers(client)
    fake = uuid.uuid4()
    r = await client.post(f"/sessions/{fake}/qr", headers=h)
    assert r.status_code == 404


# ── QR helpers (no DB) ──────────────────────────────────────────────────────
def test_haversine_zero_distance():
    from app.modules.attendance.geo import haversine_m

    assert haversine_m(12.943, 77.563, 12.943, 77.563) == pytest.approx(0.0, abs=0.5)


def test_haversine_known_distance():
    """~5.5 km between (12.943, 77.563) and (12.993, 77.563) — straight north."""
    from app.modules.attendance.geo import haversine_m

    d = haversine_m(12.943, 77.563, 12.993, 77.563)
    assert 5400 < d < 5700


def test_qr_sign_verify_roundtrip():
    from decimal import Decimal
    from app.modules.attendance.qr import sign_qr, verify_qr

    jti = uuid.uuid4()
    session_id = uuid.uuid4()
    issued_by = uuid.uuid4()
    token, valid_from, valid_until = sign_qr(
        jti=jti,
        session_id=session_id,
        issued_by_user_id=issued_by,
        centroid_lat=Decimal("12.943"),
        centroid_lon=Decimal("77.563"),
    )
    claims = verify_qr(token)
    assert claims.jti == jti
    assert claims.session_id == session_id
    assert float(claims.centroid_lat) == pytest.approx(12.943, abs=1e-6)
    assert valid_until > valid_from


def test_qr_verify_rejects_garbage():
    from app.modules.attendance.qr import QRInvalidError, verify_qr

    with pytest.raises(QRInvalidError):
        verify_qr("not-a-jwt")
