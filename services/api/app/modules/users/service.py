"""User-facing business logic — CRUD, role change, face enrollment."""
from __future__ import annotations

import base64
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.crypto import encrypt_face_embedding
from app.core.db import utcnow
from app.modules.consents.service import grant_consent
from app.modules.users.models import ConsentPurpose, User, UserRole, UserStatus
from app.modules.users.schemas import FaceEnrollRequest, UserCreate, UserPatch


class UserError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def create_user(
    session: AsyncSession,
    *,
    actor: User,
    payload: UserCreate,
) -> User:
    # Tenant isolation: new users always belong to the actor's college.
    user = User(
        college_id=actor.college_id,
        email=payload.email.strip().lower(),
        name=payload.name.strip(),
        role=payload.role,
        status=UserStatus.invited,
        phone=payload.phone,
        usn=payload.usn,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise UserError("email_in_use", "email already exists for this college", 409) from e

    await write_audit(
        session,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"email": user.email, "role": user.role.value},
    )
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, *, user_id: UUID) -> User | None:
    row = await session.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return row.scalar_one_or_none()


async def patch_user(
    session: AsyncSession,
    *,
    actor: User,
    target_id: UUID,
    payload: UserPatch,
) -> User:
    if actor.id != target_id and actor.role != UserRole.admin:
        raise UserError("forbidden", "cannot edit another user", 403)

    target = await get_user(session, user_id=target_id)
    if target is None:
        raise UserError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise UserError("forbidden", "cross-college access denied", 403)

    before: dict[str, object] = {}
    after: dict[str, object] = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        before[field] = getattr(target, field)
        setattr(target, field, value)
        after[field] = value

    if not after:
        return target  # nothing changed

    await write_audit(
        session,
        action="user.update",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value=_jsonify(before),
        new_value=_jsonify(after),
    )
    await session.commit()
    await session.refresh(target)
    return target


async def change_role(
    session: AsyncSession,
    *,
    actor: User,
    target_id: UUID,
    new_role: UserRole,
) -> User:
    target = await get_user(session, user_id=target_id)
    if target is None:
        raise UserError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise UserError("forbidden", "cross-college access denied", 403)

    if target.role == new_role:
        return target

    old_role = target.role
    target.role = new_role
    await write_audit(
        session,
        action="user.role_change",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={"role": old_role.value},
        new_value={"role": new_role.value},
    )
    await session.commit()
    await session.refresh(target)
    return target


async def enroll_face(
    session: AsyncSession,
    *,
    actor: User,
    target_id: UUID,
    payload: FaceEnrollRequest,
    ip: str | None,
    user_agent: str | None,
) -> User:
    if actor.id != target_id and actor.role != UserRole.admin:
        raise UserError("forbidden", "cannot enroll another user's face", 403)
    if payload.consent_text_version != settings.consent_text_version:
        raise UserError(
            "consent_version_mismatch",
            f"please accept the latest consent ({settings.consent_text_version})",
            400,
        )

    target = await get_user(session, user_id=target_id)
    if target is None:
        raise UserError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise UserError("forbidden", "cross-college access denied", 403)

    # TODO(M1-hardening): enforce FACE_ENROLLMENT_MIN_AGE against target.dob.
    # Deferred until parental-consent flow is designed.

    if payload.embedding_b64:
        try:
            raw = base64.b64decode(payload.embedding_b64, validate=True)
        except ValueError as e:
            raise UserError("bad_embedding", "embedding must be base64-encoded bytes", 400) from e
    else:
        raw = b"M1-stub-embedding"  # placeholder until M8 face model ships

    target.face_embedding_encrypted = encrypt_face_embedding(raw)
    target.face_key_version = settings.face_key_version
    target.face_enrolled_at = utcnow()

    await grant_consent(
        session,
        user=target,
        purpose=ConsentPurpose.face_enrollment,
        ip=ip,
        user_agent=user_agent,
    )
    await write_audit(
        session,
        action="user.face_enroll",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"key_version": settings.face_key_version},
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    await session.refresh(target)
    return target


def _jsonify(d: dict[str, object]) -> dict[str, object]:
    """Coerce non-JSON-serializable values for the audit log."""
    out: dict[str, object] = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "value"):
            out[k] = v.value
        else:
            out[k] = v
    return out
