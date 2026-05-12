"""Request/response models for the auth endpoints."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access-token expiry
    user_id: UUID
    role: str
    college_id: UUID


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordConfirm(BaseModel):
    otp: str = Field(min_length=4, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=1)


class GenericMessage(BaseModel):
    message: str
