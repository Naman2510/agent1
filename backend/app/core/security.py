"""Password hashing and token issuance.

Argon2id for passwords (memory-hard, the current OWASP recommendation) and HS256 JWTs for access
tokens. Refresh tokens are opaque random strings — never JWTs — so that revocation is a database
fact rather than a claim we have to trust.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import AuthenticationError

TokenType = Literal["access"]


class PasswordHasherService:
    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, role: str, student_id: uuid.UUID | None
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "sid": str(student_id) if student_id else None,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Access token is invalid.") from exc
    if payload.get("typ") != "access":
        # A refresh token must not be usable as a bearer credential.
        raise AuthenticationError("Access token is invalid.")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Returns (plaintext, sha256 hash). Only the hash is stored (SECURITY.md §3)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
