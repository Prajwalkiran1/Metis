"""Append-only audit log helper.

Every state-changing endpoint calls `write_audit(...)` with the actor,
the action verb, and a before/after snapshot. Rows in `audit_logs` are
immutable — there's no `updated_at`. Tenant isolation is enforced via
`college_id`; M9 admin analytics will read this table.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.modules.users.models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | UUID | None = None,
    actor_user_id: UUID | None = None,
    college_id: UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Write a single audit row. Caller is responsible for the session commit.

    `action` is a short verb like `user.create` or `auth.login.fail`.
    Keep them dot-separated so analytics can group by prefix.
    """
    session.add(
        AuditLog(
            college_id=college_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_value=old_value,
            new_value=new_value,
            ip=ip,
            user_agent=user_agent,
            created_at=utcnow(),
        )
    )
