"""Fixtures shared by every test.

Only process-local doubles live here. Anything that needs PostgreSQL is in
`tests/integration/conftest.py`, so the unit suite runs with no database at all — which is what
keeps tier-T0 CI fast and hermetic (EVALUATION.md §6).
"""

import os
import uuid

import fakeredis.aioredis
import pytest

from app.core.config import Settings

TEST_DB_URL = os.environ.get(
    "VAANIOS_TEST_DATABASE_URL",
    "postgresql+asyncpg://vaanios:vaanios@localhost:5432/vaanios_test",
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DB_URL,  # type: ignore[arg-type]
        redis_url="redis://localhost:6379/15",  # type: ignore[arg-type]
        jwt_secret="test-secret-that-is-long-enough-to-pass-validation",
        # Argon2 at production cost would dominate the suite. The real parameters are asserted
        # separately in tests/unit/test_config.py.
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        # No test may reach a paid API. The fake provider is the only one wired up.
        llm_provider="fake",
        llm_refusal_fallback_model="",
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture
def redis_client() -> fakeredis.aioredis.FakeRedis:
    """An in-process Redis.

    fakeredis executes the rate limiter's Lua script faithfully, which is the part whose
    behaviour matters; a real server would add a dependency for no extra coverage.
    """
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def unique_email(prefix: str = "student") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def auth_headers():  # type: ignore[no-untyped-def]
    def _headers(tokens: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    return _headers
