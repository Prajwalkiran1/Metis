"""User CRUD + role-change + face-enroll endpoints.

`POST /users` is an admin-only invite-style create: the new user is
inserted with `status=invited` and no password. The invites module
generates the OTP and emails it.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.db import SessionDep
from app.core.deps import CurrentUser, get_client_ip, get_user_agent, require_admin
from app.modules.users import service
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import (
    FaceEnrollRequest,
    RoleChange,
    UserCreate,
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
            session, actor=actor, target_id=user_id, new_role=body.role
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
