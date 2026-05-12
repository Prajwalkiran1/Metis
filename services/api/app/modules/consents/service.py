"""DPDP consent helpers.

No router yet — the consent UI lives in M9 (admin) and inside the M3
attendance flow. Other modules call `grant_consent` / `withdraw_consent`
inline.

Each grant inserts a new row rather than updating an existing one, so
the table is an append-only history we can audit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utcnow
from app.modules.users.models import Consent, ConsentPurpose, User


async def grant_consent(
    session: AsyncSession,
    *,
    user: User,
    purpose: ConsentPurpose,
    ip: str | None,
    user_agent: str | None,
) -> Consent:
    row = Consent(
        user_id=user.id,
        purpose=purpose,
        consent_text_version=settings.consent_text_version,
        granted_at=utcnow(),
        ip=ip,
        user_agent=user_agent,
    )
    session.add(row)
    await session.flush()
    return row


async def withdraw_consent(
    session: AsyncSession,
    *,
    user: User,
    purpose: ConsentPurpose,
) -> None:
    q = await session.execute(
        select(Consent)
        .where(
            Consent.user_id == user.id,
            Consent.purpose == purpose,
            Consent.withdrawn_at.is_(None),
        )
        .order_by(Consent.granted_at.desc())
    )
    now = utcnow()
    for row in q.scalars().all():
        row.withdrawn_at = now


async def latest_for_purpose(
    session: AsyncSession, *, user: User, purpose: ConsentPurpose
) -> Consent | None:
    q = await session.execute(
        select(Consent)
        .where(
            Consent.user_id == user.id,
            Consent.purpose == purpose,
            Consent.withdrawn_at.is_(None),
        )
        .order_by(Consent.granted_at.desc())
        .limit(1)
    )
    return q.scalars().first()
