"""FastAPI router for M4 — marks service.

Conventions mirror M2/M3:
- Writes generally require teacher or admin; lock-unlock + guardian-link
  endpoints are admin-only.
- Reads require an authenticated user; tenant filter and access control
  happen in the service layer via `actor.college_id` and role.
- Service errors → HTTPException via `_to_http(...)`, same pattern as
  `app/modules/academic/router.py`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.core.db import SessionDep
from app.core.deps import (
    CurrentUser,
    require_admin,
    require_teacher_or_admin,
)
from app.modules.marks import service
from app.modules.marks.models import (
    AssessmentState,
    AssessmentType,
)
from app.modules.marks.schemas import (
    AssessmentCreate,
    AssessmentLockRequest,
    AssessmentOut,
    AssessmentPatch,
    AssessmentRosterRow,
    AssessmentStats,
    GradeRuleSet,
    GuardianLinkCreate,
    GuardianLinkOut,
    MarkAuditEntry,
    MarkBulkResponse,
    MarkEntry,
    MarkOut,
    Page,
    ParentMarksView,
    StudentMarksHistory,
    StudentSummary,
)
from app.modules.users.models import User

router = APIRouter(tags=["marks"])


def _to_http(exc: service.MarksError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


# ── Assessments ─────────────────────────────────────────────────────────────
@router.post("/assessments", response_model=AssessmentOut, status_code=201)
async def create_assessment(
    body: AssessmentCreate,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> AssessmentOut:
    try:
        a = await service.create_assessment(session, actor=actor, payload=body)
    except service.MarksError as e:
        raise _to_http(e) from e
    return AssessmentOut.model_validate(a)


@router.get("/assessments", response_model=Page[AssessmentOut])
async def list_assessments(
    session: SessionDep,
    actor: CurrentUser,
    course_offering_id: UUID | None = None,
    type: AssessmentType | None = None,
    state: AssessmentState | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AssessmentOut]:
    items, total = await service.list_assessments(
        session,
        actor=actor,
        course_offering_id=course_offering_id,
        assessment_type=type,
        state=state,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return Page[AssessmentOut](
        items=[AssessmentOut.model_validate(a) for a in items], total=total
    )


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
async def get_assessment(
    assessment_id: UUID, session: SessionDep, actor: CurrentUser
) -> AssessmentOut:
    try:
        a = await service.get_assessment(
            session, actor=actor, assessment_id=assessment_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return AssessmentOut.model_validate(a)


@router.patch("/assessments/{assessment_id}", response_model=AssessmentOut)
async def patch_assessment(
    assessment_id: UUID,
    body: AssessmentPatch,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> AssessmentOut:
    try:
        a = await service.patch_assessment(
            session, actor=actor, assessment_id=assessment_id, payload=body
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return AssessmentOut.model_validate(a)


@router.delete("/assessments/{assessment_id}", status_code=204)
async def delete_assessment(
    assessment_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> None:
    try:
        await service.delete_assessment(
            session, actor=actor, assessment_id=assessment_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e


@router.patch("/assessments/{assessment_id}/lock", response_model=AssessmentOut)
async def lock_assessment(
    assessment_id: UUID,
    body: AssessmentLockRequest,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> AssessmentOut:
    try:
        a = await service.lock_assessment(
            session,
            actor=actor,
            assessment_id=assessment_id,
            lock=body.lock,
            reason=body.reason,
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return AssessmentOut.model_validate(a)


@router.get(
    "/assessments/{assessment_id}/roster",
    response_model=list[AssessmentRosterRow],
)
async def assessment_roster(
    assessment_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> list[AssessmentRosterRow]:
    try:
        return await service.get_assessment_roster(
            session, actor=actor, assessment_id=assessment_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e


@router.get("/assessments/{assessment_id}/stats", response_model=AssessmentStats)
async def assessment_stats(
    assessment_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> AssessmentStats:
    try:
        s = await service.get_assessment_stats(
            session, actor=actor, assessment_id=assessment_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return s


# ── Marks ───────────────────────────────────────────────────────────────────
@router.put("/marks/{assessment_id}/{student_user_id}", response_model=MarkOut)
async def set_mark(
    assessment_id: UUID,
    student_user_id: UUID,
    body: MarkEntry,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> MarkOut:
    try:
        m = await service.set_mark(
            session,
            actor=actor,
            assessment_id=assessment_id,
            student_user_id=student_user_id,
            payload=body,
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return MarkOut.model_validate(m)


@router.put("/marks/bulk", response_model=MarkBulkResponse)
async def bulk_set_marks(
    session: SessionDep,
    assessment_id: UUID = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    actor: User = Depends(require_teacher_or_admin),
) -> MarkBulkResponse:
    try:
        csv_bytes = await file.read()
        r = await service.bulk_set_marks(
            session,
            actor=actor,
            assessment_id=assessment_id,
            csv_bytes=csv_bytes,
            dry_run=dry_run,
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return r


@router.get(
    "/marks/{student_user_id}/history", response_model=StudentMarksHistory
)
async def student_history(
    student_user_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
    course_offering_id: UUID | None = None,
) -> StudentMarksHistory:
    try:
        h = await service.get_student_marks_history(
            session,
            actor=actor,
            student_user_id=student_user_id,
            course_offering_id=course_offering_id,
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return h


@router.get(
    "/marks/{mark_id}/audit",
    response_model=list[MarkAuditEntry],
)
async def mark_audit(
    mark_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> list[MarkAuditEntry]:
    try:
        rows = await service.get_mark_audit(
            session, actor=actor, mark_id=mark_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return [MarkAuditEntry.model_validate(r) for r in rows]


# ── Grade rules ─────────────────────────────────────────────────────────────
@router.get("/grade-rules", response_model=GradeRuleSet)
async def get_grade_rules(
    session: SessionDep,
    actor: CurrentUser,
    course_offering_id: UUID = Query(...),
) -> GradeRuleSet:
    try:
        r = await service.get_grade_rules(
            session, actor=actor, course_offering_id=course_offering_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    return r


@router.put("/grade-rules", response_model=GradeRuleSet)
async def upsert_grade_rules(
    body: GradeRuleSet,
    session: SessionDep,
    actor: User = Depends(require_teacher_or_admin),
) -> GradeRuleSet:
    try:
        r = await service.upsert_grade_rules(session, actor=actor, payload=body)
    except service.MarksError as e:
        raise _to_http(e) from e
    return r


# ── Parent / guardian ───────────────────────────────────────────────────────
@router.get("/parent/children", response_model=list[StudentSummary])
async def parent_children(
    session: SessionDep, actor: CurrentUser
) -> list[StudentSummary]:
    try:
        return await service.list_parent_children(session, actor=actor)
    except service.MarksError as e:
        raise _to_http(e) from e


@router.get("/parent/marks", response_model=ParentMarksView)
async def parent_marks(
    session: SessionDep, actor: CurrentUser
) -> ParentMarksView:
    try:
        return await service.get_parent_marks_view(session, actor=actor)
    except service.MarksError as e:
        raise _to_http(e) from e


@router.post(
    "/admin/guardian-links",
    response_model=dict,
    status_code=201,
)
async def admin_create_guardian_link(
    body: GuardianLinkCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> dict:
    try:
        link, initial_password = await service.create_guardian_link(
            session, actor=actor, payload=body
        )
    except service.MarksError as e:
        raise _to_http(e) from e
    out: dict = {"link": GuardianLinkOut.model_validate(link).model_dump(mode="json")}
    if initial_password is not None:
        out["parent_initial_password"] = initial_password
    return out


@router.delete("/admin/guardian-links/{link_id}", status_code=204)
async def admin_delete_guardian_link(
    link_id: UUID,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> None:
    try:
        await service.delete_guardian_link(
            session, actor=actor, link_id=link_id
        )
    except service.MarksError as e:
        raise _to_http(e) from e
