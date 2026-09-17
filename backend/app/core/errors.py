"""Uniform, non-leaking error surface (API.md § Conventions).

Clients receive a stable machine code and a safe message; detail stays in the logs, correlated by
request_id. A stack trace or a SQL fragment must never reach a response body.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for errors that are safe to describe to a client."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(self, message: str | None = None, **extra: Any) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.extra = extra


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication required."


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    # Deliberately identical for an unknown email and a wrong password: distinguishing them is a
    # user-enumeration oracle.
    message = "Email or password is incorrect."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have access to this resource."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The resource already exists."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _body(code: str, message: str, request: Request) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after)
        log.info("request.rejected", code=exc.code, status=exc.status_code, **exc.extra)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, request),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's error list can echo submitted values, so only the field locations are
        # returned; the full error is logged.
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        log.info("request.invalid", fields=fields)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "fields": fields,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "unauthenticated",
            403: "permission_denied",
            404: "not_found",
            405: "method_not_allowed",
        }
        code = codes.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(status_code=exc.status_code, content=_body(code, message, request))

    @app.exception_handler(SQLAlchemyError)
    async def _db(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # A database error message can contain table names, constraint names and values.
        log.error("db.error", error_type=type(exc).__name__, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", "An internal error occurred.", request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("request.unhandled", error_type=type(exc).__name__, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", "An internal error occurred.", request),
        )
