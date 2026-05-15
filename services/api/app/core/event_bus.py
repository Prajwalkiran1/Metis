"""Event bus — publisher (M10a) + in-process subscriber registry (M10d).

Publishing
----------
`publish()` is best-effort: it always writes to the structured log first
and then attempts a Redis `PUBLISH`. Redis failure never propagates to
the caller — a degraded bus must not take down an API request. Channel
naming is `metis:events:<event>` and the payload shape matches
AI_DEFERRAL_PLAN.md.

Subscribing
-----------
The subscriber side is an in-process registry: modules register coroutine
handlers via `on(event_name, handler)`, and `start_subscriber()` launches
a background psubscribe loop that dispatches incoming messages to the
registered handlers. Handlers are NEVER invoked synchronously from
`publish()` — they're always async-fan-out via Redis so that future
M5/M7/M8 services running in separate processes can subscribe to the
same channels.

If Redis is unavailable, `start_subscriber()` exits cleanly so tests that
don't bother starting Redis still pass — in that mode the registry is
inert and `publish()`'s log-only behaviour remains the source of truth.

When M10d's worker mode ships in production, this same module powers
both: in-process handlers run inside the API for low-latency reactions
(admin_notifications writer); cross-service consumers subscribe to the
same channels from `services/learning-engine/` and `services/insights-engine/`.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.core.redis import get_redis_client


log = get_logger("event_bus")

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[EventHandler]] = {}
_subscriber_task: asyncio.Task[None] | None = None


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


# ── Subscriber-side registry ───────────────────────────────────────────────
def on(event: str, handler: EventHandler) -> None:
    """Register `handler` to receive events of `event` name. Handlers run
    inside the API process; cross-service consumers subscribe directly to
    Redis. Idempotent: same handler registered twice is recorded once.
    """
    bucket = _handlers.setdefault(event, [])
    if handler not in bucket:
        bucket.append(handler)


def clear_handlers() -> None:
    """Test helper: drops all registered handlers."""
    _handlers.clear()


async def _dispatch(event_name: str, payload: dict[str, Any]) -> None:
    """Invoke every handler registered for `event_name`. Handler failures
    are logged but never propagated — one broken handler must not kill
    the subscriber loop for the rest.
    """
    for handler in _handlers.get(event_name, ()):
        try:
            await handler(payload)
        except Exception as e:  # noqa: BLE001 — never let a handler kill the loop
            log.warning(
                "event_handler_failed",
                event_name=event_name,
                handler=getattr(handler, "__qualname__", repr(handler)),
                error=str(e),
            )


async def start_subscriber() -> None:
    """Start a background `psubscribe('metis:events:*')` loop. Safe to
    call multiple times — only the first call schedules a task. Returns
    immediately; the task lives until cancelled by `stop_subscriber()`.

    If Redis is offline, the loop sleeps + retries indefinitely with
    exponential backoff (capped at 30s). When Redis comes back the
    listener picks up where it left off — pub/sub doesn't replay, but
    payloads in flight aren't lost either because publishers fall back
    to the structured log.
    """
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = asyncio.create_task(_subscriber_loop(), name="event_bus_subscriber")


async def stop_subscriber() -> None:
    """Cancel the background subscriber task on shutdown."""
    global _subscriber_task
    if _subscriber_task is None:
        return
    _subscriber_task.cancel()
    try:
        await _subscriber_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _subscriber_task = None


async def _subscriber_loop() -> None:
    """The forever-loop subscriber. Reconnects on Redis errors with
    capped exponential backoff so transient outages don't require a
    process restart.
    """
    backoff = 1.0
    while True:
        pubsub = None
        try:
            client = get_redis_client()
            pubsub = client.pubsub()
            await pubsub.psubscribe("metis:events:*")
            backoff = 1.0  # reset on successful connect
            log.info("event_subscriber_started", pattern="metis:events:*")
            async for msg in pubsub.listen():
                if msg.get("type") != "pmessage":
                    continue
                channel = msg.get("channel") or ""
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", errors="replace")
                event_name = channel.rsplit(":", 1)[-1] if channel else ""
                if not event_name:
                    continue
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(data) if isinstance(data, str) else data
                except (json.JSONDecodeError, TypeError):
                    log.warning(
                        "event_subscriber_bad_payload",
                        event_name=event_name,
                        raw=str(data)[:200],
                    )
                    continue
                await _dispatch(event_name, payload)
        except asyncio.CancelledError:
            log.info("event_subscriber_cancelled")
            try:
                if pubsub is not None:
                    await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as e:  # noqa: BLE001 — Redis errors, etc.
            log.warning(
                "event_subscriber_error",
                error=str(e),
                next_retry_seconds=backoff,
            )
            try:
                if pubsub is not None:
                    await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
