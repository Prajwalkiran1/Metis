"""Invite endpoints: admin issues, recipient accepts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.db import SessionDep
from app.core.deps import get_client_ip, get_user_agent, require_admin
from app.modules.invites import service
from app.modules.invites.schemas import InviteAccept, InviteCreate, InviteOut
from app.modules.users.models import User
from app.modules.users.schemas import UserOut

router = APIRouter(prefix="/invites", tags=["invites"])


def _to_http(exc: service.InviteError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("", response_model=InviteOut, status_code=201)
async def create(
    request: Request,
    body: InviteCreate,
    session: SessionDep,
    actor: User = Depends(require_admin),
) -> InviteOut:
    try:
        invite, _otp = await service.create_invite(
            session,
            actor=actor,
            user_id=body.user_id,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.InviteError as e:
        raise _to_http(e) from e
    return InviteOut.model_validate(invite)


@router.post("/accept", response_model=UserOut)
async def accept(
    request: Request,
    body: InviteAccept,
    session: SessionDep,
) -> UserOut:
    try:
        user = await service.accept_invite(
            session,
            email=body.email,
            otp=body.otp,
            password=body.password,
            name=body.name,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.InviteError as e:
        raise _to_http(e) from e
    return UserOut.model_validate(user)
