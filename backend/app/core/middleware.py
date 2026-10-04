"""Request correlation, timing, a trace span per request, and the security headers."""

import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import structlog
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.telemetry import tracer

log = structlog.get_logger(__name__)


def route_template(scope: Mapping[str, Any]) -> str | None:
    """The matched route's full template, prefixes included.

    A router included under a prefix matches with its own, shorter template ("/sessions/{id}"),
    and FastAPI keeps the joined one only in private structures. The concrete path ends with the
    leaf template filled in with the path's parameters; what precedes that is the prefix.
    """
    leaf = getattr(scope.get("route"), "path_format", None)
    if not leaf:
        return None
    params = {name: str(value) for name, value in scope.get("path_params", {}).items()}
    try:
        concrete = leaf.format(**params)
    except (KeyError, IndexError, ValueError):
        return str(leaf)
    path = str(scope.get("path", ""))
    if concrete and path.endswith(concrete):
        return path[: len(path) - len(concrete)] + leaf
    return str(leaf)


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
        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "request_id": request_id,
            },
        ) as span:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                log.error("request.failed", duration_ms=duration_ms)
                span.set_status(Status(StatusCode.ERROR))
                raise
            # The route template, once routing has matched one: "/v1/sessions/{session_id}"
            # groups every session's requests; the raw path would make each one unique.
            template = route_template(request.scope)
            if template:
                span.update_name(f"{request.method} {template}")
                span.set_attribute("http.route", template)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log.info("request.completed", status=response.status_code, duration_ms=duration_ms)
        return response


API_CONTENT_POLICY = "default-src 'none'; frame-ancestors 'none'"


def security_headers(*, production: bool) -> dict[str, str]:
    """The headers every API response carries, bar the content policy (`API_CONTENT_POLICY`),
    which the development-only docs page does without."""
    headers = {
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
        "cache-control": "no-store",
    }
    if production:
        headers["strict-transport-security"] = "max-age=63072000; includeSubDomains"
    return headers


class SecurityHeadersMiddleware:
    """The headers every HTTP response carries (SECURITY.md §6).

    The API serves JSON to a client on another origin and never a page, so its content policy
    allows nothing: whatever it returns must not be rendered, framed or run by a browser, and
    must not be cached — every response is someone's data or credentials. A route that sets its
    own value keeps it. The interactive docs, which exist only outside production, render a page
    from a CDN and are left without the content policy. HSTS is sent only in production, where
    TLS is terminated in front of the application; a browser ignores it over plain HTTP anyway.

    A pure ASGI middleware, not `BaseHTTPMiddleware`: it only touches the response's start, so a
    streamed answer (SSE) passes through unbuffered. An unhandled error is answered outside every
    middleware, so its handler sends these itself (app/core/errors.py).
    """

    _DOCS = frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json"})

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self._headers = security_headers(production=production)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = scope["path"] not in self._DOCS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._headers.items():
                    headers.setdefault(name, value)
                if policy:
                    headers.setdefault("content-security-policy", API_CONTENT_POLICY)
            await send(message)

        await self.app(scope, receive, send_with_headers)
