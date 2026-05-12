"""Request/response schemas for invites."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InviteCreate(BaseModel):
    user_id: UUID  # an existing invited User row created via POST /users


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    expires_at: datetime
    # OTP is intentionally NOT exposed; the user receives it by email.


class InviteAccept(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=4, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
