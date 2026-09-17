"""Request correlation and timing."""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request_id, binds it for the duration, and records duration.

    A client-supplied X-Request-ID is echoed so a caller can correlate, but it is never trusted
    for anything else and is length-capped to keep log lines bounded.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")[:64]
        request_id = incoming or uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.error("request.failed", duration_ms=duration_ms)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log.info("request.completed", status=response.status_code, duration_ms=duration_ms)
        return response
