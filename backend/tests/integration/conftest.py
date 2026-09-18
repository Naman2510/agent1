"""Fixtures for tests that need the real database.

The schema is built by running the actual migrations rather than `Base.metadata.create_all`:
when those two drifted in Phase 1, a create_all suite was green against a schema that existed
nowhere (Gate 1 finding D-02).
"""

import os
import pathlib
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.security import PasswordHasherService
from app.main import create_app
from app.providers.llm.fake import FakeLLMProvider
from app.services.usage import UsageLedger
from tests.conftest import unique_email


@pytest.fixture(scope="session")
def _migrated_schema(settings: Settings) -> None:
    """Build the test schema with the real migrations.

    Run as a subprocess because migrations/env.py owns its own event loop. The schema is dropped
    first rather than downgraded: the database may hold tables from an older revision, and
    `downgrade` only knows how to undo revisions it has a record of.
    """
    env = {
        **os.environ,
        "VAANIOS_DATABASE_URL": str(settings.database_url),
        "VAANIOS_REDIS_URL": str(settings.redis_url),
        "VAANIOS_JWT_SECRET": settings.jwt_secret,
    }
    root = pathlib.Path(__file__).resolve().parents[2]

    def _run(argv: list[str], label: str) -> None:
        result = subprocess.run(  # noqa: S603
            argv, cwd=root, env=env, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            pytest.fail(f"{label} failed:\n{result.stdout}\n{result.stderr}")

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
    """Truncate between tests, so ordering cannot create hidden dependencies."""
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE audit_log, tool_calls, messages, sessions, students, "
                "refresh_tokens, users RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def llm() -> FakeLLMProvider:
    """The scripted LLM the app under test will use. Tests can inspect `llm.requests`."""
    return FakeLLMProvider()


@pytest.fixture
async def app(engine, settings: Settings, redis_client, llm: FakeLLMProvider):  # type: ignore[no-untyped-def]
    """The real application, with the engine, Redis and LLM replaced by test doubles.

    Nothing else is overridden — routes, dependencies, middleware and exception handlers are the
    ones that ship, so broken wiring fails here rather than in production.
    """
    application = create_app(settings)
    application.state.engine = engine
    application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application.state.redis = redis_client
    application.state.hasher = PasswordHasherService(settings)
    application.state.rate_limiter = RateLimiter(redis_client, settings)
    application.state.llm = llm
    application.state.usage_ledger = UsageLedger(redis_client, settings)
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/v1") as c:
        yield c


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
