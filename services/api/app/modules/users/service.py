"""User-facing business logic — CRUD, role change, face enrollment."""
from __future__ import annotations

import base64
import csv
import io
import re
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.crypto import encrypt_face_embedding
from app.core.db import utcnow
from app.modules.consents.service import grant_consent
from app.modules.users.models import College, ConsentPurpose, User, UserRole, UserStatus
from app.modules.users.schemas import (
    BulkCsvResponse,
    BulkCsvRowError,
    FaceEnrollRequest,
    UserCreate,
    UserPatch,
)


_USN_RE = re.compile(r"^1BM\d{2}[A-Z]{2}\d{3}$")


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
    email = payload.email.strip().lower()

    # Exact-match domain check against the actor's college. Sub-domains
    # are intentionally rejected — a college can run a separate Metis
    # tenant if it has split mail domains.
    college = await session.get(College, actor.college_id)
    if college is not None:
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain != college.email_domain.lower():
            raise UserError(
                "bad_domain",
                f"email must end with @{college.email_domain}",
                400,
            )

    # Tenant isolation: new users always belong to the actor's college.
    # USN format is enforced by the DB CHECK constraint added in 0009, but
    # a friendlier error here saves a round trip through the IntegrityError
    # mapping (which can't tell unique-violation from check-violation apart).
    if payload.role == UserRole.student and not payload.usn:
        raise UserError(
            "missing_usn",
            "USN is required for students",
            400,
        )

    user = User(
        college_id=actor.college_id,
        email=email,
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
        # Distinguish the known constraints so tests and clients can react.
        msg = str(e.orig).lower() if e.orig is not None else str(e).lower()
        if "users_usn_format" in msg:
            raise UserError(
                "bad_usn_format",
                "USN must match 1BM<YY><DD><RRR> e.g. 1BM23CS001",
                400,
            ) from e
        if "uq_users_usn_per_college_active" in msg:
            raise UserError(
                "usn_in_use", "USN already exists for this college", 409
            ) from e
        if "users_student_usn_required" in msg:
            raise UserError(
                "missing_usn", "USN is required for students", 400
            ) from e
        if "uq_users_college_email_active" in msg or "email" in msg:
            raise UserError(
                "email_in_use",
                "email already exists for this college",
                409,
            ) from e
        # Unknown integrity error — surface as a generic conflict.
        raise UserError("integrity_error", str(e.orig) if e.orig else str(e), 409) from e

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
    hod_of_department_id: UUID | None = None,
) -> User:
    target = await get_user(session, user_id=target_id)
    if target is None:
        raise UserError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise UserError("forbidden", "cross-college access denied", 403)

    if target.role == new_role and target.hod_of_department_id == hod_of_department_id:
        return target

    # HOD requires a department; reject otherwise so the one-HOD-per-dept
    # uniqueness index in 0009 can stay strict (NULLs are distinct).
    if new_role == UserRole.hod and hod_of_department_id is None:
        raise UserError(
            "hod_dept_required",
            "HOD role requires hod_of_department_id",
            400,
        )

    # Departing the HOD role clears the dept assignment.
    new_dept = hod_of_department_id if new_role == UserRole.hod else None

    # Enforce one-HOD-per-dept at the service layer too (the DB uniqueness
    # index lands in 0009 and gives a cleaner error than IntegrityError).
    if new_dept is not None:
        existing = await session.execute(
            select(User.id).where(
                User.hod_of_department_id == new_dept,
                User.deleted_at.is_(None),
                User.id != target.id,
            )
        )
        if existing.first() is not None:
            raise UserError(
                "hod_already_assigned",
                "another active HOD is already assigned to that department",
                409,
            )

    old_role = target.role
    old_dept = target.hod_of_department_id
    target.role = new_role
    target.hod_of_department_id = new_dept
    await write_audit(
        session,
        action="user.role_change",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={
            "role": old_role.value,
            "hod_of_department_id": str(old_dept) if old_dept else None,
        },
        new_value={
            "role": new_role.value,
            "hod_of_department_id": str(new_dept) if new_dept else None,
        },
    )
    await session.commit()
    await session.refresh(target)
    return target


async def change_status(
    session: AsyncSession,
    *,
    actor: User,
    target_id: UUID,
    new_status: UserStatus,
) -> User:
    target = await get_user(session, user_id=target_id)
    if target is None:
        raise UserError("not_found", "user not found", 404)
    if target.college_id != actor.college_id:
        raise UserError("forbidden", "cross-college access denied", 403)
    if target.id == actor.id and new_status != UserStatus.active:
        raise UserError(
            "self_deactivate", "cannot deactivate your own account", 400
        )

    if target.status == new_status:
        return target
    old_status = target.status
    target.status = new_status

    await write_audit(
        session,
        action="user.status_change",
        entity_type="user",
        entity_id=target.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        old_value={"status": old_status.value},
        new_value={"status": new_status.value},
    )
    await session.commit()
    await session.refresh(target)
    return target


async def list_users(
    session: AsyncSession,
    *,
    college_id: UUID,
    role: UserRole | None = None,
    status_: UserStatus | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    """Admin listing with simple filters. Always college-scoped."""
    base = select(User).where(User.college_id == college_id)
    if not include_deleted:
        base = base.where(User.deleted_at.is_(None))
    if role is not None:
        base = base.where(User.role == role)
    if status_ is not None:
        base = base.where(User.status == status_)
    if q:
        q_norm = f"%{q.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(User.email).like(q_norm),
                func.lower(User.name).like(q_norm),
                func.lower(func.coalesce(User.usn, "")).like(q_norm),
            )
        )
    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), int(total)


# ── Bulk CSV onboarding ─────────────────────────────────────────────────────
_ALLOWED_ROLES = {r.value for r in UserRole}


async def bulk_csv_onboard(
    session: AsyncSession,
    *,
    actor: User,
    csv_bytes: bytes,
    dry_run: bool,
) -> BulkCsvResponse:
    """Bulk create users from a CSV upload.

    CSV columns (header row required, case-insensitive):
      email,name,role,usn,phone

    `usn` is required for role=student and rejected for other roles.
    `role` must be one of the UserRole enum values.

    Dry-run validates every row and returns errors but commits nothing.
    Commit inserts every valid row in a single transaction; rows whose
    email already exists in the college are reported under
    `skipped_existing` rather than treated as errors.
    """
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise UserError("bad_encoding", "CSV must be UTF-8 encoded", 400) from e

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise UserError("empty_csv", "CSV has no header row", 400)
    headers = {h.strip().lower() for h in reader.fieldnames}
    required = {"email", "name", "role"}
    missing = required - headers
    if missing:
        raise UserError(
            "missing_columns",
            f"CSV is missing columns: {', '.join(sorted(missing))}",
            400,
        )

    college = await session.get(College, actor.college_id)
    college_domain = (college.email_domain.lower() if college else None)

    # Preload existing emails in the college to detect duplicates without N+1.
    existing_rows = await session.execute(
        select(User.email).where(
            User.college_id == actor.college_id, User.deleted_at.is_(None)
        )
    )
    existing_emails = {row[0].lower() for row in existing_rows.all()}

    errors: list[BulkCsvRowError] = []
    valid_rows: list[dict[str, str]] = []
    seen_in_batch: set[str] = set()
    skipped_existing = 0

    for idx, raw in enumerate(reader, start=2):  # row 1 = header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        email = row.get("email", "").lower()
        name = row.get("name", "")
        role_str = row.get("role", "").lower()
        usn = row.get("usn") or None
        phone = row.get("phone") or None

        if not email:
            errors.append(BulkCsvRowError(row_number=idx, code="missing_email", message="email is required"))
            continue
        if not name:
            errors.append(BulkCsvRowError(row_number=idx, code="missing_name", message="name is required", email=email))
            continue
        if role_str not in _ALLOWED_ROLES:
            errors.append(BulkCsvRowError(
                row_number=idx, code="bad_role",
                message=f"role must be one of: {', '.join(sorted(_ALLOWED_ROLES))}",
                email=email,
            ))
            continue
        if college_domain and email.rsplit("@", 1)[-1] != college_domain:
            errors.append(BulkCsvRowError(
                row_number=idx, code="bad_domain",
                message=f"email must end with @{college_domain}", email=email,
            ))
            continue
        if role_str == "student" and not usn:
            errors.append(BulkCsvRowError(
                row_number=idx, code="missing_usn",
                message="USN is required for students", email=email,
            ))
            continue
        if usn and not _USN_RE.match(usn):
            errors.append(BulkCsvRowError(
                row_number=idx, code="bad_usn_format",
                message="USN must match 1BM<YY><DD><RRR> e.g. 1BM23CS001",
                email=email,
            ))
            continue
        if role_str != "student" and usn:
            errors.append(BulkCsvRowError(
                row_number=idx, code="usn_not_allowed",
                message="USN is only allowed for students", email=email,
            ))
            continue
        if email in seen_in_batch:
            errors.append(BulkCsvRowError(
                row_number=idx, code="duplicate_in_csv",
                message="email appears more than once in this CSV", email=email,
            ))
            continue
        if email in existing_emails:
            skipped_existing += 1
            seen_in_batch.add(email)
            continue
        seen_in_batch.add(email)
        valid_rows.append({
            "email": email, "name": name, "role": role_str,
            "usn": usn or "", "phone": phone or "",
        })

    inserted = 0
    if not dry_run and valid_rows:
        for r in valid_rows:
            user = User(
                college_id=actor.college_id,
                email=r["email"],
                name=r["name"],
                role=UserRole(r["role"]),
                status=UserStatus.invited,
                phone=r["phone"] or None,
                usn=r["usn"] or None,
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError:
                # Race: someone created the same email between the preload and
                # this flush. Roll back this row and count it as skipped.
                await session.rollback()
                skipped_existing += 1
                continue
            inserted += 1

        await write_audit(
            session,
            action="user.bulk_csv_create",
            entity_type="user",
            entity_id=None,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={
                "inserted": inserted,
                "skipped_existing": skipped_existing,
                "errors": len(errors),
            },
        )
        await session.commit()

    return BulkCsvResponse(
        dry_run=dry_run,
        total_rows=len(valid_rows) + len(errors) + skipped_existing,
        valid_rows=len(valid_rows),
        inserted=inserted,
        skipped_existing=skipped_existing,
        errors=errors,
    )


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
