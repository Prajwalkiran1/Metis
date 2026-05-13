"""Stub face-match verifier.

Returns the configured confidence (default 0.95) for any input until M8
ships DeepFace FaceNet. The submit handler discards the raw frame
immediately after this call returns, matching the spec's privacy rule:
"live frame → match/no-match. Frame discarded immediately."

To exercise the FLAGGED path in dev, lower
`ATTENDANCE_FACE_STUB_CONFIDENCE` below the threshold the service uses
(currently 0.6) — the stub doesn't itself decide; the service compares
against the threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings


@dataclass(frozen=True)
class FaceMatchResult:
    match: bool
    confidence: Decimal


def verify_face_stub(
    *, raw_frame_b64: str | None, expected_user_id: str
) -> FaceMatchResult:
    """Discard `raw_frame_b64`, return a fixed confidence.

    Signature mirrors what M8 will implement so the call site doesn't
    change when DeepFace lands. M8's impl will base64-decode the frame,
    run an embedding, cosine-compare against `users.face_embedding_encrypted`,
    and only then return.
    """
    # raw_frame_b64 is intentionally unused — discarded immediately.
    del raw_frame_b64, expected_user_id
    conf = Decimal(str(settings.attendance_face_stub_confidence))
    return FaceMatchResult(match=conf >= Decimal("0.6"), confidence=conf)
