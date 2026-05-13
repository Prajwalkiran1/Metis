"""FastAPI router for M3 — attendance service.

Conventions:
- `POST /sessions/{id}/qr` / `POST /sessions/{id}/close`: teacher (owner) or admin
- `POST /attendance/submit`: student, per-IP slowapi-limited
- `GET /attendance/{student_id}`: self (student) or teacher/admin
- `GET /attendance/session/{id}`: teacher (owner) or admin
- `PATCH /attendance/{id}/override`: teacher (owner) or admin
- `GET /attendance/report/{batch_id}`: admin or teacher who teaches at least
  one offering in the batch. CSV by default; ?format=json available.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.db import SessionDep
from app.core.deps import (
    CurrentUser,
    get_client_ip,
    get_user_agent,
    require_teacher_or_admin,
)
from app.core.ratelimit import attendance_submit_rate_limit, limiter
from app.modules.attendance import service
from app.modules.attendance.models import ClassSessionState
from app.modules.attendance.schemas import (
    AttendanceRecordOut,
    AttendanceReport,
    AttendanceSubmit,
    ClassSessionOut,
    OverrideOut,
    OverrideRequest,
    QRTokenOut,
    SessionFeed,
)
from app.modules.users.models import User

router = APIRouter(tags=["attendance"])


def _to_http(exc: service.AttendanceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


# ── Class session lifecycle ─────────────────────────────────────────────────
@router.get("/sessions", response_model=list[ClassSessionOut])
async def list_sessions(
    session: SessionDep,
    actor: CurrentUser,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    state: ClassSessionState | None = None,
) -> list[ClassSessionOut]:
    rows = await service.list_sessions(
        session,
        actor=actor,
        from_date=from_date,
        to_date=to_date,
        state=state,
    )
    return [ClassSessionOut.model_validate(r) for r in rows]


@router.post("/sessions/{session_id}/qr", response_model=QRTokenOut)
async def issue_qr(
    session_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> QRTokenOut:
    try:
        token, qr, _cs = await service.issue_qr_token(
            session, actor=actor, session_id=session_id
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return QRTokenOut(
        token=token,
        jti=qr.jti,
        session_id=qr.class_session_id,
        valid_from=qr.valid_from,
        valid_until=qr.valid_until,
        ttl_seconds=settings.attendance_qr_ttl_seconds,
    )


@router.post("/sessions/{session_id}/close", response_model=ClassSessionOut)
async def close_session(
    session_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> ClassSessionOut:
    try:
        cs = await service.close_session(
            session, actor=actor, session_id=session_id
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return ClassSessionOut.model_validate(cs)


# ── Submit ──────────────────────────────────────────────────────────────────
@router.post("/attendance/submit", response_model=AttendanceRecordOut)
@limiter.limit(attendance_submit_rate_limit())
async def submit_attendance(
    request: Request,
    body: AttendanceSubmit,
    session: SessionDep,
    actor: CurrentUser,
) -> AttendanceRecordOut:
    try:
        record = await service.submit_attendance(
            session,
            actor=actor,
            payload=body,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return AttendanceRecordOut.model_validate(record)


# ── Views ───────────────────────────────────────────────────────────────────
@router.get(
    "/attendance/session/{session_id}", response_model=SessionFeed
)
async def session_feed(
    session_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> SessionFeed:
    try:
        feed = await service.get_session_feed(
            session, actor=actor, session_id=session_id
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return feed


@router.get("/attendance/{student_id}", response_model=list[AttendanceRecordOut])
async def student_attendance(
    student_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    course_offering_id: UUID | None = None,
) -> list[AttendanceRecordOut]:
    try:
        rows = await service.get_student_attendance(
            session,
            actor=actor,
            student_id=student_id,
            from_date=from_date,
            to_date=to_date,
            course_offering_id=course_offering_id,
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return [AttendanceRecordOut.model_validate(r) for r in rows]


# ── Override ────────────────────────────────────────────────────────────────
@router.patch(
    "/attendance/sessions/{session_id}/override",
    response_model=OverrideOut,
)
async def override_attendance_for_session(
    session_id: UUID,
    body: OverrideRequest,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
    record_id: UUID | None = Query(
        None,
        description=(
            "Existing attendance_record to override. Omit when marking a "
            "non-submitting student present manually (supply student_user_id "
            "in the body)."
        ),
    ),
) -> OverrideOut:
    try:
        ov = await service.override_attendance(
            session,
            actor=actor,
            session_id=session_id,
            record_id=record_id,
            payload=body,
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    return OverrideOut.model_validate(ov)


# ── Report ──────────────────────────────────────────────────────────────────
@router.get("/attendance/report/{batch_id}", response_model=None)
async def attendance_report(
    batch_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    format: Literal["csv", "json"] = "csv",
) -> AttendanceReport | StreamingResponse:
    try:
        report = await service.generate_report(
            session,
            actor=actor,
            batch_id=batch_id,
            from_date=from_date,
            to_date=to_date,
        )
    except service.AttendanceError as e:
        raise _to_http(e) from e
    if format == "json":
        return report
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "student_email",
        "student_name",
        "section",
        "course_code",
        "course_title",
        "total_sessions",
        "recorded",
        "flagged",
        "absent",
        "percentage",
    ])
    for row in report.rows:
        w.writerow([
            row.student_email,
            row.student_name,
            row.section_name,
            row.course_code,
            row.course_title,
            row.total_sessions,
            row.recorded,
            row.flagged,
            row.absent,
            f"{row.percentage:.2f}",
        ])
    buf.seek(0)
    filename = f"attendance_{batch_id}.csv"
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
