"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.logging import TraceIdMiddleware, configure_logging, get_logger
from app.core.ratelimit import limiter
from app.core.redis import close_redis
from app.modules.academic.router import router as academic_router
from app.modules.attendance.router import router as attendance_router
from app.modules.auth.router import router as auth_router
from app.modules.invites.router import router as invites_router
from app.modules.system.router import router as system_router
from app.modules.users.router import router as users_router


async def _rate_limit_handler(request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "limit": str(exc.detail)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger()
    log.info("api.startup", env=settings.app_env, version=app.version)
    yield
    await close_redis()
    log.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Metis backend — module 1 (User & Auth Service).",
        lifespan=lifespan,
        docs_url=f"{settings.api_v1_prefix}/docs",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Order matters: trace-id outermost so every other middleware/log carries it.
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    app.include_router(system_router, prefix=settings.api_v1_prefix)
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(users_router, prefix=settings.api_v1_prefix)
    app.include_router(invites_router, prefix=settings.api_v1_prefix)
    app.include_router(academic_router, prefix=settings.api_v1_prefix)
    app.include_router(attendance_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
