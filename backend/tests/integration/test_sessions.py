"""Session lifecycle and transcript reads."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageRole
from app.db.repositories.sessions import MessageRepository


async def test_create_list_and_end_a_session(client: AsyncClient, registered, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)

    created = await client.post(
        "/sessions", headers=headers, json={"transport": "websocket", "client_info": {"ua": "test"}}
    )
    assert created.status_code == 201
    session_id = created.json()["id"]
    assert created.json()["status"] == "active"
    assert created.json()["ended_at"] is None

    ended = await client.post(f"/sessions/{session_id}/end", headers=headers)
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    assert ended.json()["ended_at"] is not None


async def test_ending_twice_is_idempotent(client: AsyncClient, registered, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = (await client.post("/sessions", headers=headers, json={})).json()["id"]

    first = await client.post(f"/sessions/{session_id}/end", headers=headers)
    second = await client.post(f"/sessions/{session_id}/end", headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json()["ended_at"] == first.json()["ended_at"], "the end time must not move"


async def test_messages_are_returned_in_turn_order(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    import uuid as _uuid

    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = _uuid.UUID((await client.post("/sessions", headers=headers, json={})).json()["id"])

    repo = MessageRepository(db_session)
    await repo.append(
        session_id=session_id,
        turn_index=0,
        seq=0,
        role=MessageRole.USER,
        content="KVL kya hai?",
        language="hi-Latn",
    )
    await repo.append(
        session_id=session_id,
        turn_index=0,
        seq=1,
        role=MessageRole.ASSISTANT,
        content="Kirchhoff ka voltage law",
        language="hi-Latn",
        was_interrupted=True,
        spoken_prefix_chars=13,
        unspoken_remainder=" ke mutabik loop ka sum zero hota hai",
    )
    await db_session.commit()

    response = await client.get(f"/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [m["seq"] for m in body] == [0, 1]
    assert body[1]["was_interrupted"] is True
    # The transcript exposes what was spoken; the unspoken tail is debug-only and never returned.
    assert body[1]["content"] == "Kirchhoff ka voltage law"
    assert "unspoken_remainder" not in body[1]


async def test_transport_must_be_a_known_value(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    response = await client.post(
        "/sessions", headers=auth_headers(tokens), json={"transport": "carrier-pigeon"}
    )
    assert response.status_code == 422
