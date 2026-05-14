"""FastAPI dependencies shared across modules.

`get_current_user` is the gate every authenticated endpoint passes
through. It validates the JWT, looks up the user, and rejects suspended
or soft-deleted accounts so they can't keep using a still-fresh access
token after their status changes.

`require_role` builds a role-gated dependency on top of it. Use it as
`Depends(require_admin)` or `Depends(require_role(UserRole.teacher))`.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select

from app.core.db import SessionDep
from app.core.security import decode_access_token
from app.modules.users.models import User, UserRole, UserStatus

_bearer = HTTPBearer(auto_error=False)

_CREDS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _CREDS_EXC
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError as e:
        raise _CREDS_EXC from e
    if payload.get("typ") != "access":
        raise _CREDS_EXC
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise _CREDS_EXC from e

    row = await session.execute(select(User).where(User.id == user_id))
    user = row.scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        raise _CREDS_EXC
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"account is {user.status.value}",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed: UserRole):
    """Return a dependency that 403s unless the current user has one of `allowed`."""
    allowed_set = set(allowed)

    async def _dep(user: CurrentUser) -> User:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return user

    return _dep


require_admin = require_role(UserRole.admin)
require_teacher_or_admin = require_role(UserRole.teacher, UserRole.admin)
require_hod = require_role(UserRole.hod)
require_hod_or_admin = require_role(UserRole.hod, UserRole.admin)
# HOD scope includes teaching their own offerings, so any teacher-permitted
# endpoint should accept HOD too.
require_teacher_hod_or_admin = require_role(
    UserRole.teacher, UserRole.hod, UserRole.admin
)


def require_dept_scope(user: User, department_id: UUID) -> None:
    """Raise 403 unless the user can act in the given department.

    Admins pass unconditionally. HODs pass only for their own department.
    Anyone else is rejected; teacher-level dept scope (e.g., own offerings)
    is computed against course_offerings.teacher_user_id, not this helper.
    """
    if user.role == UserRole.admin:
        return
    if user.role == UserRole.hod and user.hod_of_department_id == department_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions for this department",
    )


# ── Request metadata helpers ──────────────────────────────────────────────────
def get_client_ip(request: Request) -> str | None:
    """Best-effort client IP. Trusts `X-Forwarded-For` first hop if present."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:400] if ua else None


def _ensure_role(user: User, allowed: Iterable[UserRole]) -> None:
    if user.role not in set(allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
