"""Invite issuance + acceptance."""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.email import send_email
from app.core.security import hash_otp, hash_password, new_otp
from app.modules.users.models import User, UserInvite, UserStatus


INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


class InviteError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def create_invite(
    session: AsyncSession,
    *,
    actor: User,
    user_id: UUID,
    ip: str | None,
    user_agent: str | None,
) -> tuple[UserInvite, str]:
    """Generate an OTP for an existing invited user and email it.

    Returns the new invite row and the plaintext OTP. The plaintext is
    surfaced so tests + the seed script can use it; in production the
    OTP only leaves the box via the email backend.
    """
    target = await session.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise InviteError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise InviteError("forbidden", "cross-college access denied", 403)
    if target.status != UserStatus.invited:
        raise InviteError("already_active", "user is not in invited state", 409)

    # One active invite per (college, email) — invalidate prior unused invites.
    prior = await session.execute(
        select(UserInvite).where(
            UserInvite.college_id == target.college_id,
            UserInvite.email == target.email,
            UserInvite.used_at.is_(None),
        )
    )
    for old in prior.scalars().all():
        old.used_at = utcnow()  # mark as superseded; index is partial on used_at

    otp = new_otp(12)
    invite = UserInvite(
        college_id=target.college_id,
        email=target.email,
        role=target.role,
        name=target.name,
        otp_hash=hash_otp(otp),
        expires_at=utcnow() + timedelta(seconds=INVITE_TTL_SECONDS),
        created_by=actor.id,
    )
    session.add(invite)
    await write_audit(
        session,
        action="invite.create",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    await session.refresh(invite)

    accept_link = f"{settings.web_base_url}/accept-invite?email={target.email}&otp={otp}"
    await send_email(
        to=target.email,
        subject="You're invited to Metis",
        body=f"Hi {target.name},\n\nFinish setting up your account: {accept_link}",
    )
    return invite, otp


async def accept_invite(
    session: AsyncSession,
    *,
    email: str,
    otp: str,
    password: str,
    name: str | None,
    ip: str | None,
    user_agent: str | None,
) -> User:
    email = email.strip().lower()
    otp_h = hash_otp(otp)

    row = await session.execute(
        select(UserInvite).where(
            UserInvite.email == email,
            UserInvite.otp_hash == otp_h,
            UserInvite.used_at.is_(None),
        )
    )
    invite = row.scalar_one_or_none()
    if invite is None:
        raise InviteError("invalid_otp", "invalid or used invite", 400)
    now = utcnow()
    if invite.expires_at <= now:
        raise InviteError("expired_otp", "invite expired", 400)

    user_row = await session.execute(
        select(User).where(
            User.email == email,
            User.college_id == invite.college_id,
            User.deleted_at.is_(None),
        )
    )
    user = user_row.scalar_one_or_none()
    if user is None:
        raise InviteError("not_found", "user not found", 404)
    if user.status != UserStatus.invited:
        raise InviteError("already_active", "user is not in invited state", 409)

    user.password_hash = hash_password(password)
    user.status = UserStatus.active
    if name:
        user.name = name.strip()
    invite.used_at = now

    await write_audit(
        session,
        action="invite.accept",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    # TODO(events): publish `user.enrolled` once an event bus exists (M0.5/M2).
    await session.commit()
    await session.refresh(user)
    return user
