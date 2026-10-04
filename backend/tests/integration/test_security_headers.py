"""The headers every HTTP response carries (SECURITY.md §6)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

EXPECTED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}


async def test_every_api_response_carries_the_security_headers(client: AsyncClient) -> None:
    """A success, a refusal and a route that does not exist alike: the API serves data, never a
    page, so nothing it returns may be rendered, framed, run or cached."""
    for response in (
        await client.get("/health"),
        await client.get("/auth/me"),
        await client.get("/no-such-route"),
    ):
        assert response.status_code in {200, 401, 404}
        for name, value in EXPECTED.items():
            assert response.headers.get(name) == value, (response.url, name)
        # Not outside production: there is no TLS in front of a development server to pin.
        assert "strict-transport-security" not in response.headers


async def test_a_cors_preflight_carries_them_too(client: AsyncClient) -> None:
    """Answered by the CORS middleware before any route runs."""
    response = await client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name


async def test_the_development_docs_page_is_left_without_the_content_policy(
    settings: Settings,
) -> None:
    """Swagger UI is a page that loads from a CDN; the API's policy would blank it. It does not
    exist in production (`docs_url=None`)."""
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        page = await client.get("/docs")
    assert page.status_code == 200
    assert "content-security-policy" not in page.headers
    assert page.headers["x-content-type-options"] == "nosniff"


async def test_production_pins_https(settings: Settings) -> None:
    production = settings.model_copy(
        update={"environment": "production", "cors_origins": ["https://app.example"]}
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(production)), base_url="http://test/v1"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"


async def test_an_unexpected_error_is_generic_and_still_carries_the_headers(
    settings: Settings,
) -> None:
    """Whatever broke — here an exception whose message is SQL — the client sees a code and a
    request id, never the message or a trace. Starlette answers these outside every middleware,
    so the headers are the handler's own."""
    app = create_app(settings)

    async def boom() -> None:
        raise RuntimeError("SELECT password_hash FROM users WHERE email = 'x'")

    app.add_api_route("/v1/boom", boom)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test/v1") as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "SELECT" not in response.text
    assert "Traceback" not in response.text
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name
