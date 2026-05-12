"""Auth endpoints — `/auth/login`, `/auth/refresh`, `/auth/logout`,
`/auth/reset-password/{request,confirm}`.

Each auth endpoint is rate-limited per-IP via slowapi
(`RATE_LIMIT_AUTH_PER_MINUTE`). The refresh token never appears in the
response body — it's set as an HTTP-only cookie so XSS can't read it.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from app.core.config import settings
from app.core.db import SessionDep
from app.core.deps import CurrentUser, get_client_ip, get_user_agent
from app.core.ratelimit import auth_rate_limit, limiter
from app.core.redis import RedisDep

from . import service
from .schemas import (
    GenericMessage,
    LoginRequest,
    ResetPasswordConfirm,
    ResetPasswordRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/",
        samesite=settings.refresh_cookie_samesite,
    )


def _to_http(exc: service.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.post("/login", response_model=TokenResponse)
@limiter.limit(auth_rate_limit())
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: SessionDep,
    redis: RedisDep,
) -> TokenResponse:
    try:
        tokens = await service.login(
            session,
            redis,
            email=body.email,
            password=body.password,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.AuthError as e:
        raise _to_http(e) from e

    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user_id=tokens.user.id,
        role=tokens.user.role.value,
        college_id=tokens.user.college_id,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(auth_rate_limit())
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    metis_refresh: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> TokenResponse:
    if not metis_refresh:
        raise HTTPException(status_code=401, detail={"code": "no_refresh", "message": "missing refresh cookie"})
    try:
        tokens = await service.rotate_refresh(
            session,
            refresh_token_plain=metis_refresh,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.AuthError as e:
        raise _to_http(e) from e

    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user_id=tokens.user.id,
        role=tokens.user.role.value,
        college_id=tokens.user.college_id,
    )


@router.post("/logout", response_model=GenericMessage)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    user: CurrentUser,
    metis_refresh: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> GenericMessage:
    await service.logout(
        session,
        refresh_token_plain=metis_refresh,
        actor_user_id=user.id,
        ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    _clear_refresh_cookie(response)
    return GenericMessage(message="logged out")


@router.post("/reset-password/request", response_model=GenericMessage)
@limiter.limit(auth_rate_limit())
async def reset_password_request(
    request: Request,
    body: ResetPasswordRequest,
    session: SessionDep,
) -> GenericMessage:
    await service.request_password_reset(
        session,
        email=body.email,
        ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    # Always 200 so callers can't enumerate accounts.
    return GenericMessage(message="if the email exists, a reset link was sent")


@router.post("/reset-password/confirm", response_model=GenericMessage)
@limiter.limit(auth_rate_limit())
async def reset_password_confirm(
    request: Request,
    body: ResetPasswordConfirm,
    session: SessionDep,
) -> GenericMessage:
    try:
        await service.confirm_password_reset(
            session,
            otp=body.otp,
            new_password=body.new_password,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    except service.AuthError as e:
        raise _to_http(e) from e
    return GenericMessage(message="password updated")
