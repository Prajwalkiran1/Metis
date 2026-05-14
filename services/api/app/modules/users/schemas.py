"""Request/response schemas for the users module."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import UserRole, UserStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    college_id: UUID
    email: EmailStr
    name: str
    role: UserRole
    status: UserStatus
    phone: str | None = None
    usn: str | None = None
    hod_of_department_id: UUID | None = None
    dob: datetime | None = None
    profile_photo_url: str | None = None
    face_enrolled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: UserRole
    phone: str | None = Field(default=None, max_length=20)
    usn: str | None = Field(default=None, max_length=40)
    hod_of_department_id: UUID | None = None


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    dob: datetime | None = None
    profile_photo_url: str | None = None  # TODO(M6): proper upload + storage


class RoleChange(BaseModel):
    role: UserRole
    # If the new role is HOD, the dept assignment is required so the
    # one-HOD-per-dept invariant can be enforced at service layer.
    hod_of_department_id: UUID | None = None


class StatusChange(BaseModel):
    status: UserStatus


class UserListItem(BaseModel):
    """Slim row for the admin /users table."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    status: UserStatus
    usn: str | None = None
    hod_of_department_id: UUID | None = None
    phone: str | None = None
    created_at: datetime


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int


class FaceEnrollRequest(BaseModel):
    consent_text_version: str
    # The real FaceNet embedding lands in M8. M1 stores whatever bytes the
    # client posts (typically a stub) so downstream code wires up cleanly.
    embedding_b64: str | None = None


# ── Bulk CSV onboarding ─────────────────────────────────────────────────────
class BulkCsvRowError(BaseModel):
    row_number: int
    code: str
    message: str
    email: str | None = None


class BulkCsvResponse(BaseModel):
    """Response for both dry-run and commit modes."""

    dry_run: bool
    total_rows: int
    valid_rows: int
    inserted: int = 0           # 0 when dry_run=true
    skipped_existing: int = 0
    errors: list[BulkCsvRowError]
