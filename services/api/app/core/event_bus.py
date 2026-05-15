"""Best-effort event publisher for inter-module fan-out.

M10a publishes the first real event (`semester_setup.published`). The
subscriber side is M10d's job — until then the events live only in the
structured log and (best-effort) on a Redis pub/sub channel.

Contract:

- `publish()` MUST NOT raise on Redis failure or absence. A degraded
  event bus must never take down an API request. The event is always
  written to the structured log first; the Redis fan-out is a bonus.
- The payload shape MUST match AI_DEFERRAL_PLAN.md so M5/M7/M8
  consumers can subscribe without surprises. Top-level keys:
  `event`, `version`, `occurred_at`, `college_id`, `actor_user_id`,
  `data`.
- Channel naming: `metis:events:<event>` (e.g. `metis:events:semester_setup.published`).
- Call AFTER the DB transaction commits. The event reflects committed
  state, not in-flight changes.

When M10d ships the real bus, this module gets swapped to required-Redis
mode with retry + dead-letter handling. The signature stays stable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.core.redis import get_redis_client


log = get_logger("event_bus")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce(value: Any) -> Any:
    """JSON-safe serializer: stringify UUIDs and datetimes."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    return value


def build_event_payload(
    event: str,
    data: dict[str, Any],
    *,
    college_id: UUID | str,
    actor_user_id: UUID | str,
    version: int = 1,
) -> dict[str, Any]:
    """Assemble the wire payload. Pulled out so tests can assert the shape."""
    return {
        "event": event,
        "version": version,
        "occurred_at": _utcnow_iso(),
        "college_id": str(college_id),
        "actor_user_id": str(actor_user_id),
        "data": _coerce(data),
    }


async def publish(
    event: str,
    data: dict[str, Any],
    *,
    college_id: UUID | str,
    actor_user_id: UUID | str,
) -> dict[str, Any]:
    """Publish an event to the bus. Best-effort; never raises.

    Returns the payload that was emitted so callers (and tests) can
    assert on it without rebuilding it.
    """
    payload = build_event_payload(
        event, data, college_id=college_id, actor_user_id=actor_user_id
    )
    # NOTE: structlog binds the first positional as `event`; we re-key our
    # own event name to `event_name` so it doesn't collide.
    log.info("event_published", event_name=event, payload=payload)

    try:
        client = get_redis_client()
        await client.publish(f"metis:events:{event}", json.dumps(payload))
    except Exception as e:  # noqa: BLE001 — Redis problems must not break the API
        log.warning("event_publish_redis_failed", event_name=event, error=str(e))

    return payload
