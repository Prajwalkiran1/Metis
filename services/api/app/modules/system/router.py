"""System endpoints — liveness and readiness.

`/health` returns 200 as long as the process is up. Useful for Render
free-tier keepalive pings and uptime monitoring.

`/ready` pings the database (`SELECT 1`) and Redis (`PING`) and reports
each check's status individually. Overall status is `down` if any
required check fails; an orchestrator can use that to keep the pod out
of the load balancer until dependencies are reachable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionDep
from app.core.logging import get_logger
from app.core.redis import RedisDep

router = APIRouter(tags=["system"])
log = get_logger(__name__)


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


async def _check_db(session: SessionDep) -> ReadinessCheck:
    try:
        await session.execute(text("SELECT 1"))
        return ReadinessCheck(status="ok")
    except Exception as exc:  # noqa: BLE001 — readiness must never raise
        log.warning("ready.db_check_failed", error=str(exc))
        return ReadinessCheck(status="down", detail=str(exc)[:200])


async def _check_redis(redis: RedisDep) -> ReadinessCheck:
    try:
        pong = await redis.ping()
        if pong:
            return ReadinessCheck(status="ok")
        return ReadinessCheck(status="down", detail="ping returned falsey")
    except Exception as exc:  # noqa: BLE001
        log.warning("ready.redis_check_failed", error=str(exc))
        return ReadinessCheck(status="down", detail=str(exc)[:200])


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready(session: SessionDep, redis: RedisDep) -> ReadinessResponse:
    checks = {
        "db": await _check_db(session),
        "redis": await _check_redis(redis),
    }
    overall: Literal["ok", "degraded", "down"] = (
        "ok" if all(c.status == "ok" for c in checks.values()) else "down"
    )
    return ReadinessResponse(
        status=overall,
        checks=checks,
        timestamp=datetime.now(timezone.utc),
    )
