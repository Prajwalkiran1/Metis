"""Async Redis client + FastAPI dependency.

One shared `redis.asyncio.Redis` instance, lazily constructed from
`settings.redis_url`. Used by `core.ratelimit` for the slowapi storage,
by the auth service for lockout counters, and by `system.ready` for the
liveness ping.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Return the process-wide Redis client, building it on first use."""
    global _client
    if _client is None:
        _client = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_redis() -> AsyncIterator[Redis]:
    yield get_redis_client()


RedisDep = Annotated[Redis, Depends(get_redis)]
