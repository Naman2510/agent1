"""The voice WebSocket endpoint itself: handshake auth, framing, and quota.

The session's behaviour is covered in test_voice_session.py through its Transport seam. What is
tested here is the endpoint — the things only a real connection exercises: subprotocol
authentication, frame validation, and the guards that run before `accept`.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, decode_access_token
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


def test_a_configured_voice_that_is_not_installed_stops_the_server_starting(
    settings, _migrated_schema, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Not the first student's first answer (ADR-0018): the voice is built once at startup."""
    import fakeredis.aioredis

    import app.main as main_module
    from app.main import create_app
    from app.providers.tts import espeak

    monkeypatch.setattr(
        main_module,
        "create_redis",
        lambda _settings: fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    monkeypatch.setattr(espeak.shutil, "which", lambda _name: None)
    application = create_app(settings.model_copy(update={"tts_provider": "espeak"}))
    with pytest.raises(espeak.EspeakNotInstalledError), TestClient(application):
        pass


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


def test_a_control_field_of_the_wrong_type_is_reported_without_dropping_the_session(
    sync_client: TestClient,
) -> None:
    """Every control frame's fields are checked (SECURITY.md §6), and, like a malformed audio frame,
    a bad one is a client bug: reported, and the conversation goes on."""
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        for bad in (
            {"type": "playback.ack", "turn_id": "zero", "played_ms": 10},
            {"type": "playback.ack", "turn_id": 0, "played_ms": True},
            {"type": "user.interrupt", "turn_id": [1]},
        ):
            ws.send_text(json.dumps(bad))
            error = json.loads(ws.receive_text())
            assert error["code"] == "bad_control", bad
        ws.send_text(json.dumps({"type": "definitely.not.a.thing"}))
        assert json.loads(ws.receive_text())["code"] == "unknown_control", "still listening"


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


def _short_lived_token(settings, token: str, ttl_seconds: int = 2) -> tuple[str, float]:  # type: ignore[no-untyped-def]
    """A token for the same user as `token`, expiring in `ttl_seconds`."""
    claims = decode_access_token(settings, token)
    brief, _ = create_access_token(
        settings.model_copy(update={"access_token_ttl_seconds": ttl_seconds}),
        user_id=uuid.UUID(claims["sub"]),
        role=claims["role"],
        student_id=uuid.UUID(claims["sid"]),
    )
    return brief, float(decode_access_token(settings, brief)["exp"])


def _sleep_past(epoch_seconds: float) -> None:
    time.sleep(max(0.0, epoch_seconds - time.time()) + 0.3)


def test_a_connection_lasts_only_as_long_as_its_latest_token(
    sync_client: TestClient, settings
) -> None:  # type: ignore[no-untyped-def]
    """Revocation must reach live sockets (ARCHITECTURE §10). A revoked account cannot refresh, so
    bounding the connection by its newest access token cuts it off within one token lifetime —
    where before, it kept talking for the full hour."""
    headers, session_id = _register(sync_client)
    brief, expires_at = _short_lived_token(settings, headers["Authorization"].split()[1])

    with _connect(sync_client, session_id, brief) as ws:
        ws.receive_text()
        ws.receive_text()
        _sleep_past(expires_at)
        # A live socket answers an unknown frame with an error; this one must not answer at all.
        ws.send_text(encode_control("no.such.frame"))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason == "credential expired"


def test_reauth_with_a_fresh_token_keeps_the_connection_alive(
    sync_client: TestClient, settings
) -> None:  # type: ignore[no-untyped-def]
    headers, session_id = _register(sync_client)
    fresh = headers["Authorization"].split()[1]
    brief, expires_at = _short_lived_token(settings, fresh)

    with _connect(sync_client, session_id, brief) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_text(encode_control("session.reauth", access_token=fresh))
        _sleep_past(expires_at)
        # Still open: an unknown control frame gets an error reply rather than a closed socket.
        ws.send_text(encode_control("no.such.frame"))
        assert json.loads(ws.receive_text())["code"] == "unknown_control"


def test_another_accounts_token_cannot_extend_a_connection(
    sync_client: TestClient, settings
) -> None:  # type: ignore[no-untyped-def]
    headers, session_id = _register(sync_client)
    brief, expires_at = _short_lived_token(settings, headers["Authorization"].split()[1])
    stranger, _ = _register(sync_client, prefix="stranger")

    with _connect(sync_client, session_id, brief) as ws:
        ws.receive_text()
        ws.receive_text()
        ws.send_text(
            encode_control("session.reauth", access_token=stranger["Authorization"].split()[1])
        )
        assert json.loads(ws.receive_text())["code"] == "reauth_failed"
        _sleep_past(expires_at)
        # A live socket answers an unknown frame with an error; this one must not answer at all.
        ws.send_text(encode_control("no.such.frame"))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.reason == "credential expired"


@pytest.fixture
def sync_client_one_db_connection(settings, _migrated_schema, monkeypatch):  # type: ignore[no-untyped-def]
    """The real application with a database pool of exactly one connection."""
    import fakeredis.aioredis

    import app.main as main_module
    from app.main import create_app

    monkeypatch.setattr(
        main_module,
        "create_redis",
        lambda _settings: fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    one = settings.model_copy(update={"database_pool_size": 1, "database_max_overflow": 0})
    with TestClient(create_app(one)) as client:
        yield client


def test_connected_students_hold_no_database_connection_while_idle(
    sync_client_one_db_connection: TestClient,
) -> None:
    """Under load, a worker admitted exactly as many students as its database pool held (15): each
    connection's pre-accept lookups kept a pooled connection until its first turn committed, and
    the next student timed out in the handshake (docs/LOAD.md). With a pool of one, three students
    connect, and stay connected, side by side."""
    import contextlib

    client = sync_client_one_db_connection
    students = [_register(client, f"pool{i}") for i in range(3)]
    with contextlib.ExitStack() as stack:
        for headers, session_id in students:
            token = headers["Authorization"].removeprefix("Bearer ")
            ws = stack.enter_context(_connect(client, session_id, token))
            assert json.loads(ws.receive_text())["state"] == "listening"
            assert json.loads(ws.receive_text())["type"] == "ready"


def test_a_connection_is_metered_even_after_a_turn_was_rolled_back(
    sync_client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A turn that breaks mid-query is rolled back (ConversationService.recover), and a rollback
    expires every row the connection's database session had loaded — the student's among them.
    The close read the student's id from that row, failed, and never metered the connection's
    audio; under load it happened ten times in one run (docs/LOAD.md)."""
    from sqlalchemy import text as sql

    from app.services.usage import UsageLedger
    from app.voice.session import VoiceSession

    close = VoiceSession.close

    async def close_after_a_rolled_back_turn(self: VoiceSession) -> None:
        db = self.conversation._db
        assert db is not None
        await db.execute(sql("SELECT 1"))
        await db.rollback()
        await close(self)

    monkeypatch.setattr(VoiceSession, "close", close_after_a_rolled_back_turn)
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")
    state = sync_client.app_state  # type: ignore[attr-defined]
    ledger = UsageLedger(state.redis, state.settings)
    student_id = decode_access_token(state.settings, token)["sid"]

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        for seq in range(150):  # three seconds
            ws.send_bytes(encode_audio(AudioFrame(turn_id=0, seq=seq, pcm=SILENT_FRAME)))
        ws.send_text(encode_control("session.end"))
        used, deadline = 0, time.monotonic() + 5
        while not used and time.monotonic() < deadline:
            time.sleep(0.05)
            used = sync_client.portal.call(ledger.voice_seconds_used, student_id)  # type: ignore[union-attr]
    assert used == 3


def test_audio_sent_faster_than_real_time_is_refused(sync_client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No microphone produces audio faster than time passes, and every 32 ms of it costs a VAD run
    on the one event loop every student shares (docs/LOAD.md). A burst after a network stall is
    allowed for (MAX_AUDIO_AHEAD_MS, lowered here so the test need not send ten seconds)."""
    import contextlib

    import app.ws.voice as voice_ws

    monkeypatch.setattr(voice_ws, "MAX_AUDIO_AHEAD_MS", 1_000)
    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        # Five seconds of audio at once; the server closes part-way, and later sends may fail.
        # The last frame is one only a live session answers, so a session left open fails the
        # test instead of hanging it.
        with contextlib.suppress(Exception):
            for seq in range(250):
                ws.send_bytes(encode_audio(AudioFrame(turn_id=0, seq=seq, pcm=SILENT_FRAME)))
            ws.send_text(json.dumps({"type": "definitely.not.a.thing"}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason == "audio faster than real time"


def test_the_daily_allowance_ends_a_connection_that_uses_it_up(sync_client: TestClient) -> None:
    """Checked only at connect, a connection opened with a minute left could talk for the hour,
    and any number could be open at once. Metered every few seconds of audio, the allowance ends
    the connection that crosses it."""
    from app.services.usage import UsageLedger

    headers, session_id = _register(sync_client)
    token = headers["Authorization"].removeprefix("Bearer ")
    state = sync_client.app_state  # type: ignore[attr-defined]
    state.settings = state.settings.model_copy(update={"rate_limit_voice_minutes_per_day": 1})
    ledger = UsageLedger(state.redis, state.settings)
    student_id = decode_access_token(state.settings, token)["sid"]
    sync_client.portal.call(ledger.record_voice_seconds, student_id, 57)  # type: ignore[union-attr]

    with _connect(sync_client, session_id, token) as ws:
        ws.receive_text()
        ws.receive_text()
        for seq in range(300):  # six seconds: the meter counts five, and 62 s crosses 60
            ws.send_bytes(encode_audio(AudioFrame(turn_id=0, seq=seq, pcm=SILENT_FRAME)))
        # Answered only if the session were still open: then the test fails, rather than hangs.
        ws.send_text(json.dumps({"type": "definitely.not.a.thing"}))
        error = json.loads(ws.receive_text())
        assert error["code"] == "voice_quota_exceeded"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason == "voice_quota_exceeded"
    # 57 + the five seconds heard before the cut-off; the rest was never read.
    assert sync_client.portal.call(ledger.voice_seconds_used, student_id) == 62  # type: ignore[union-attr]
