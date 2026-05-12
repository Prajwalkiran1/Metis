"""Thin email-sending helper. Two backends today:

* `console` — writes the message to the structured log. Used in dev/test.
* `resend`  — POSTs to Resend's HTTP API. Used in staging/prod once a
              `RESEND_API_KEY` is set.

Both backends honour `settings.email_from`. Callers pass a subject and
plain-text body; HTML templates land in M5 (comms service).
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


async def send_email(*, to: str, subject: str, body: str) -> None:
    if settings.email_backend == "console":
        log.info(
            "email.sent_console",
            to=to,
            subject=subject,
            body=body,
            sender=settings.email_from,
        )
        return

    api_key = settings.resend_api_key.get_secret_value() if settings.resend_api_key else None
    if not api_key:
        log.error("email.resend_misconfigured", to=to, subject=subject)
        raise RuntimeError("EMAIL_BACKEND=resend but RESEND_API_KEY is not set")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "text": body,
            },
        )
    if resp.status_code >= 400:
        log.error("email.resend_failed", to=to, status=resp.status_code, body=resp.text)
        resp.raise_for_status()
