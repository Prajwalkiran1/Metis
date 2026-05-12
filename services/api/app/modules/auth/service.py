"""Auth business logic — pure functions over a session + redis client.

Endpoints in `router.py` keep the FastAPI plumbing (request parsing,
cookies, error mapping). All state changes and DB writes live here so
the same flow is reusable from tests and from background jobs.

Lockout:
    Redis key `lockout:login:<email>` is INCR-ed on every failed login
    and EXPIRE-d to LOGIN_LOCKOUT_WINDOW_SECONDS. When the counter
    crosses LOGIN_LOCKOUT_MAX_ATTEMPTS the email is locked for the
    remainder of the window.

Refresh-token rotation:
    On every refresh we mark the old `auth_sessions` row revoked and
    insert a fresh row. M1 does not implement token-family reuse
    detection — TODO(M1-hardening) below.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.db import utcnow
from app.core.email import send_email
from app.core.google_oauth import GoogleAuthError, verify_google_id_token
from app.core.security import (
    create_access_token,
    hash_otp,
    hash_password,
    hash_refresh_token,
    new_otp,
    new_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.modules.users.models import (
    AuthSession,
    College,
    LoginAttempt,
    PasswordResetToken,
    User,
    UserStatus,
)


PASSWORD_RESET_OTP_TTL_SECONDS = 60 * 30  # 30 min


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str  # plaintext; only returned to the client once
    expires_in: int
    user: User


# ── Lockout helpers ───────────────────────────────────────────────────────────
def _lockout_key(email: str) -> str:
    return f"lockout:login:{email.lower()}"


async def _is_locked(redis: Redis, email: str) -> bool:
    val = await redis.get(_lockout_key(email))
    if val is None:
        return False
    try:
        return int(val) >= settings.login_lockout_max_attempts
    except (TypeError, ValueError):
        return False


async def _record_failure(redis: Redis, email: str) -> None:
    key = _lockout_key(email)
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, settings.login_lockout_window_seconds)
    await pipe.execute()


async def _clear_failures(redis: Redis, email: str) -> None:
    await redis.delete(_lockout_key(email))


# ── Public service surface ────────────────────────────────────────────────────
class AuthError(Exception):
    """Raised by the service layer; router maps to HTTP responses."""

    def __init__(self, code: str, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def login(
    session: AsyncSession,
    redis: Redis,
    *,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    email = email.strip().lower()
    if await _is_locked(redis, email):
        await _log_attempt(session, email=email, ip=ip, success=False, reason="locked")
        raise AuthError("locked", "too many failed attempts; try again later", 429)

    user = await _find_active_user_by_email(session, email)
    if user is None or user.password_hash is None or not verify_password(
        user.password_hash, password
    ):
        await _record_failure(redis, email)
        await _log_attempt(
            session,
            email=email,
            college_id=user.college_id if user else None,
            ip=ip,
            success=False,
            reason="bad_credentials",
        )
        await session.commit()
        raise AuthError("invalid_credentials", "invalid email or password", 401)

    if user.status != UserStatus.active:
        await _log_attempt(
            session,
            email=email,
            college_id=user.college_id,
            ip=ip,
            success=False,
            reason=f"status_{user.status.value}",
        )
        await session.commit()
        raise AuthError("inactive", f"account is {user.status.value}", 403)

    await _clear_failures(redis, email)
    await _log_attempt(
        session,
        email=email,
        college_id=user.college_id,
        ip=ip,
        success=True,
    )

    tokens = await _issue_tokens(session, user=user, ip=ip, user_agent=user_agent)
    await write_audit(
        session,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    return tokens


async def login_with_google(
    session: AsyncSession,
    *,
    id_token: str,
    ip: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    """Sign-in via Google Identity Services.

    Flow:
      1. Verify the Google ID token (signature + audience + email_verified).
      2. Look up the Metis user by lower(email). No auto-create — admins
         must invite the user first; same playbook as M1's invite flow.
      3. Enforce the user's college email_domain against the Google email.
      4. Bind google_sub on first login; reject mismatched sub on later
         logins (prevents account hijack via re-used emails).
      5. Issue the standard Metis access + refresh token pair.
    """
    try:
        claims = verify_google_id_token(id_token)
    except GoogleAuthError as e:
        # Map "google not configured" to 503; everything else to 401.
        status = 503 if e.code == "google_disabled" else 401
        raise AuthError(e.code, e.message, status) from e

    google_email = claims["email"].strip().lower()
    google_sub = str(claims["sub"])

    user = await _find_active_user_by_email(session, google_email)
    if user is None:
        await _log_attempt(
            session,
            email=google_email,
            ip=ip,
            success=False,
            reason="google_no_account",
        )
        await session.commit()
        raise AuthError(
            "no_account",
            "no Metis account on this college — ask your admin to invite you",
            403,
        )

    college = await session.get(College, user.college_id)
    if college is None:
        raise AuthError("orphan", "user has no college (corrupt state)", 500)

    domain = google_email.rsplit("@", 1)[-1] if "@" in google_email else ""
    if domain != college.email_domain.lower():
        await _log_attempt(
            session,
            email=google_email,
            college_id=user.college_id,
            ip=ip,
            success=False,
            reason="google_bad_domain",
        )
        await session.commit()
        raise AuthError(
            "bad_domain",
            f"email must end with @{college.email_domain}",
            403,
        )

    if user.status != UserStatus.active:
        await _log_attempt(
            session,
            email=google_email,
            college_id=user.college_id,
            ip=ip,
            success=False,
            reason=f"status_{user.status.value}",
        )
        await session.commit()
        raise AuthError("inactive", f"account is {user.status.value}", 403)

    if user.google_sub is None:
        user.google_sub = google_sub
    elif user.google_sub != google_sub:
        await _log_attempt(
            session,
            email=google_email,
            college_id=user.college_id,
            ip=ip,
            success=False,
            reason="google_sub_mismatch",
        )
        await session.commit()
        raise AuthError(
            "sub_mismatch",
            "this email is already linked to a different Google account",
            403,
        )

    await _log_attempt(
        session,
        email=google_email,
        college_id=user.college_id,
        ip=ip,
        success=True,
    )

    tokens = await _issue_tokens(session, user=user, ip=ip, user_agent=user_agent)
    await write_audit(
        session,
        action="auth.login.google",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    return tokens


async def rotate_refresh(
    session: AsyncSession,
    *,
    refresh_token_plain: str,
    ip: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    token_hash = hash_refresh_token(refresh_token_plain)
    row = await session.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    auth_row = row.scalar_one_or_none()

    if auth_row is None:
        # TODO(M1-hardening): if we knew this token used to be valid we'd
        # nuke the whole family here (reuse detection).
        raise AuthError("invalid_refresh", "unknown refresh token", 401)

    now = utcnow()
    if auth_row.revoked_at is not None:
        raise AuthError("revoked_refresh", "refresh token revoked", 401)
    if auth_row.expires_at <= now:
        raise AuthError("expired_refresh", "refresh token expired", 401)

    user = await session.get(User, auth_row.user_id)
    if user is None or user.deleted_at is not None or user.status != UserStatus.active:
        raise AuthError("inactive", "account no longer active", 403)

    auth_row.revoked_at = now
    tokens = await _issue_tokens(session, user=user, ip=ip, user_agent=user_agent)
    await write_audit(
        session,
        action="auth.refresh",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    return tokens


async def logout(
    session: AsyncSession,
    *,
    refresh_token_plain: str | None,
    actor_user_id,
    ip: str | None,
    user_agent: str | None,
) -> None:
    if not refresh_token_plain:
        return
    token_hash = hash_refresh_token(refresh_token_plain)
    row = await session.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    auth_row = row.scalar_one_or_none()
    if auth_row is not None and auth_row.revoked_at is None:
        auth_row.revoked_at = utcnow()
        await write_audit(
            session,
            action="auth.logout",
            entity_type="user",
            entity_id=auth_row.user_id,
            actor_user_id=actor_user_id,
            ip=ip,
            user_agent=user_agent,
        )
    await session.commit()


async def request_password_reset(
    session: AsyncSession,
    *,
    email: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Always returns success to the caller — we never reveal whether the
    address exists."""
    email = email.strip().lower()
    user = await _find_active_user_by_email(session, email)
    if user is None:
        return

    otp = new_otp(12)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            otp_hash=hash_otp(otp),
            expires_at=utcnow() + timedelta(seconds=PASSWORD_RESET_OTP_TTL_SECONDS),
        )
    )
    await write_audit(
        session,
        action="auth.reset_password.request",
        entity_type="user",
        entity_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()

    reset_link = f"{settings.web_base_url}/reset-password?otp={otp}"
    await send_email(
        to=user.email,
        subject="Reset your Metis password",
        body=f"Use this link to reset your password (valid 30 minutes): {reset_link}",
    )


async def confirm_password_reset(
    session: AsyncSession,
    *,
    otp: str,
    new_password: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    otp_hash = hash_otp(otp)
    row = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.otp_hash == otp_hash)
    )
    token = row.scalar_one_or_none()
    if token is None:
        raise AuthError("invalid_otp", "invalid or expired reset code", 400)
    now = utcnow()
    if token.used_at is not None:
        raise AuthError("used_otp", "reset code already used", 400)
    if token.expires_at <= now:
        raise AuthError("expired_otp", "reset code expired", 400)

    user = await session.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("invalid_otp", "invalid or expired reset code", 400)

    user.password_hash = hash_password(new_password)
    token.used_at = now

    # Revoke every existing session — forces re-login on every device.
    sessions_q = await session.execute(
        select(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
        )
    )
    for s in sessions_q.scalars().all():
        s.revoked_at = now

    await write_audit(
        session,
        action="auth.reset_password.confirm",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        college_id=user.college_id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()


# ── Internals ─────────────────────────────────────────────────────────────────
async def _find_active_user_by_email(session: AsyncSession, email: str) -> User | None:
    # Email is unique per college among non-deleted users. With one tenant
    # (BMSCE) for M1 this returns at most one row.
    q = await session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    return q.scalars().first()


async def _log_attempt(
    session: AsyncSession,
    *,
    email: str,
    success: bool,
    college_id=None,
    ip: str | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        LoginAttempt(
            email=email,
            college_id=college_id,
            ip=ip,
            success=success,
            failure_reason=reason if not success else None,
            created_at=utcnow(),
        )
    )


async def _issue_tokens(
    session: AsyncSession, *, user: User, ip: str | None, user_agent: str | None
) -> IssuedTokens:
    refresh = new_refresh_token()
    session.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh),
            user_agent=user_agent,
            ip=ip,
            last_seen_at=utcnow(),
            expires_at=refresh_token_expiry(),
        )
    )
    access = create_access_token(
        subject=user.id,
        role=user.role.value,
        college_id=user.college_id,
    )
    return IssuedTokens(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
        user=user,
    )
