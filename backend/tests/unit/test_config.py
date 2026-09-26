"""Configuration invariants, including the production refusals."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[3]

BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
    "jwt_secret": "x" * 32,
}


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "jwt_secret": "too-short"})  # type: ignore[arg-type]


def test_production_refuses_debug() -> None:
    with pytest.raises(ValidationError, match="debug"):
        Settings(**{**BASE, "environment": "production", "debug": True})  # type: ignore[arg-type]


def test_production_refuses_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS"):
        Settings(**{**BASE, "environment": "production", "cors_origins": ["*"]})  # type: ignore[arg-type]


def test_production_refuses_transcript_logging() -> None:
    with pytest.raises(ValidationError, match="log_transcripts"):
        Settings(**{**BASE, "environment": "production", "log_transcripts": True})  # type: ignore[arg-type]


def test_production_refuses_disabled_rate_limiting() -> None:
    with pytest.raises(ValidationError, match="rate limiting"):
        Settings(**{**BASE, "environment": "production", "rate_limit_enabled": False})  # type: ignore[arg-type]


def test_cors_origins_accept_a_comma_separated_string() -> None:
    settings = Settings(**{**BASE, "cors_origins": "http://a.test, http://b.test"})  # type: ignore[arg-type]
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("http://a.test, http://b.test", ["http://a.test", "http://b.test"]),
    ],
)
def test_cors_origins_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: list[str]
) -> None:
    """Through the real environment source. Passing the string as a keyword skipped the JSON
    decoding that source applies to list fields, which rejected both of these values."""
    monkeypatch.setenv("VAANIOS_CORS_ORIGINS", value)
    assert Settings(**BASE).cors_origins == expected  # type: ignore[arg-type]


def test_the_documented_example_configuration_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every value .env.example documents must be one the application accepts. Its CORS line and
    its empty spend cap both failed to parse, so the documented setup could not start."""
    for name in list(os.environ):
        if name.startswith("VAANIOS_"):
            monkeypatch.delenv(name)
    # The example deliberately ships without a usable secret.
    settings = Settings(_env_file=REPO / ".env.example", jwt_secret="x" * 32)  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.monthly_spend_cap_usd is None, "an empty cap means no cap"


def test_argon2_defaults_meet_owasp_guidance() -> None:
    """The test suite lowers these for speed, so the defaults are asserted explicitly."""
    settings = Settings(**BASE)  # type: ignore[arg-type]
    assert settings.argon2_memory_cost_kib >= 19456, "OWASP: at least 19 MiB"
    assert settings.argon2_time_cost >= 2


def test_spend_cap_defaults_to_unset() -> None:
    """Gate 0 M-11: the application must not invent a ceiling it does not enforce."""
    assert Settings(**BASE).monthly_spend_cap_usd is None  # type: ignore[arg-type]
