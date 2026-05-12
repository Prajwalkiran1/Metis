"""Application configuration loaded from environment variables.

Single Settings instance shared across the app — import via `from app.core.config import settings`.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    app_name: str = "Metis API"
    app_env: Literal["dev", "staging", "prod", "test"] = "dev"
    api_v1_prefix: str = "/api/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Database ───────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://metis:metis@localhost:5432/metis",
        description="Async SQLAlchemy DSN. Use `postgresql+asyncpg://...` for Postgres.",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL. Use `memory://` to use fakeredis (dev only).",
    )

    # ── Auth ───────────────────────────────────────────────────────────────
    jwt_secret: SecretStr = Field(
        default=SecretStr("change-me-in-production-please-32+chars"),
        description="HMAC secret for JWT signing. Must be ≥32 chars in production.",
    )
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 15  # 15 min
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    refresh_cookie_name: str = "metis_refresh"
    refresh_cookie_secure: bool = False  # flip to True in prod (HTTPS)
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    login_lockout_max_attempts: int = 5
    login_lockout_window_seconds: int = 60 * 15  # 15 min
    rate_limit_auth_per_minute: int = 5

    # ── Face data encryption (M1: stub stores placeholder; M8 plugs in encoding) ──
    face_encryption_key: SecretStr = Field(
        default=SecretStr("0" * 64),  # 32-byte key in hex; replace per-env
        description="32-byte AES-256-GCM key in hex (64 hex chars).",
    )
    face_key_version: int = 1

    # ── Email backend ──────────────────────────────────────────────────────
    email_backend: Literal["console", "resend"] = "console"
    resend_api_key: SecretStr | None = None
    email_from: str = "noreply@metis.local"

    # ── Web ────────────────────────────────────────────────────────────────
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allowed origins for CORS. Comma-separated in env.",
    )
    web_base_url: str = "http://localhost:3000"

    # ── DPDP / consent ─────────────────────────────────────────────────────
    consent_text_version: str = "v1-2026-05"
    face_enrollment_min_age: int = 18

    # ── Academic / time ────────────────────────────────────────────────────
    # College-local timezone for materialising recurring timetable slots into
    # concrete TIMESTAMPTZ class sessions. Hardcoded until multi-region pilots.
    default_timezone: str = "Asia/Kolkata"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
