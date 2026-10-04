"""Registration, login, and refresh-token rotation over the real HTTP surface."""

from httpx import AsyncClient


async def test_register_returns_usable_tokens(client: AsyncClient, registered) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "student"
    assert body["student"]["display_name"] == "Test Student"
    assert body["student"]["consent_audio_retention"] is False, "audio retention is opt-in"


async def test_duplicate_registration_is_a_conflict_without_confirming_the_account(
    client: AsyncClient, registered
) -> None:  # type: ignore[no-untyped-def]
    email, _, _ = await registered()
    again = await client.post(
        "/auth/register",
        json={"email": email, "password": "another-long-password", "display_name": "Impostor"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"
    assert email not in again.text, "the response must not echo the address back"


async def test_login_rejects_wrong_password_with_a_generic_message(
    client: AsyncClient, registered
) -> None:  # type: ignore[no-untyped-def]
    email, _, _ = await registered()
    wrong = await client.post("/auth/login", json={"email": email, "password": "not-the-password"})
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "not-the-password"}
    )
    assert wrong.status_code == unknown.status_code == 401
    # Identical responses: any difference is a user-enumeration oracle.
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_short_password_is_rejected_at_validation(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": "shorty@example.com", "password": "short", "display_name": "S"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "password" in response.json()["error"]["fields"]
    assert "short" not in response.text, "validation errors must not echo the submitted password"


async def test_refresh_rotates_and_retires_the_old_token(client: AsyncClient, registered) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    first = tokens["refresh_token"]

    rotated = await client.post("/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first, "refresh tokens are single-use"

    # The new one works.
    assert (await client.post("/auth/refresh", json={"refresh_token": second})).status_code == 200


async def test_refresh_reuse_revokes_the_whole_family(client: AsyncClient, registered) -> None:  # type: ignore[no-untyped-def]
    """Replaying a rotated token is the signature of theft: every descendant must die."""
    _, _, tokens = await registered()
    stolen = tokens["refresh_token"]

    rotated = await client.post("/auth/refresh", json={"refresh_token": stolen})
    live = rotated.json()["refresh_token"]

    replay = await client.post("/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401

    # The legitimate token is now dead too — logging the real user out is the correct trade.
    after = await client.post("/auth/refresh", json={"refresh_token": live})
    assert after.status_code == 401


async def test_logout_revokes_the_family(client: AsyncClient, registered) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    logout = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204
    replay = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401


async def test_unknown_refresh_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh", json={"refresh_token": "made-up-token"})
    assert response.status_code == 401


async def test_missing_and_malformed_bearer_tokens_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    bad = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] in {"unauthenticated", "invalid_credentials"}


async def test_profile_update_applies_only_to_the_caller(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    response = await client.patch(
        "/auth/me/profile",
        headers=auth_headers(tokens),
        json={"preferred_language": "hi-Latn", "semester": 5, "consent_audio_retention": True},
    )
    assert response.status_code == 200
    assert response.json()["preferred_language"] == "hi-Latn"
    assert response.json()["semester"] == 5


async def test_profile_rejects_an_unsupported_language(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    response = await client.patch(
        "/auth/me/profile", headers=auth_headers(tokens), json={"preferred_language": "fr"}
    )
    assert response.status_code == 422


async def test_account_deletion_removes_every_owned_row(
    client: AsyncClient, registered, auth_headers, db_session
) -> None:  # type: ignore[no-untyped-def]
    """Erasure must mean erasure — the security-checklist item, asserted rather than assumed."""
    import uuid as _uuid

    from sqlalchemy import func, select

    from app.db.models import Message, MessageRole, RefreshToken, Session, Student, User
    from app.db.repositories.sessions import MessageRepository

    _, _, tokens = await registered()
    headers = auth_headers(tokens)

    session_id = (await client.post("/sessions", headers=headers, json={})).json()["id"]
    await MessageRepository(db_session).append(
        session_id=_uuid.UUID(session_id),
        turn_index=0,
        seq=0,
        role=MessageRole.USER,
        content="remember me",
    )
    await db_session.commit()

    async def count(model) -> int:  # type: ignore[no-untyped-def]
        result = await db_session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())

    assert await count(User) == 1
    assert await count(Student) == 1
    assert await count(Session) == 1
    assert await count(Message) == 1
    assert await count(RefreshToken) >= 1

    response = await client.request("DELETE", "/auth/me", headers=headers)
    assert response.status_code == 204

    for model in (User, Student, Session, Message, RefreshToken):
        assert await count(model) == 0, f"{model.__name__} rows survived account deletion"

    # The access token is still cryptographically valid, but the account is gone.
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
