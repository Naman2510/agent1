"""The voice WebSocket endpoint itself: handshake auth, framing, and quota.

The session's behaviour is covered in test_voice_session.py through its Transport seam. What is
tested here is the endpoint — the things only a real connection exercises: subprotocol
authentication, frame validation, and the guards that run before `accept`.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.voice.audio import FRAME_BYTES, AudioFrame, bytes_to_ms
from app.voice.protocol import decode_audio, encode_audio, encode_control

SILENT_FRAME = b"\x00" * FRAME_BYTES


@pytest.fixture
def sync_client(settings, _migrated_schema, monkeypatch):  # type: ignore[no-untyped-def]
    """A synchronous client, because Starlette's WebSocket test support is sync-only.

    Built deliberately differently from the async fixtures: `TestClient` runs the application in
    its own event loop on another thread, and asyncpg connections are bound to the loop that
    created them. So the app's engine and Redis client must be created *inside* that loop, which
    means letting the real lifespan build them rather than injecting the session-scoped doubles.

    Only Redis is substituted, by patching its factory so the fake is constructed in the right
    loop. The database is the real test database, already migrated.
    """
    import fakeredis.aioredis

    import app.main as main_module
    from app.main import create_app

    monkeypatch.setattr(
        main_module,
        "create_redis",
        lambda _settings: fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    application = create_app(settings)
    with TestClient(application) as client:
        client.app_state = application.state  # type: ignore[attr-defined]
        yield client


def _register(client: TestClient, prefix: str = "ws") -> tuple[dict[str, str], str]:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "display_name": "WS Student",
        },
    )
    assert response.status_code == 201, response.text
    tokens = response.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    session = client.post("/v1/sessions", headers=headers, json={"transport": "websocket"})
    assert session.status_code == 201, session.text
    return headers, session.json()["id"]


def _connect(client: TestClient, session_id: str, token: str):  # type: ignore[no-untyped-def]
    # The browser WebSocket API cannot set Authorization, and a token in the query string lands in
    # access logs, so the credential rides the subprotocol header (ARCHITECTURE §10).
    return client.websocket_connect(
        f"/v1/voice/ws?session_id={session_id}",
        subprotocols=["bearer", token],
    )


def test_a_valid_handshake_is_accepted_and_announces_the_audio_contract(
    sync_client: TestClient,
) -> None:
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        first = json.loads(ws.receive_text())
        assert first == {"type": "state", "state": "listening", "turn_id": 0}
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        # The client cannot guess the framing; the server states it.
        assert ready["sample_rate"] == 16_000
        assert ready["frame_ms"] == 20
        assert ready["tts_sample_rate"] > 0


def test_a_connection_without_a_credential_is_refused(sync_client: TestClient) -> None:
    _, session_id = _register(sync_client)
    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/v1/voice/ws?session_id={session_id}") as ws,
    ):
        ws.receive_text()


def test_a_forged_token_is_refused(sync_client: TestClient) -> None:
    _, session_id = _register(sync_client)
    with pytest.raises(WebSocketDisconnect), _connect(sync_client, session_id, "not-a-jwt") as ws:
        ws.receive_text()


def test_another_students_session_cannot_be_opened(sync_client: TestClient) -> None:
    """The same rule as the HTTP surface: absent and not-yours are indistinguishable."""
    _alice_headers, alice_session = _register(sync_client, "alice")
    mallory_headers, _mallory_session = _register(sync_client, "mallory")
    mallory_token = mallory_headers["Authorization"].removeprefix("Bearer ")

    with (
        pytest.raises(WebSocketDisconnect),
        _connect(sync_client, alice_session, mallory_token) as ws,
    ):
        ws.receive_text()


def test_an_unknown_session_id_is_refused(sync_client: TestClient) -> None:
    headers, _ = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")
    with pytest.raises(WebSocketDisconnect), _connect(sync_client, str(uuid.uuid4()), token) as ws:
        ws.receive_text()


def test_a_malformed_audio_frame_is_reported_without_dropping_the_session(
    sync_client: TestClient,
) -> None:
    """A bad frame is a client bug; killing the conversation over it would be worse."""
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()  # state
        ws.receive_text()  # ready

        ws.send_bytes(b"\x00\x00\x00")  # shorter than the header
        error = json.loads(ws.receive_text())
        assert error["type"] == "error"
        assert error["code"] == "bad_frame"

        # Still alive: a well-formed frame is accepted afterwards.
        ws.send_bytes(encode_audio(AudioFrame(turn_id=0, seq=0, pcm=SILENT_FRAME)))
        ws.send_text(encode_control("session.end"))


def test_an_oversized_audio_message_is_rejected(sync_client: TestClient) -> None:
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_bytes(b"\x00" * (FRAME_BYTES * 10))
        error = json.loads(ws.receive_text())
        assert error["code"] == "frame_too_large"


def test_a_malformed_control_frame_is_reported(sync_client: TestClient) -> None:
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_text("{not json")
        error = json.loads(ws.receive_text())
        assert error["code"] == "bad_control"


def test_an_unknown_control_type_is_reported(sync_client: TestClient) -> None:
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_text(json.dumps({"type": "definitely.not.a.thing"}))
        error = json.loads(ws.receive_text())
        assert error["code"] == "unknown_control"


def test_a_typed_turn_over_the_socket_produces_audio_and_metrics(
    sync_client: TestClient,
) -> None:
    """The typed fallback inside a voice session: noisy room, or no microphone permission."""
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ready = json.loads(ws.receive_text())
        ws.send_text(encode_control("user.text", text="Kirchhoff ka voltage law samjhao"))

        saw_audio = False
        metrics = None
        received = 0
        # Generous: a couple of seconds of synthesised audio is ~100 frames before the final
        # metrics event arrives.
        for _ in range(600):
            message = ws.receive()
            if (data := message.get("bytes")) is not None:
                saw_audio = True
                # A conforming client: play what arrives and acknowledge it (ARCHITECTURE §5.3).
                # The turn stays open until playback drains, so without this the metrics would
                # only arrive after the no-ACK deadline.
                frame = decode_audio(data)
                received += len(frame.pcm)
                played_ms = bytes_to_ms(received, ready["tts_sample_rate"])
                ws.send_text(
                    encode_control("playback.ack", turn_id=frame.turn_id, played_ms=played_ms)
                )
            elif message.get("text") is not None:
                payload = json.loads(message["text"])
                if payload["type"] == "metrics":
                    metrics = payload
                    break
        assert saw_audio, "the mentor must actually speak"
        assert metrics is not None, "the turn must report its stage marks"
        assert "llm_ttft_ms" in metrics["latency_ms"]
        ws.send_text(encode_control("session.end"))


def test_a_reauth_frame_with_a_bad_token_is_reported(sync_client: TestClient) -> None:
    """A long conversation can outlive a 15-minute access token (Gate 0 finding M-08)."""
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_text(encode_control("session.reauth", access_token="expired-nonsense"))
        error = json.loads(ws.receive_text())
        assert error["code"] == "reauth_failed"


def test_a_zero_voice_allowance_closes_the_connection_before_accept(
    sync_client: TestClient,
) -> None:
    """The daily voice meter is the control that actually bounds spend on a voice product.

    A zero allowance is used rather than seeding a counter, so the test exercises the endpoint's
    enforcement path without depending on how the counter is stored.
    """
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    state = sync_client.app_state  # type: ignore[attr-defined]
    state.settings = state.settings.model_copy(update={"rate_limit_voice_minutes_per_day": 0})
    with pytest.raises(WebSocketDisconnect), _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
