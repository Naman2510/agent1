"""Authorization: cross-student access (IDOR) and the admin role gate.

Gate 1 requires an IDOR test per endpoint that takes a resource id.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole


async def _make_session(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/sessions", headers=headers, json={"transport": "websocket"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("GET", "/sessions/{id}"),
        ("GET", "/sessions/{id}/messages"),
        ("POST", "/sessions/{id}/end"),
    ],
)
async def test_one_student_cannot_reach_another_students_session(
    client: AsyncClient, registered, auth_headers, method: str, path_template: str
) -> None:  # type: ignore[no-untyped-def]
    _, _, alice = await registered("alice")
    _, _, mallory = await registered("mallory")

    session_id = await _make_session(client, auth_headers(alice))
    path = path_template.format(id=session_id)

    response = await client.request(method, path, headers=auth_headers(mallory))
    # 404 rather than 403: a 403 would confirm that the session exists.
    assert response.status_code == 404, f"{method} {path} leaked another student's session"
    assert response.json()["error"]["code"] == "not_found"

    # And the owner still has access, so the test is not passing for the wrong reason.
    owner = await client.request(method, path, headers=auth_headers(alice))
    assert owner.status_code == 200


async def test_absent_and_foreign_sessions_are_indistinguishable(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, alice = await registered("alice")
    _, _, mallory = await registered("mallory")
    owned = await _make_session(client, auth_headers(alice))

    foreign = await client.get(f"/sessions/{owned}", headers=auth_headers(mallory))
    missing = await client.get(f"/sessions/{uuid.uuid4()}", headers=auth_headers(mallory))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"] | {
        "request_id": foreign.json()["error"]["request_id"]
    }


async def test_session_listing_is_scoped_to_the_caller(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, alice = await registered("alice")
    _, _, bob = await registered("bob")
    await _make_session(client, auth_headers(alice))
    await _make_session(client, auth_headers(alice))
    await _make_session(client, auth_headers(bob))

    listing = await client.get("/sessions", headers=auth_headers(bob))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1, "listing must not count another student's sessions"


async def test_admin_endpoint_rejects_a_student(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    response = await client.get("/admin/health", headers=auth_headers(tokens))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_admin_endpoint_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/admin/health")).status_code == 401


async def test_admin_endpoint_allows_an_admin(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    email, password, _ = await registered("boss")

    # Promotion happens out of band: there is no HTTP route that grants admin.
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()

    fresh = await client.post("/auth/login", json={"email": email, "password": password})
    response = await client.get("/admin/health", headers=auth_headers(fresh.json()))
    assert response.status_code == 200
    body = response.json()
    assert body["active_sessions"] == 0
    # A metric with no data must say so rather than report a misleading zero.
    assert body["latency"] == "not_measured"


async def test_a_deactivated_account_stops_working_before_token_expiry(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    """The access token is still cryptographically valid; the account check must still reject."""
    email, _, tokens = await registered()
    assert (await client.get("/auth/me", headers=auth_headers(tokens))).status_code == 200

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.is_active = False
    await db_session.commit()

    assert (await client.get("/auth/me", headers=auth_headers(tokens))).status_code == 401
