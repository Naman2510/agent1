"""Graceful degradation (Phase 9): what a student gets when each dependency fails.

One section per dependency. Each test takes one thing down — Redis unreachable, a provider that
raises, or one that accepts the request and then never answers — and asserts what the student
sees and hears, and what is recorded. docs/DEGRADATION.md is the matrix these tests pin.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.models import Document, MessageRole
from app.providers.base import ProviderUnavailableError
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import LLMRequest, StreamEvent, TextDelta, ToolCall
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.providers.llm.watchdog import StallGuard
from app.providers.reranker.base import NoopReranker, RerankCandidate, RerankResult
from app.providers.stt.base import FinalTranscript
from app.providers.tts.base import SynthesisRequest
from app.providers.tts.fake import FakeTTSProvider
from app.rag.ingest import DocumentMetadata
from app.rag.retrieve import HybridRetriever, RetrievalConfig
from app.rag.service import RagService
from app.services.conversation import FAILURE_REPLY
from app.voice.session import VoiceSessionConfig
from app.voice.state import TurnState
from tests.integration.test_chat_turn import _mentor_requests, _session, _turn
from tests.integration.test_voice_session import (
    ONE_QUESTION,
    _build,
    _hear,
    _LiveSTT,
    _messages,
)

# A model with a real price, so every turn costs something and the spend counter is written.
PRICED = "claude-sonnet-5"


def _redis_down() -> fakeredis.aioredis.FakeRedis:
    server = fakeredis.FakeServer()
    server.connected = False
    return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)


# --- Redis --------------------------------------------------------------------------------
#
# ARCHITECTURE §13: Redis holds nothing that cannot be rebuilt, so losing it may cost a session's
# live state and the accounting counters — never an answer.


@pytest.mark.parametrize("redis_client", [_redis_down()])
@pytest.mark.parametrize(
    "llm", [FakeLLMProvider([ScriptedTurn(text="KVL: loops sum to zero.")], model=PRICED)]
)
async def test_redis_down_a_typed_turn_is_answered_and_recorded(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "What is KVL?")

    assert [name for name, _ in events if name == "error"] == []
    assert "".join(p["text"] for n, p in events if n == "delta") == "KVL: loops sum to zero."
    assert events[-1][0] == "done"
    stored = await _messages(db_session, uuid.UUID(session_id))
    assert [(m.role, m.content) for m in stored] == [
        (MessageRole.USER, "What is KVL?"),
        (MessageRole.ASSISTANT, "KVL: loops sum to zero."),
    ]


@pytest.mark.parametrize("redis_client", [_redis_down()])
@pytest.mark.parametrize(
    "llm",
    [
        # Every call gets the same answer: the intent gate shares the model, so a script of
        # distinct answers would be consumed out of step with the turns.
        FakeLLMProvider([ScriptedTurn(text="KVL: loops sum to zero.")], model=PRICED)
    ],
)
async def test_redis_down_the_next_turn_still_sees_the_last_one(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:  # type: ignore[no-untyped-def]
    """The short-term window lives in Redis; without it, history comes from Postgres."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    await _turn(client, headers, session_id, "What is KVL?")
    await _turn(client, headers, session_id, "Does it hold for every loop?")

    second = _mentor_requests(llm)[-1]
    said = [m.text for m in second.messages]
    assert "What is KVL?" in said and "KVL: loops sum to zero." in said


@pytest.mark.parametrize("redis_client", [_redis_down()])
async def test_redis_down_the_service_says_degraded_and_keeps_serving(client: AsyncClient) -> None:
    """Readiness takes an instance out of rotation. Doing that for a Redis outage would turn a
    degraded service into no service at all, so only the database makes it unready."""
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": "up", "redis": "down"}


@pytest.mark.parametrize("redis_client", [_redis_down()])
async def test_redis_down_a_spend_cap_does_not_stop_the_mentor(
    client: AsyncClient, registered, auth_headers, app, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    """The cap's counter is in Redis. Refusing every turn while it is unreadable would make an
    accounting outage a product outage; the spend itself is still recorded per message
    (`messages.token_usage`), so nothing is lost but the counter's increments."""
    app.state.usage_ledger._settings = settings.model_copy(update={"monthly_spend_cap_usd": 5.0})
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "What is KVL?")

    assert [name for name, _ in events if name == "error"] == []
    assert events[-1][0] == "done"


async def test_redis_down_a_voice_turn_is_answered_and_recorded(
    db_session: AsyncSession, settings: Settings, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=_redis_down(),
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION,
        llm=FakeLLMProvider([ScriptedTurn(text="Loop ka sum zero hota hai.")], model=PRICED),
    )
    await voice.start()
    for seq in range(100):
        await _hear(voice, seq)
    await voice.wait_for_turn()
    await db_session.commit()

    assert transport.of_type("error") == []
    assert transport.of_type("metrics"), "the turn finished, and said how long it took"
    assert voice.machine.state is TurnState.LISTENING
    stored = await _messages(db_session, session_id)
    assert [m.content for m in stored][-1] == "Loop ka sum zero hota hai."


@pytest.fixture
def sync_client_redis_down(settings, _migrated_schema, monkeypatch) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """The real application and lifespan (see test_voice_ws.py), its Redis unreachable."""
    import app.main as main_module
    from app.main import create_app

    monkeypatch.setattr(main_module, "create_redis", lambda _settings: _redis_down())
    with TestClient(create_app(settings)) as client:
        yield client


def test_redis_down_a_voice_connection_still_opens_and_closes_cleanly(
    sync_client_redis_down: TestClient,
) -> None:
    """The daily voice allowance is counted in Redis. Unreadable, it is not enforced — as the
    rate limiter is not — rather than keeping every student out of voice."""
    client = sync_client_redis_down
    email = f"down-{uuid.uuid4().hex[:8]}@example.com"
    registered = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery-staple", "display_name": "S"},
    )
    assert registered.status_code == 201, registered.text
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/v1/sessions", headers=headers, json={"transport": "websocket"})
    session_id = session_id.json()["id"]

    with client.websocket_connect(
        f"/v1/voice/ws?session_id={session_id}", subprotocols=["bearer", token]
    ) as ws:
        assert json.loads(ws.receive_text())["state"] == "listening"
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_text(json.dumps({"type": "session.end"}))


# --- the language model -------------------------------------------------------------------


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLMProvider(
            [
                ScriptedTurn(raise_error=ProviderUnavailableError("upstream down", provider="x")),
                ScriptedTurn(text="Back again: loops sum to zero."),
            ]
        )
    ],
)
async def test_llm_down_a_voice_student_hears_an_apology_and_can_ask_again(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session, llm
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION + ONE_QUESTION,
        llm=llm,
    )
    await voice.start()
    for seq in range(100):
        await _hear(voice, seq)
    await voice.wait_for_turn()

    assert "".join(d["text"] for d in transport.of_type("llm.delta")) == FAILURE_REPLY
    assert tts.requests, "the apology is spoken, not only shown"
    assert voice.machine.state is TurnState.LISTENING

    for seq in range(100, 280):
        await _hear(voice, seq)
    await voice.wait_for_turn()
    assert "".join(d["text"] for d in transport.of_type("llm.delta")).endswith("sum to zero.")


class _Silent(FakeLLMProvider):
    """Accepts the request, then never says anything — an upstream that has hung."""

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        await asyncio.Event().wait()
        yield  # type: ignore[misc]  # pragma: no cover


@pytest.mark.parametrize("llm", [StallGuard(_Silent(), stall_seconds=0.2)])
async def test_llm_that_never_answers_is_given_up_on_with_an_apology(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    """The SDK's timeout (30 s per attempt, three attempts) bounds each read, not the silence a
    student sits through; StallGuard bounds that."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await asyncio.wait_for(_turn(client, headers, session_id, "What is KVL?"), timeout=5)

    assert "".join(p["text"] for n, p in events if n == "delta") == FAILURE_REPLY
    assert events[-1][0] == "done"


async def test_the_stall_guard_passes_a_healthy_stream_through_untouched() -> None:
    inner = FakeLLMProvider([ScriptedTurn(text="Loops sum to zero.")])
    guarded = StallGuard(inner, stall_seconds=5)
    request = LLMRequest(system=[], messages=[])
    events = [event async for event in guarded.stream(request)]
    assert [e for e in events if hasattr(e, "text")]
    assert guarded.info == inner.info
    assert inner.requests == [request]


# --- speech recognition -------------------------------------------------------------------


class _NeverFinishes(_LiveSTT):
    """Hears the whole utterance and then never produces its final transcript."""

    async def transcribe_stream(self, frames, context=None):  # type: ignore[no-untyped-def,override]
        async for _chunk in frames:
            self.chunks += 1
        await asyncio.Event().wait()
        yield FinalTranscript(text="unreachable")  # pragma: no cover


async def test_a_recogniser_that_never_finishes_is_given_up_on_and_the_session_listens_again(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION,
        stt=_NeverFinishes([], final="unused"),
        config=VoiceSessionConfig(ack_grace_ms=0, stt_final_timeout_ms=200),
    )
    await voice.start()

    async def speak() -> None:
        for seq in range(100):
            await _hear(voice, seq)

    await asyncio.wait_for(speak(), timeout=5)

    assert [e["code"] for e in transport.of_type("error")] == ["stt_failed"]
    assert voice.machine.state is TurnState.LISTENING
    assert voice.machine.turn_id == 0


# --- speech synthesis ---------------------------------------------------------------------


class _VoiceLost(FakeTTSProvider):
    """Speaks the first `works` sentences, then fails on every one after."""

    def __init__(self, *, works: int, hang: bool = False) -> None:
        super().__init__()
        self._works = works
        self._hang = hang

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        if len(self.requests) >= self._works:
            self.requests.append(request)
            if self._hang:
                await asyncio.Event().wait()
            raise ProviderUnavailableError("tts down", provider="fake-tts")
        async for audio in super().synthesize_stream(request):
            yield audio


ANSWER = (
    "Kirchhoff's voltage law is about loops. The voltages around a loop sum to zero. That is all."
)


@pytest.mark.parametrize("hang", [False, True], ids=["fails", "hangs"])
async def test_a_voice_that_is_lost_mid_answer_finishes_the_answer_in_text(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session, hang: bool
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    tts = _VoiceLost(works=1, hang=hang)
    voice, transport, _ = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION,
        llm=FakeLLMProvider([ScriptedTurn(text=ANSWER)]),
        tts=tts,
        config=VoiceSessionConfig(ack_grace_ms=0, tts_stall_timeout_ms=200),
    )
    await voice.start()
    for seq in range(100):
        await _hear(voice, seq)
    await asyncio.wait_for(voice.wait_for_turn(), timeout=5)
    await db_session.commit()

    assert "".join(d["text"] for d in transport.of_type("llm.delta")) == ANSWER
    assert [e["code"] for e in transport.of_type("error")] == ["tts_failed"], "said once"
    assert transport.of_type("metrics"), "the turn still finished"
    assert voice.machine.state is TurnState.LISTENING
    stored = await _messages(db_session, session_id)
    answer = stored[-1]
    assert (answer.role, answer.content, answer.was_interrupted) == (
        MessageRole.ASSISTANT,
        ANSWER,
        False,
    ), "the whole answer reached the student: the first sentence aloud, the rest as text"


async def test_a_voice_lost_before_the_first_word_still_delivers_the_answer_in_text(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _ = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION,
        llm=FakeLLMProvider([ScriptedTurn(text=ANSWER)]),
        tts=_VoiceLost(works=0),
    )
    await voice.start()
    for seq in range(100):
        await _hear(voice, seq)
    await voice.wait_for_turn()
    await db_session.commit()

    assert transport.audio == []
    assert "".join(d["text"] for d in transport.of_type("llm.delta")) == ANSWER
    assert [e["code"] for e in transport.of_type("error")] == ["tts_failed"]
    assert voice.machine.state is TurnState.LISTENING
    assert (await _messages(db_session, session_id))[-1].content == ANSWER


# --- retrieval ----------------------------------------------------------------------------


class _EmbedderDown(TfidfSvdEmbeddingProvider):
    """Fitted, so retrieval runs — and then unable to embed a query."""

    async def embed_query(self, text: str) -> list[float]:
        raise ProviderUnavailableError("embedding service unreachable", provider="embeddings")


async def _ingest_kvl(
    db_session: AsyncSession, tmp_path: Path, embeddings: TfidfSvdEmbeddingProvider
) -> None:
    rag = RagService(db_session, embeddings=embeddings, reranker=NoopReranker())
    doc = tmp_path / "kvl.md"
    doc.write_text(
        "# Unit\n\n## 7.1 KVL\n\nKirchhoff's voltage law: voltages around a loop sum to zero.\n\n"
        "## 7.2 KCL\n\nKirchhoff's current law: currents into a node sum to zero.\n",
        encoding="utf-8",
    )
    await rag.ingest_file(doc, DocumentMetadata(title="Degraded KVL Notes", subject="EMT"))
    await db_session.commit()
    await rag.fit_and_embed_all()
    await db_session.commit()


async def test_embeddings_down_retrieval_falls_back_to_the_lexical_arm(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    embeddings = _EmbedderDown()
    await _ingest_kvl(db_session, tmp_path, embeddings)
    try:
        chunks = await HybridRetriever(
            db_session, embeddings=embeddings, reranker=NoopReranker()
        ).retrieve("voltage loop")
        assert chunks, "found by words alone"
        assert chunks[0].content.startswith("Kirchhoff's voltage law")
        assert all(set(c.source_ranks) == {"lexical"} for c in chunks)
    finally:
        await db_session.execute(delete(Document).where(Document.title == "Degraded KVL Notes"))
        await db_session.commit()


class _RerankerDown(NoopReranker):
    @property
    def reranks(self) -> bool:
        return True

    async def rerank(self, query: str, candidates: Sequence[RerankCandidate]) -> list[RerankResult]:
        raise ProviderUnavailableError("reranker unreachable", provider="reranker")


async def test_reranker_down_retrieval_keeps_the_fused_order(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    embeddings = TfidfSvdEmbeddingProvider()
    await _ingest_kvl(db_session, tmp_path, embeddings)
    try:
        config = RetrievalConfig(use_reranker=True)
        fused = await HybridRetriever(
            db_session, embeddings=embeddings, reranker=NoopReranker()
        ).retrieve("voltage loop", config)
        degraded = await HybridRetriever(
            db_session, embeddings=embeddings, reranker=_RerankerDown()
        ).retrieve("voltage loop", config)
        assert degraded and [c.id for c in degraded] == [c.id for c in fused]
        assert all(c.rerank_score is None for c in degraded)
    finally:
        await db_session.execute(delete(Document).where(Document.title == "Degraded KVL Notes"))
        await db_session.commit()


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLMProvider(
            [
                ScriptedTurn(text="question"),  # IntentGate.classify
                ScriptedTurn(
                    tool_calls=[
                        ToolCall(
                            id="c1", name="search_knowledge", arguments={"query": "voltage loop"}
                        )
                    ],
                    stop_reason="tool_use",
                ),
                ScriptedTurn(text="The voltages around a loop sum to zero [1]."),
            ]
        )
    ],
)
async def test_embeddings_down_an_answer_still_finds_and_cites_its_source(
    client: AsyncClient, registered, auth_headers, app, db_session: AsyncSession, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    app.state.embeddings = _EmbedderDown()
    await _ingest_kvl(db_session, tmp_path, app.state.embeddings)
    try:
        _, _, tokens = await registered()
        headers = auth_headers(tokens)
        session_id = await _session(client, headers)

        events = await _turn(client, headers, session_id, "What is KVL?")

        assert [name for name, _ in events if name == "error"] == []
        done = events[-1][1]
        assert done["tool_activity"] == [{"tool_name": "search_knowledge", "ok": True}]
        assert [c["document_title"] for c in done["citations"]] == ["Degraded KVL Notes"]
    finally:
        await db_session.execute(delete(Document).where(Document.title == "Degraded KVL Notes"))
        await db_session.commit()


# --- the database -------------------------------------------------------------------------
#
# The record of truth: without it nothing works, so the goal is an honest refusal — a 503 that
# says "try again", not a 500 that says "we broke" — and readiness that takes the instance out.


@pytest.fixture
async def app_without_database(app, settings: Settings):  # type: ignore[no-untyped-def]
    dead = create_async_engine("postgresql+asyncpg://vaanios:x@127.0.0.1:1/vaanios")
    app.state.engine = dead
    app.state.session_factory = async_sessionmaker(dead, expire_on_commit=False)
    yield app
    await dead.dispose()


async def test_database_down_requests_are_refused_as_unavailable_not_as_a_crash(
    app_without_database, client: AsyncClient
) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/health")).status_code == 200, "alive, if not ready"

    ready = await client.get("/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": "down", "redis": "up"}

    login = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery-staple"}
    )
    assert login.status_code == 503
    assert login.headers["Retry-After"] == "5"
    error = login.json()["error"]
    assert error["code"] == "service_unavailable"
    assert "127.0.0.1" not in error["message"], "nothing about the infrastructure leaks"


class _BreaksMidAnswer(FakeLLMProvider):
    """Streams the first half of an answer, then loses the connection."""

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield TextDelta(text="Kirchhoff's voltage law says the voltages around")
        raise ProviderUnavailableError("connection reset", provider="x")


@pytest.mark.parametrize("llm", [_BreaksMidAnswer()])
async def test_llm_lost_mid_answer_keeps_what_was_said_and_apologises_for_the_rest(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "What is KVL?")

    said = "".join(p["text"] for n, p in events if n == "delta")
    assert said == f"Kirchhoff's voltage law says the voltages around {FAILURE_REPLY}"
    assert events[-1][0] == "done"
    stored = await _messages(db_session, uuid.UUID(session_id))
    assert stored[-1].content == said, "the record is what the student was shown"


async def test_a_database_connection_lost_mid_session_costs_one_turn_not_the_session(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session, engine
) -> None:  # type: ignore[no-untyped-def]
    """A voice connection holds one database session for its whole life. When Postgres drops
    that session's connection — a restart, a failover, a network blip — the turn in flight is
    lost, and the next question must not be lost with it (the class of D8-04)."""
    student_id, session_id = student_and_session
    voice, transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=ONE_QUESTION + ONE_QUESTION,
        llm=FakeLLMProvider([ScriptedTurn(text="Loop ka sum zero hota hai.")]),
    )
    # Held open (no commit), so the admin connection below is a different one from the pool.
    pid = (await db_session.execute(sql("SELECT pg_backend_pid()"))).scalar_one()
    async with engine.connect() as admin:
        await admin.execute(sql("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

    await voice.start()
    for seq in range(100):
        await _hear(voice, seq)
    await voice.wait_for_turn()
    assert [e["code"] for e in transport.of_type("error")] == ["turn_failed"]
    assert voice.machine.state is TurnState.LISTENING

    for seq in range(100, 280):
        await _hear(voice, seq)
    await voice.wait_for_turn()
    assert [e["code"] for e in transport.of_type("error")] == ["turn_failed"], "only the one"
    assert transport.of_type("llm.delta")[-1]["text"]
    await db_session.commit()
    stored = await _messages(db_session, session_id)
    assert [m.content for m in stored][-1] == "Loop ka sum zero hota hai."
