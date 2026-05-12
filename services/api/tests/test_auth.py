"""Auth happy-path + edge-case smoke tests.

Run with `npm run test:api`. Requires the docker stack + a fresh seed,
so the test suite expects `admin@bmsce.edu.in` to exist with the seed
password.
"""
from __future__ import annotations

import pytest

# Must stay in sync with infra/scripts/seed.py:DEMO_PASSWORD.
DEMO_PASSWORD = "MetisDemo!2026"


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_ready(client):
    resp = await client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["db"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_login_happy_path(client):
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.edu.in", "password": DEMO_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert "access_token" in body
    assert "metis_refresh" in resp.cookies


@pytest.mark.asyncio
async def test_login_bad_password(client):
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.edu.in", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_lockout(client):
    # 5 fails should trigger a 429 on the 6th attempt. Both the slowapi
    # IP rate limit and the Redis-backed account lockout return 429 at
    # this threshold; either one is correct brute-force protection.
    for _ in range(5):
        await client.post(
            "/auth/login",
            json={"email": "lockout-victim@bmsce.edu.in", "password": "x"},
        )
    resp = await client.post(
        "/auth/login",
        json={"email": "lockout-victim@bmsce.edu.in", "password": "x"},
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_refresh_rotation(client):
    login = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.edu.in", "password": DEMO_PASSWORD},
    )
    assert login.status_code == 200
    first_refresh = login.cookies["metis_refresh"]

    rotated = await client.post("/auth/refresh", cookies={"metis_refresh": first_refresh})
    assert rotated.status_code == 200
    new_refresh = rotated.cookies["metis_refresh"]
    assert new_refresh != first_refresh

    # Replaying the old refresh must fail (it's revoked).
    replay = await client.post("/auth/refresh", cookies={"metis_refresh": first_refresh})
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "revoked_refresh"


@pytest.mark.asyncio
async def test_get_me_requires_auth(client):
    resp = await client.get("/users/me")
    assert resp.status_code == 401

    login = await client.post(
        "/auth/login",
        json={"email": "admin@bmsce.edu.in", "password": DEMO_PASSWORD},
    )
    token = login.json()["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@bmsce.edu.in"
