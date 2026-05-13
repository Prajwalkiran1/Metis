"""IP-keyed rate limiting backed by Redis (slowapi).

A single `Limiter` instance for the whole app. Routers use it via the
`auth_rate_limit` decorator on auth endpoints to enforce
`RATE_LIMIT_AUTH_PER_MINUTE`. Other endpoints can build their own
decorators on top of `limiter`.

Storage: the same Redis we use elsewhere, so rate-limit counters survive
restarts and are shared across replicas.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[],
)


def auth_rate_limit() -> str:
    """Return the slowapi limit string for auth endpoints."""
    return f"{settings.rate_limit_auth_per_minute}/minute"


def attendance_submit_rate_limit() -> str:
    """Per-IP cap on /attendance/submit — defends against bulk replay."""
    return f"{settings.rate_limit_attendance_submit_per_minute}/minute"
