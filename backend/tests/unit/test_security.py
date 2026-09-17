"""Password hashing and token behaviour.

These assert properties that matter, not that functions return non-None.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    PasswordHasherService,
    create_access_token,
    decode_access_token,
    hash_refresh_token,
    new_refresh_token,
)


def test_hash_is_argon2id_and_salted(settings: Settings) -> None:
    hasher = PasswordHasherService(settings)
    first = hasher.hash("same-password-twice")
    second = hasher.hash("same-password-twice")
    assert first.startswith("$argon2id$"), "must be Argon2id, not argon2i or bcrypt"
    assert first != second, "per-hash salt means identical passwords hash differently"
    assert hasher.verify(first, "same-password-twice")
    assert hasher.verify(second, "same-password-twice")


def test_wrong_password_and_garbage_hash_both_fail_closed(settings: Settings) -> None:
    hasher = PasswordHasherService(settings)
    stored = hasher.hash("real-password")
    assert hasher.verify(stored, "wrong-password") is False
    # A corrupted column must not raise out of the auth path; it must simply not authenticate.
    assert hasher.verify("not-a-hash", "real-password") is False
    assert hasher.verify("", "real-password") is False


def test_password_is_not_recoverable_from_hash(settings: Settings) -> None:
    hasher = PasswordHasherService(settings)
    stored = hasher.hash("swordfish")
    assert "swordfish" not in stored


def test_access_token_carries_identity_and_expiry(settings: Settings) -> None:
    user_id, student_id = uuid.uuid4(), uuid.uuid4()
    token, expires_in = create_access_token(
        settings, user_id=user_id, role="student", student_id=student_id
    )
    assert expires_in == settings.access_token_ttl_seconds

    payload = decode_access_token(settings, token)
    assert payload["sub"] == str(user_id)
    assert payload["sid"] == str(student_id)
    assert payload["role"] == "student"
    assert payload["typ"] == "access"


def test_expired_token_is_rejected(settings: Settings) -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "typ": "access",
        "role": "student",
        "exp": int((datetime.now(UTC) - timedelta(seconds=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, token)


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "typ": "access",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
    }
    forged = jwt.encode(payload, "a-different-secret-entirely-long", algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, forged)


def test_unsigned_token_is_rejected(settings: Settings) -> None:
    """The alg=none downgrade attack must not work."""
    payload = {
        "sub": str(uuid.uuid4()),
        "typ": "access",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
    }
    unsigned = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, unsigned)


def test_non_access_token_type_is_rejected(settings: Settings) -> None:
    """A token minted for another purpose must not work as a bearer credential."""
    payload = {
        "sub": str(uuid.uuid4()),
        "typ": "refresh",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, token)


def test_refresh_tokens_are_opaque_high_entropy_and_stored_hashed() -> None:
    raw_a, hash_a = new_refresh_token()
    raw_b, _ = new_refresh_token()
    assert raw_a != raw_b
    assert len(raw_a) >= 43, "at least 256 bits of entropy, base64url-encoded"
    assert raw_a.count(".") == 0, "opaque, not a JWT: revocation must be a database fact"
    assert hash_a == hash_refresh_token(raw_a)
    assert raw_a not in hash_a
