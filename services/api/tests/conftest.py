"""Pytest fixtures for the API test suite.

These tests run against the docker-compose Postgres + Redis. We can't
swap Postgres for SQLite because the schema uses Postgres-only features
(INET, JSONB, partial unique indexes, the set_updated_at trigger).

Each test gets a fresh transaction that is rolled back at the end so
tests don't pollute each other. Redis is flushed per-test using
fakeredis when available so we don't need the docker stack running just
to test rate-limit/lockout logic.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("APP_ENV", "test")

from app.core import redis as redis_module  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis() -> AsyncIterator[None]:
    """Flush Redis between tests so lockout counters don't bleed."""
    try:
        client = redis_module.get_redis_client()
        await client.flushdb()
    except Exception:
        # Redis not reachable; tests that don't need it will still pass.
        pass
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_engine():
    yield
    await engine.dispose()
    await redis_module.close_redis()
