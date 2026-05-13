"""Signed-JWT QR token wrapper.

A QR token is a JWT keyed off `settings.jwt_secret` with `typ='attendance_qr'`
to keep it unconflated with access tokens. Claims:

  jti     uuid (matches qr_tokens.jti — explicit anti-replay handle)
  sid     class_session_id
  lat,lon GPS centroid copied from the session's room (or null if no room coords)
  iat,exp standard JWT timestamps; exp = iat + ATTENDANCE_QR_TTL_SECONDS
  iss_by  teacher who issued the token
  typ     "attendance_qr"

`sign_qr` is what `/sessions/{id}/qr` returns. `verify_qr` is what
`/attendance/submit` calls — it validates signature, type, and expiry,
and returns the decoded claims. The DB-level jti lookup happens in the
service layer (not here) so the unit tests can exercise the JWT half
without a session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from app.core.config import settings

QR_TOKEN_TYPE = "attendance_qr"


@dataclass(frozen=True)
class QRClaims:
    jti: UUID
    session_id: UUID
    centroid_lat: Decimal | None
    centroid_lon: Decimal | None
    valid_from: datetime
    valid_until: datetime
    issued_by_user_id: UUID


class QRInvalidError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sign_qr(
    *,
    jti: UUID,
    session_id: UUID,
    issued_by_user_id: UUID,
    centroid_lat: Decimal | None,
    centroid_lon: Decimal | None,
    ttl_seconds: int | None = None,
) -> tuple[str, datetime, datetime]:
    """Sign a fresh QR JWT. Returns (token, valid_from, valid_until)."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.attendance_qr_ttl_seconds
    now = datetime.now(timezone.utc)
    exp = now.timestamp() + ttl
    payload: dict[str, Any] = {
        "typ": QR_TOKEN_TYPE,
        "jti": str(jti),
        "sid": str(session_id),
        "lat": float(centroid_lat) if centroid_lat is not None else None,
        "lon": float(centroid_lon) if centroid_lon is not None else None,
        "iat": int(now.timestamp()),
        "exp": int(exp),
        "iss_by": str(issued_by_user_id),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    valid_until = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    return token, now, valid_until


def verify_qr(token: str) -> QRClaims:
    """Validate signature + type + exp; return decoded claims.

    Does NOT check that the jti exists in the DB — that's the service
    layer's job and is its own anti-replay layer on top of the JWT exp.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise QRInvalidError("bad_signature", "QR token invalid or expired") from e
    if payload.get("typ") != QR_TOKEN_TYPE:
        raise QRInvalidError("bad_type", "wrong token type")
    try:
        jti = UUID(payload["jti"])
        sid = UUID(payload["sid"])
        issued_by = UUID(payload["iss_by"])
        iat = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
        exp = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (KeyError, ValueError, TypeError) as e:
        raise QRInvalidError("bad_claims", "QR token claims malformed") from e

    lat_raw = payload.get("lat")
    lon_raw = payload.get("lon")
    centroid_lat = Decimal(str(lat_raw)) if lat_raw is not None else None
    centroid_lon = Decimal(str(lon_raw)) if lon_raw is not None else None

    return QRClaims(
        jti=jti,
        session_id=sid,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        valid_from=iat,
        valid_until=exp,
        issued_by_user_id=issued_by,
    )
