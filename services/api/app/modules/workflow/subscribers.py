"""In-process event subscribers for workflow-side reactions.

Registered at API startup so the API can react to events on the bus
without waiting for a separate worker process. Cross-service consumers
(M5 comms, M7 learning-engine, M8 insights-engine) subscribe to the
same channels independently — this module is for reactions that should
live close to the writing transaction.

The only handler shipped in M10d is `internal_deadline.crossed` → write
an admin_notifications row so admins see missed/frozen deadlines in
their feed. M5 will replace this with a richer notification surface;
the contract is event-shaped so the swap is mechanical.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.db import SessionLocal
from app.core.event_bus import on as on_event
from app.core.logging import get_logger
from app.modules.workflow.models import AdminNotification


log = get_logger("workflow.subscribers")


async def _record_admin_notification(
    *, college_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    """Append an admin_notifications row. Each subscriber writes its own
    transaction so a failure here doesn't take down the API.
    """
    try:
        async with SessionLocal() as session:
            session.add(
                AdminNotification(
                    college_id=UUID(college_id),
                    event_type=event_type,
                    payload=payload,
                )
            )
            await session.commit()
    except (SQLAlchemyError, ValueError) as e:
        log.warning(
            "admin_notification_write_failed",
            event_type=event_type,
            error=str(e),
        )


async def handle_internal_deadline_crossed(event: dict[str, Any]) -> None:
    """Materialise an admin_notifications row when a deadline freezes."""
    data = event.get("data") or {}
    college_id = event.get("college_id")
    if not college_id:
        return
    await _record_admin_notification(
        college_id=college_id,
        event_type="internal_deadline.crossed",
        payload={
            "internal_deadline_id": data.get("internal_deadline_id"),
            "kind": data.get("kind"),
            "academic_term_id": data.get("academic_term_id"),
            "department_id": data.get("department_id"),
            "course_offering_id": data.get("course_offering_id"),
            "deadline_at": data.get("deadline_at"),
            "frozen_at": data.get("frozen_at"),
        },
    )


def register_workflow_subscribers() -> None:
    """Wire all workflow-side handlers into the in-process registry.

    Called once during FastAPI lifespan startup. Idempotent — repeat
    calls won't double-register because event_bus.on() de-dupes.
    """
    on_event("internal_deadline.crossed", handle_internal_deadline_crossed)
