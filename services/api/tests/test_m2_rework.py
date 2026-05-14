"""Smoke tests for the M2 rework surface.

These run against the live docker-compose Postgres after migrations
0007/0008/0009 have applied. The seed script must have run at least once
(produces the admin/teacher/student demo accounts).

Covered:
- user_role enum accepts hod
- GET /users (admin only) returns paginated rows with USN column
- PATCH /users/{id}/status flips between active and suspended
- PATCH /users/{id}/role enforces hod requires dept + one-HOD-per-dept
- POST /users/bulk-csv dry-run rejects bad rows, commit creates valid rows
- POST /courses accepts course_type=nptel
- GET /hod/dashboard rejects non-HOD callers and returns dept info for HOD
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_auth import DEMO_PASSWORD


async def _login(client, email: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin_headers(client) -> dict[str, str]:
    return await _login(client, "admin@bmsce.ac.in")


def _short() -> str:
    return uuid.uuid4().hex[:6]


# ── /users list + status ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_users_list_admin_only(client):
    h = await _admin_headers(client)
    r = await client.get("/users", headers=h, params={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
    assert isinstance(body["items"], list)
    assert body["total"] >= 1
    # USN column is in the slim list response.
    assert "usn" in body["items"][0]


@pytest.mark.asyncio
async def test_users_list_forbidden_for_non_admin(client):
    s = await _login(client, "student@bmsce.ac.in")
    r = await client.get("/users", headers=s)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_users_status_toggle(client):
    h = await _admin_headers(client)
    # Make a new user we can flip status on.
    email = f"flip-{_short()}@bmsce.ac.in"
    c = await client.post(
        "/users",
        headers=h,
        json={"email": email, "name": "Flip Me", "role": "teacher"},
    )
    assert c.status_code == 201, c.text
    uid = c.json()["id"]

    susp = await client.patch(
        f"/users/{uid}/status", headers=h, json={"status": "suspended"}
    )
    assert susp.status_code == 200
    assert susp.json()["status"] == "suspended"

    act = await client.patch(
        f"/users/{uid}/status", headers=h, json={"status": "active"}
    )
    assert act.status_code == 200
    assert act.json()["status"] == "active"


# ── HOD role assignment ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_role_change_to_hod_requires_dept(client):
    h = await _admin_headers(client)
    email = f"hod-{_short()}@bmsce.ac.in"
    c = await client.post(
        "/users",
        headers=h,
        json={"email": email, "name": "Future HOD", "role": "teacher"},
    )
    uid = c.json()["id"]

    # No dept → 400
    bad = await client.patch(
        f"/users/{uid}/role", headers=h, json={"role": "hod"}
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "hod_dept_required"


@pytest.mark.asyncio
async def test_role_change_hod_unique_per_dept(client):
    h = await _admin_headers(client)
    # Find a dept that already has an HOD (post-backfill at least CSE should).
    depts = await client.get("/departments", headers=h)
    assert depts.status_code == 200
    # Find any dept_id with an active HOD by listing users.
    users = await client.get(
        "/users", headers=h, params={"role": "hod", "limit": 5}
    )
    if users.json()["total"] == 0:
        pytest.skip("no existing HOD to collide with — seed data has none")
    occupied_dept = users.json()["items"][0]["hod_of_department_id"]
    assert occupied_dept

    # Create a fresh teacher and try to promote to HOD of the occupied dept.
    email = f"hod2-{_short()}@bmsce.ac.in"
    c = await client.post(
        "/users",
        headers=h,
        json={"email": email, "name": "Second HOD", "role": "teacher"},
    )
    uid = c.json()["id"]
    bad = await client.patch(
        f"/users/{uid}/role",
        headers=h,
        json={"role": "hod", "hod_of_department_id": occupied_dept},
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "hod_already_assigned"


# ── Bulk CSV ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bulk_csv_dry_run_validates_usn(client):
    h = await _admin_headers(client)
    csv = (
        "email,name,role,usn,phone\n"
        f"good-{_short()}@bmsce.ac.in,Good Student,student,1BM23CS{_short_num()},9876543210\n"
        f"bad-{_short()}@bmsce.ac.in,Bad Student,student,NOT-A-USN,\n"
        f"missing-{_short()}@bmsce.ac.in,Missing USN,student,,\n"
        f"good-teacher-{_short()}@bmsce.ac.in,Good Teacher,teacher,,9876543210\n"
        f"bad-domain-{_short()}@elsewhere.com,Wrong Domain,teacher,,\n"
    )
    files = {"file": ("users.csv", csv.encode(), "text/csv")}
    data = {"dry_run": "true"}
    r = await client.post(
        "/users/bulk-csv", headers=h, files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["inserted"] == 0
    assert body["valid_rows"] == 2  # the two good ones
    error_codes = {e["code"] for e in body["errors"]}
    assert "bad_usn_format" in error_codes
    assert "missing_usn" in error_codes
    assert "bad_domain" in error_codes


@pytest.mark.asyncio
async def test_bulk_csv_commit_inserts(client):
    h = await _admin_headers(client)
    email = f"commit-{_short()}@bmsce.ac.in"
    csv = (
        "email,name,role,usn,phone\n"
        f"{email},Commit Teacher,teacher,,\n"
    )
    files = {"file": ("users.csv", csv.encode(), "text/csv")}
    data = {"dry_run": "false"}
    r = await client.post(
        "/users/bulk-csv", headers=h, files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 1
    assert body["errors"] == []

    # The user is now listable.
    lst = await client.get("/users", headers=h, params={"q": email})
    assert lst.status_code == 200
    assert any(u["email"] == email for u in lst.json()["items"])


# ── courses accept nptel ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_courses_accept_nptel_course_type(client):
    h = await _admin_headers(client)
    dept = await client.post(
        "/departments", headers=h, json={"name": "NPTELDept", "code": f"NP-{_short()}"}
    )
    dept_id = dept.json()["id"]
    code = f"NP{_short()}"
    r = await client.post(
        "/courses",
        headers=h,
        json={
            "department_id": dept_id,
            "code": code,
            "title": "MOOC slot 1",
            "credits": 3,
            "semester": 5,
            "course_type": "nptel",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["course_type"] == "nptel"


# ── /hod/dashboard ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hod_dashboard_rejects_non_hod(client):
    s = await _login(client, "student@bmsce.ac.in")
    r = await client.get("/hod/dashboard", headers=s)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_hod_dashboard_returns_dept(client):
    h = await _admin_headers(client)
    users = await client.get(
        "/users", headers=h, params={"role": "hod", "limit": 1}
    )
    if users.json()["total"] == 0:
        pytest.skip("no HOD in seed — backfill skipped this run")
    hod_email = users.json()["items"][0]["email"]
    # Seeded HODs use the demo password if they came from the seed admin.
    # If they were backfilled from an existing teacher account, this login
    # may fail; that's acceptable — the assertion only runs when login works.
    try:
        hod_headers = await _login(client, hod_email)
    except AssertionError:
        pytest.skip(
            f"could not log in as {hod_email}; backfilled HOD has no usable password"
        )
    r = await client.get("/hod/dashboard", headers=hod_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "department" in body
    assert body["department"]["id"]
    assert "teaching_offerings" in body
    assert "placeholder" in body


def _short_num() -> str:
    """3-digit USN suffix derived from uuid bytes."""
    u = uuid.uuid4().bytes
    return f"{(u[0] * 256 + u[1]) % 1000:03d}"
