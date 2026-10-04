"""A write is durable before the client hears that it succeeded."""

from __future__ import annotations

from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import User
from tests.conftest import unique_email


async def test_a_write_is_committed_before_its_response_starts(app) -> None:  # type: ignore[no-untyped-def]
    """FastAPI finishes a `yield` dependency *after* the response by default, and each request's
    transaction commits in that teardown — so a client could read a 201 before the row existed.
    The frontend's own follow-up to a registration (GET /auth/me, then a token refresh) raced the
    commit in a real browser, lost, and signed the new student straight back out; and a commit
    failing after the 201 would have been a success report for a write that never happened.
    """
    email = unique_email("durable")
    visible_when_response_started: list[bool] = []

    async def probe(scope: Any, receive: Any, send: Any) -> None:
        async def probing_send(message: Any) -> None:
            if (
                message["type"] == "http.response.start"
                and scope.get("path") == "/v1/auth/register"
            ):
                # A separate connection sees only what has been committed.
                async with app.state.session_factory() as other:
                    found = await other.scalar(select(User).where(User.email == email))
                visible_when_response_started.append(found is not None)
            await send(message)

        await app(scope, receive, probing_send)

    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test/v1") as client:
        response = await client.post(
            "/auth/register",
            json={"email": email, "password": "correct-horse-battery-staple", "display_name": "D"},
        )

    assert response.status_code == 201, response.text
    assert visible_when_response_started == [True]
