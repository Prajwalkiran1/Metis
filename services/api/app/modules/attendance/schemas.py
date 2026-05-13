"""Request/response schemas for the attendance module."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attendance.models import (
    AttendanceRecordState,
    ClassSessionSource,
    ClassSessionState,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


# ── Class sessions ──────────────────────────────────────────────────────────
class ClassSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    course_offering_id: UUID
    room_id: UUID | None = None
    scheduled_date: date
    start_time: time
    end_time: time
    state: ClassSessionState
    source: ClassSessionSource
    origin_slot_id: UUID | None = None
    origin_exception_id: UUID | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── QR token ────────────────────────────────────────────────────────────────
class QRTokenOut(BaseModel):
    """Returned by POST /sessions/{id}/qr — what the FE renders as a QR."""

    token: str
    jti: UUID
    session_id: UUID
    valid_from: datetime
    valid_until: datetime
    ttl_seconds: int


# ── Attendance submit ───────────────────────────────────────────────────────
class AttendanceSubmit(BaseModel):
    """Student-side submit payload. Three independent anti-proxy layers:

    1. `qr_token` — signed JWT, verified server-side
    2. `gps_lat` / `gps_lon` — haversine vs. room centroid; > threshold → flagged
    3. `face_frame_b64` — handed to M8 stub; never stored
    Plus `device_fingerprint` — SHA-256'd and stored as the device anti-replay key.
    """

    qr_token: str = Field(min_length=20)
    gps_lat: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    gps_lon: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))
    face_frame_b64: str | None = Field(default=None, max_length=2_000_000)
    device_fingerprint: str = Field(min_length=8, max_length=400)


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    class_session_id: UUID
    student_user_id: UUID
    state: AttendanceRecordState
    submitted_at: datetime
    verified_at: datetime | None = None
    recorded_at: datetime | None = None
    flagged_reason: str | None = None
    gps_lat: Decimal | None = None
    gps_lon: Decimal | None = None
    gps_distance_m: int | None = None
    face_match: bool
    face_confidence: Decimal
    qr_token_jti: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Session live feed (teacher) ─────────────────────────────────────────────
class SessionFeedRow(BaseModel):
    student_user_id: UUID
    student_name: str
    student_email: str
    record: AttendanceRecordOut | None = None


class SessionFeed(BaseModel):
    session: ClassSessionOut
    rows: list[SessionFeedRow]
    counts: dict[str, int]  # state → count, plus "absent"


# ── Override ────────────────────────────────────────────────────────────────
class OverrideRequest(BaseModel):
    """Narrow override semantics:

    - On an existing record: only flagged → recorded is permitted.
    - On a missing record (student never submitted): to_state must be
      recorded and `student_user_id` identifies who to credit.
    """

    to_state: AttendanceRecordState
    reason: str = Field(min_length=3, max_length=400)
    student_user_id: UUID | None = None  # required when creating a record from absence


class OverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    class_session_id: UUID
    attendance_record_id: UUID | None = None
    student_user_id: UUID
    from_state: AttendanceRecordState | None = None
    to_state: AttendanceRecordState
    reason: str
    overridden_by_user_id: UUID
    created_at: datetime


# ── Report ──────────────────────────────────────────────────────────────────
class AttendanceReportRow(BaseModel):
    student_user_id: UUID
    student_name: str
    student_email: str
    section_id: UUID
    section_name: str
    course_offering_id: UUID
    course_code: str
    course_title: str
    total_sessions: int
    recorded: int
    flagged: int
    absent: int
    percentage: float


class AttendanceReport(BaseModel):
    batch_id: UUID
    from_date: date | None
    to_date: date | None
    generated_at: datetime
    rows: list[AttendanceReportRow]
