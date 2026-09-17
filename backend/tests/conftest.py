"""Test fixtures.

Two deliberate choices:

* **A real PostgreSQL.** The schema uses enums, JSONB, citext, partial indexes and check
  constraints. SQLite would silently accept things Postgres rejects, so the tests would pass
  against a database the application never runs on.
* **fakeredis, not a real Redis.** The rate limiter's contract is the Lua script's behaviour,
  which fakeredis executes faithfully, and an in-process fake keeps the suite fast and
  hermetic.

`VAANIOS_TEST_DATABASE_URL` points at a throwaway database; `scripts/dev_db.sh` starts one
locally and CI provides a service container.
"""

import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.security import PasswordHasherService
from app.main import create_app

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
        # Argon2 at production cost would dominate the suite; the parameters themselves are
        # asserted separately in tests/unit/test_config.py.
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def _migrated_schema(settings: Settings) -> None:
    """Build the test schema by running the real migrations.

    Not `Base.metadata.create_all`: that builds the schema the *models* describe, while
    production runs the schema the *migrations* build. When those two drifted (the migration set
    server defaults the models did not declare), a create_all suite would have passed against a
    schema that does not exist anywhere. Running alembic here means every test exercises the
    production schema, and a forgotten migration fails the suite.

    Run as a subprocess because migrations/env.py owns its own event loop.
    """
    env = {
        **os.environ,
        "VAANIOS_DATABASE_URL": str(settings.database_url),
        "VAANIOS_REDIS_URL": str(settings.redis_url),
        "VAANIOS_JWT_SECRET": settings.jwt_secret,
    }
    root = pathlib.Path(__file__).resolve().parents[1]

    def _run(argv: list[str], label: str) -> None:
        result = subprocess.run(  # noqa: S603
            argv, cwd=root, env=env, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            pytest.fail(f"{label} failed:\n{result.stdout}\n{result.stderr}")

    # Drop the schema rather than running `alembic downgrade base`: the test database may hold
    # tables from an older revision (or from before alembic was introduced), and downgrade only
    # knows how to undo revisions it has a record of.
    _run([sys.executable, str(root / "scripts" / "reset_schema.py")], "schema reset")
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], "alembic upgrade head")


@pytest.fixture(scope="session")
async def engine(settings: Settings, _migrated_schema: None) -> AsyncIterator[object]:
    eng = create_async_engine(str(settings.database_url), poolclass=None)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine, settings: Settings) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(engine) -> AsyncIterator[None]:  # type: ignore[no-untyped-def]
    """Truncate between tests so ordering cannot create hidden dependencies."""
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE audit_log, tool_calls, messages, sessions, students, "
                "refresh_tokens, users RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def redis_client() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def app(engine, settings: Settings, redis_client):  # type: ignore[no-untyped-def]
    """The real application, with the engine and Redis replaced by test doubles.

    Nothing else is overridden: routes, dependencies, middleware and exception handlers are the
    ones that ship, so a broken dependency wiring fails here rather than in production.
    """
    application = create_app(settings)
    application.state.engine = engine
    application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application.state.redis = redis_client
    application.state.hasher = PasswordHasherService(settings)
    application.state.rate_limiter = RateLimiter(redis_client, settings)
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/v1") as c:
        yield c


# --- helpers ---------------------------------------------------------------


def unique_email(prefix: str = "student") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
async def registered(client: AsyncClient):  # type: ignore[no-untyped-def]
    """Registers a student and returns (email, password, tokens)."""

    async def _register(prefix: str = "student") -> tuple[str, str, dict]:
        email = unique_email(prefix)
        password = "correct-horse-battery-staple"
        response = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "display_name": "Test Student"},
        )
        assert response.status_code == 201, response.text
        return email, password, response.json()

    return _register


@pytest.fixture
def auth_headers():  # type: ignore[no-untyped-def]
    def _headers(tokens: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    return _headers
