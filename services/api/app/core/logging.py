"""Structured logging + per-request trace ID propagation.

Every request gets an `X-Request-Id` (generated if missing). It's bound to the
structlog context so every log line in that request scope carries `trace_id`,
and is echoed back on the response header so the frontend can surface it in
error toasts for support workflows.
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
TRACE_HEADER = "X-Request-Id"


def _add_trace_id(_logger: object, _name: str, event_dict: dict[str, object]) -> dict[str, object]:
    event_dict["trace_id"] = _trace_id_ctx.get()
    return event_dict


def configure_logging() -> None:
    """Configure structlog + stdlib logging once at app startup."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_trace_id,
        timestamper,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if settings.app_env != "dev"
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level),
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or "metis")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Reads or generates X-Request-Id and binds it to the structlog context."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex
        token = _trace_id_ctx.set(trace_id)
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            response: Response = await call_next(request)
        finally:
            _trace_id_ctx.reset(token)
            structlog.contextvars.unbind_contextvars("trace_id")
        response.headers[TRACE_HEADER] = trace_id
        return response


def current_trace_id() -> str:
    return _trace_id_ctx.get()
