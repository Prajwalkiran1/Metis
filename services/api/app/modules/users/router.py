"""User CRUD + role-change + face-enroll endpoints.

`POST /users` is an admin-only invite-style create: the new user is
inserted with `status=invited` and no password. The invites module
generates the OTP and emails it.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.core.db import SessionDep
from app.core.deps import CurrentUser, get_client_ip, get_user_agent, require_admin
from app.modules.users import service
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.schemas import (
    BulkCsvResponse,
    FaceEnrollRequest,
    RoleChange,
    StatusChange,
    UserCreate,
    UserListItem,
    UserListResponse,
    UserOut,
    UserPatch,
)

router = APIRouter(prefix="/users", tags=["users"])


def _to_http(exc: service.UserError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("", response_model=UserOut, status_code=201)
async def create(
    body: UserCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> UserOut:
    try:
        user = await service.create_user(session, actor=actor, payload=body)
    except service.UserError as e:
        raise _to_http(e) from e
    # NOTE: callers typically chain with POST /invites to email an OTP.
    # Done as two calls so the admin can bulk-create without triggering N emails.
    return UserOut.model_validate(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    session: SessionDep,
    actor: User = Depends(require_admin),
    role: UserRole | None = None,
    status_filter: UserStatus | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> UserListResponse:
    """Admin-only paginated user listing. Always scoped to actor's college."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail={"code": "bad_limit", "message": "limit must be 1..200"})
    if offset < 0:
        raise HTTPException(status_code=400, detail={"code": "bad_offset", "message": "offset >= 0"})
    users, total = await service.list_users(
        session,
        college_id=actor.college_id,
        role=role,
        status_=status_filter,
        q=q,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return UserListResponse(
        items=[UserListItem.model_validate(u) for u in users],
        total=total,
    )


@router.post("/bulk-csv", response_model=BulkCsvResponse)
async def bulk_csv(
    session: SessionDep,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    actor: User = Depends(require_admin),
) -> BulkCsvResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_file", "message": "CSV file is empty"},
        )
    try:
        return await service.bulk_csv_onboard(
            session, actor=actor, csv_bytes=raw, dry_run=dry_run
        )
    except service.UserError as e:
        raise _to_http(e) from e


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_one(
    user_id: UUID,
    session: SessionDep,
    actor: CurrentUser,
) -> UserOut:
    if actor.id != user_id and actor.role != UserRole.admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "not allowed"})
    target = await service.get_user(session, user_id=user_id)
    if target is None or target.college_id != actor.college_id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "user not found"})
    return UserOut.model_validate(target)


@router.patch("/{user_id}", response_model=UserOut)
async def patch(
    user_id: UUID,
    body: UserPatch,
    session: SessionDep,
    actor: CurrentUser,
) -> UserOut:
    try:
        target = await service.patch_user(session, actor=actor, target_id=user_id, payload=body)
    except service.UserError as e:
        raise _to_http(e) from e
    return UserOut.model_validate(target)


@router.patch("/{user_id}/role", response_model=UserOut)
async def change_role(
    user_id: UUID,
    body: RoleChange,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> UserOut:
    try:
        target = await service.change_role(
            session,
            actor=actor,
            target_id=user_id,
            new_role=body.role,
            hod_of_department_id=body.hod_of_department_id,
        )
    except service.UserError as e:
        raise _to_http(e) from e
    return UserOut.model_validate(target)


@router.patch("/{user_id}/status", response_model=UserOut)
async def change_status(
    user_id: UUID,
    body: StatusChange,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> UserOut:
    try:
        target = await service.change_status(
            session, actor=actor, target_id=user_id, new_status=body.status
        )
    except service.UserError as e:
        raise _to_http(e) from e
    return UserOut.model_validate(target)


@router.post("/{user_id}/face-enroll", response_model=UserOut)
async def face_enroll(
    user_id: UUID,
    body: FaceEnrollRequest,
    request: Request,
    session: SessionDep,
    actor: CurrentUser,
) -> UserOut:
    try:
        target = await service.enroll_face(
            session,
            actor=actor,
            target_id=user_id,
            payload=body,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.UserError as e:
        raise _to_http(e) from e
    return UserOut.model_validate(target)
