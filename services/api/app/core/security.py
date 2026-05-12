"""Password hashing, JWT signing/verification, and refresh-token helpers.

argon2id is the only password hash used. JWTs are short-lived access
tokens (HS256, TTL from settings). Refresh tokens are opaque random
strings — the database stores a SHA-256 hash, never the plaintext.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

_hasher = PasswordHasher()


# ── Passwords ─────────────────────────────────────────────────────────────────
def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(hashed: str, plaintext: str) -> bool:
    try:
        return _hasher.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHash):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# ── Access tokens (JWT) ───────────────────────────────────────────────────────
def create_access_token(
    *,
    subject: UUID | str,
    role: str,
    college_id: UUID | str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "college_id": str(college_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "typ": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + validate signature/expiry. Raises `JWTError` on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


# ── Refresh tokens (opaque + hashed at rest) ─────────────────────────────────
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl_seconds)


# ── Short OTPs (invites + password reset) ────────────────────────────────────
def new_otp(length: int = 8) -> str:
    """URL-safe random OTP suitable for one-time email/SMS links."""
    return secrets.token_urlsafe(length)


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


__all__ = [
    "JWTError",
    "create_access_token",
    "decode_access_token",
    "hash_otp",
    "hash_password",
    "hash_refresh_token",
    "new_otp",
    "new_refresh_token",
    "password_needs_rehash",
    "refresh_token_expiry",
    "verify_password",
]
