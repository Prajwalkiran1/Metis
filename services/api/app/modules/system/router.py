"""System endpoints — liveness and readiness.

`/health` returns 200 as long as the process is up. Useful for Render free-tier
keepalive pings and uptime monitoring.

`/ready` checks downstream dependencies (DB, Redis) and returns each one's
status. Will start exercising real DB/Redis pings once those layers land in
later commits — for now it just reports the app is ready to serve.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    env: str
    timestamp: datetime


class ReadinessCheck(BaseModel):
    status: Literal["ok", "degraded", "down"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checks: dict[str, ReadinessCheck]
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        env=settings.app_env,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready() -> ReadinessResponse:
    # Real DB and Redis pings are wired in a later commit when those modules exist.
    checks = {
        "app": ReadinessCheck(status="ok"),
    }
    return ReadinessResponse(
        status="ok",
        checks=checks,
        timestamp=datetime.now(timezone.utc),
    )
