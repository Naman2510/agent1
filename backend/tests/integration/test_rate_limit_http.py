"""Rate limiting as observed over HTTP (SECURITY.md §4)."""

from httpx import AsyncClient

from app.core.config import Settings


async def test_anonymous_login_attempts_are_throttled(
    client: AsyncClient, settings: Settings
) -> None:
    """Blunts credential stuffing: the limit applies to failures, not just successes."""
    payload = {"email": "victim@example.com", "password": "guess-guess-guess"}
    statuses = [
        (await client.post("/auth/login", json=payload)).status_code
        for _ in range(settings.rate_limit_anonymous_per_min + 1)
    ]
    assert statuses[-1] == 429
    assert statuses.count(429) == 1, "exactly the request past the limit should be refused"


async def test_a_forged_forwarded_for_header_does_not_buy_a_fresh_bucket(
    client: AsyncClient, settings: Settings
) -> None:
    """X-Forwarded-For is only as honest as whoever set it. Read from any caller, rotating it per
    request gave every login attempt its own bucket, and the credential-stuffing limit above never
    engaged. Only a trusted proxy's header counts, and uvicorn already applies exactly that rule
    to `request.client` (FORWARDED_ALLOW_IPS)."""
    payload = {"email": "victim@example.com", "password": "guess-guess-guess"}
    statuses = [
        (
            await client.post(
                "/auth/login", json=payload, headers={"X-Forwarded-For": f"203.0.113.{n}"}
            )
        ).status_code
        for n in range(settings.rate_limit_anonymous_per_min + 1)
    ]
    assert statuses[-1] == 429


async def test_rate_limited_response_carries_retry_after(
    client: AsyncClient, settings: Settings
) -> None:
    payload = {"email": "victim@example.com", "password": "guess-guess-guess"}
    for _ in range(settings.rate_limit_anonymous_per_min):
        await client.post("/auth/login", json=payload)

    limited = await client.post("/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


async def test_ai_class_is_stricter_than_the_read_class(
    client: AsyncClient, registered, auth_headers, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    """Starting sessions costs money, so it exhausts well before ordinary reads do."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)

    for _ in range(settings.rate_limit_ai_per_min):
        assert (
            await client.post("/sessions", headers=headers, json={"transport": "websocket"})
        ).status_code == 201

    blocked = await client.post("/sessions", headers=headers, json={"transport": "websocket"})
    assert blocked.status_code == 429

    # The student can still read their own history while the expensive path is cooling down.
    assert (await client.get("/sessions", headers=headers)).status_code == 200
