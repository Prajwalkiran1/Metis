"""Google Identity Services ID-token verifier.

Sign-in flow:
  1. Frontend gets an `id_token` from Google (after the user picks an
     account in the GIS popup).
  2. Frontend POSTs it to /auth/google.
  3. We verify the signature against Google's JWKS, check the audience
     matches our OAuth client ID, then return the claims.

`google.oauth2.id_token.verify_oauth2_token` does the JWKS fetch +
caching internally, so we don't have to maintain key state ourselves.
"""
from __future__ import annotations

from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings


class GoogleAuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Reused across calls so the JWKS cache lives for the process lifetime.
_request = google_requests.Request()


def verify_google_id_token(token: str) -> dict[str, Any]:
    """Verify a Google ID token and return its claims.

    Raises GoogleAuthError if the token is malformed, expired, signed by
    the wrong key, addressed to the wrong audience, or asserts an
    unverified email.
    """
    if not settings.google_client_id:
        raise GoogleAuthError(
            "google_disabled",
            "Google sign-in is not configured on this server",
        )

    try:
        claims = google_id_token.verify_oauth2_token(
            token,
            _request,
            audience=settings.google_client_id,
        )
    except ValueError as e:
        # google-auth raises ValueError for every verification failure —
        # bad signature, expired, wrong audience, wrong issuer.
        raise GoogleAuthError("invalid_token", str(e)) from e

    iss = claims.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("bad_issuer", f"unexpected issuer: {iss}")

    if not claims.get("email"):
        raise GoogleAuthError("no_email", "Google did not return an email")
    if not claims.get("email_verified"):
        raise GoogleAuthError("email_unverified", "Google email is not verified")

    return claims
