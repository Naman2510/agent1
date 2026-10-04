"""The turn service directly: cancellation, provider swapping, and history bounds.

The cancellation test is the important one here. It asserts the invariant from Gate 0 finding
C-03 — *what is stored is what the user actually received* — while the thing that makes it matter
(barge-in) does not exist yet. Phase 3 inherits a tested invariant rather than discovering it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent import IntentGate
from app.agent.tools.registry import DEFAULT_REGISTRY
from app.core.config import Settings
from app.db.models import Message, MessageRole, Session, Student, User, UserRole
from app.db.repositories.sessions import MessageRepository
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import ToolCall
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.providers.reranker.base import NoopReranker
from app.rag.ingest import DocumentMetadata
from app.rag.service import RagService
from app.services.conversation import ConversationService
from app.services.usage import UsageLedger


@pytest.fixture
async def student_session(db_session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"svc-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", role=UserRole.STUDENT
    )
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name="Svc")
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()
    return session.id


def _service(
    db_session: AsyncSession,
    settings: Settings,
    redis_client,  # type: ignore[no-untyped-def]
    llm: FakeLLMProvider,
) -> ConversationService:
    return ConversationService(
        llm=llm,
        messages=MessageRepository(db_session),
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
    )


async def _messages(db_session: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    result = await db_session.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.turn_index, Message.seq)
    )
    return list(result.scalars().all())


async def test_abandoning_the_stream_persists_only_what_was_delivered(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """The C-03 invariant.

    The model generates further ahead than the consumer reads. If the full generation were
    stored, the next turn's context would contain text the student never saw, and the mentor
    would refer back to it.
    """
    llm = FakeLLMProvider([ScriptedTurn(text="ONEtwoTHREEfourFIVEsixSEVENeight")], chunk_size=5)
    service = _service(db_session, settings, redis_client, llm)

    stream = service.stream_turn(
        session_id=student_session, student_id=uuid.uuid4(), utterance="explain"
    )

    delivered: list[str] = []
    async for fragment, _result in stream:
        delivered.append(fragment)
        if len(delivered) == 2:
            break  # the consumer goes away mid-answer
    await stream.aclose()
    await db_session.commit()

    rows = await _messages(db_session, student_session)
    assistant = next(r for r in rows if r.role is MessageRole.ASSISTANT)

    assert assistant.was_interrupted is True
    assert assistant.content == "".join(delivered)
    assert assistant.content != "ONEtwoTHREEfourFIVEsixSEVENeight"
    assert assistant.spoken_prefix_chars == len(assistant.content)
    # The record is a prefix of what was generated — never more than was delivered.
    assert "ONEtwoTHREEfourFIVEsixSEVENeight".startswith(assistant.content)


async def test_a_completed_turn_is_not_marked_interrupted(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLMProvider([ScriptedTurn(text="A complete answer.")])
    service = _service(db_session, settings, redis_client, llm)

    result = None
    async for _fragment, maybe in service.stream_turn(
        session_id=student_session, student_id=uuid.uuid4(), utterance="explain"
    ):
        if maybe is not None:
            result = maybe
    await db_session.commit()

    assert result is not None and result.interrupted is False
    assistant = next(
        r for r in await _messages(db_session, student_session) if r.role is MessageRole.ASSISTANT
    )
    assert assistant.was_interrupted is False
    assert assistant.spoken_prefix_chars is None
    assert assistant.content == "A complete answer."


@pytest.mark.parametrize(
    "provider",
    [
        FakeLLMProvider([ScriptedTurn(text="answer from provider A")], model="fake-llm-1"),
        FakeLLMProvider([ScriptedTurn(text="answer from provider B")], model="fake-llm-1"),
    ],
    ids=["provider-a", "provider-b"],
)
async def test_the_same_service_code_runs_against_different_providers(
    db_session: AsyncSession,
    settings: Settings,
    redis_client,  # type: ignore[no-untyped-def]
    student_session: uuid.UUID,
    provider: FakeLLMProvider,
) -> None:
    """Gate 2: swapping a provider must require no application change.

    Identical service code, two provider instances, no branching anywhere in between.
    """
    service = _service(db_session, settings, redis_client, provider)
    text = ""
    async for fragment, result in service.stream_turn(
        session_id=student_session, student_id=uuid.uuid4(), utterance="explain"
    ):
        text += fragment
        if result is not None:
            assert result.cost is not None
            assert result.cost.model == provider.info.model
    assert "answer from provider" in text


async def test_history_is_bounded_by_configuration(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """Every token resent costs money and latency, whatever the context window would allow."""
    repo = MessageRepository(db_session)
    for turn in range(15):
        await repo.append(
            session_id=student_session,
            turn_index=turn,
            seq=0,
            role=MessageRole.USER,
            content=f"question {turn}",
        )
        await repo.append(
            session_id=student_session,
            turn_index=turn,
            seq=1,
            role=MessageRole.ASSISTANT,
            content=f"answer {turn}",
        )
    await db_session.commit()

    tight = settings.model_copy(update={"llm_history_turns": 4})
    service = _service(db_session, tight, redis_client, FakeLLMProvider())
    history = await service.history(student_session, limit=tight.llm_history_turns)

    assert len(history) == 4
    assert history[-1].text == "answer 14", "the most recent turns are the ones kept"
    assert history[0].text == "question 13"


async def test_the_turn_path_actually_applies_the_history_bound(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """The setting has to reach the request, not merely exist.

    Testing `history()` directly would have passed while `stream_turn` used the default — which
    is exactly what it did until this test was written.
    """
    repo = MessageRepository(db_session)
    for turn in range(12):
        await repo.append(
            session_id=student_session,
            turn_index=turn,
            seq=0,
            role=MessageRole.USER,
            content=f"question {turn}",
        )
        await repo.append(
            session_id=student_session,
            turn_index=turn,
            seq=1,
            role=MessageRole.ASSISTANT,
            content=f"answer {turn}",
        )
    await db_session.commit()

    tight = settings.model_copy(update={"llm_history_turns": 4})
    llm = FakeLLMProvider()
    service = _service(db_session, tight, redis_client, llm)

    async for _fragment, _result in service.stream_turn(
        session_id=student_session, student_id=uuid.uuid4(), utterance="and now?"
    ):
        pass

    # 4 replayed history messages + the new utterance.
    assert len(llm.last_request.messages) == 5
    assert llm.last_request.messages[-1].text == "and now?"


async def test_a_real_search_hit_produces_a_real_populated_citation(
    db_session: AsyncSession, settings: Settings, redis_client, tmp_path: Path
) -> None:
    """`TurnResult.citations` end to end: a real ingested document, a real search_knowledge hit,
    and a reply citing it — not just "resolve_citations doesn't crash on a fabricated ref" (already
    covered elsewhere) but "a real citation actually arrives with the right content." Nothing in
    this suite checked that before ARCHITECTURE §10's `rag.citations` frame needed it to be true.
    """
    user = User(email=f"cite-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name="Cite")
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()

    rag = RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
    doc = tmp_path / "kvl.md"
    doc.write_text(
        "# Unit\n\n## 7.1 KVL\n\nKVL states voltages sum to zero.\n\n"
        "## 7.2 KCL\n\nKCL states currents sum to zero.\n",
        encoding="utf-8",
    )
    await rag.ingest_file(doc, DocumentMetadata(title="KVL Notes", subject="EMT"))
    await db_session.commit()
    await rag.fit_and_embed_all()
    await db_session.commit()

    search_call = ToolCall(id="c1", name="search_knowledge", arguments={"query": "KVL"})
    llm = FakeLLMProvider(
        [
            ScriptedTurn(text="question"),  # IntentGate.classify
            ScriptedTurn(tool_calls=[search_call], stop_reason="tool_use"),
            ScriptedTurn(text="KVL says loop voltages sum to zero [1]."),
        ]
    )
    service = ConversationService(
        llm=llm,
        messages=MessageRepository(db_session),
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
        db=db_session,
        tool_registry=DEFAULT_REGISTRY,
        intent_gate=IntentGate(llm),
        rag=rag,
    )

    result = None
    async for _fragment, maybe_result in service.stream_turn(
        session_id=session.id, student_id=student.id, utterance="What is KVL?"
    ):
        if maybe_result is not None:
            result = maybe_result

    assert result is not None
    assert len(result.citations) == 1
    assert result.citations[0].document_title == "KVL Notes"
    assert result.citations[0].ref == "[1]"


# --- withdrawing a cut-off turn (ARCHITECTURE §5.6) and surviving cancellation (D8-04) ------


async def _turn(
    repo: MessageRepository, session_id: uuid.UUID, index: int, question: str, answer: str
) -> None:
    await repo.append(
        session_id=session_id, turn_index=index, seq=0, role=MessageRole.USER, content=question
    )
    await repo.append(
        session_id=session_id,
        turn_index=index,
        seq=1,
        role=MessageRole.ASSISTANT,
        content=answer,
        was_interrupted=not answer,
    )


async def test_only_the_named_question_with_an_unheard_answer_is_withdrawn(
    db_session: AsyncSession, student_session: uuid.UUID
) -> None:
    repo = MessageRepository(db_session)
    await _turn(repo, student_session, 0, "What is KVL?", "Loop voltages sum to zero.")
    await _turn(repo, student_session, 1, "And KCL", "")

    assert await repo.withdraw_unheard_turn(student_session, question="And KVL") is None
    assert await repo.withdraw_unheard_turn(student_session, question="And KCL") == 1
    rows = await _messages(db_session, student_session)
    assert [(r.turn_index, r.content) for r in rows] == [
        (0, "What is KVL?"),
        (0, "Loop voltages sum to zero."),
    ]
    session = await db_session.get(Session, student_session)
    assert session is not None
    await db_session.refresh(session)
    assert session.turn_count == 1

    # An answer that was heard is never withdrawn, whatever the question.
    assert await repo.withdraw_unheard_turn(student_session, question="What is KVL?") is None


async def test_a_connection_lost_to_a_cancelled_query_is_recovered(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    service = _service(db_session, settings, redis_client, FakeLLMProvider())
    query = asyncio.create_task(db_session.execute(sql("SELECT pg_sleep(1)")))
    await asyncio.sleep(0.1)
    query.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await query

    await service.recover()
    assert (await db_session.execute(sql("SELECT 1"))).scalar() == 1


async def test_recovery_leaves_a_healthy_session_and_its_work_alone(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    service = _service(db_session, settings, redis_client, FakeLLMProvider())
    await _turn(MessageRepository(db_session), student_session, 0, "Kept?", "")

    await service.recover()
    await db_session.commit()
    assert len(await _messages(db_session, student_session)) == 2


class _Watching(FakeLLMProvider):
    """Notes, when the model is asked, whether the turn still holds a database transaction."""

    def __init__(self, session: AsyncSession, turns: list[ScriptedTurn] | None = None) -> None:
        super().__init__(turns or [ScriptedTurn(text="Loop voltages sum to zero.")])
        self._session = session
        self.in_transaction_when_asked: list[bool] = []

    async def stream(self, request):  # type: ignore[no-untyped-def,override]
        self.in_transaction_when_asked.append(self._session.in_transaction())
        async for event in super().stream(request):
            yield event


async def test_a_turn_holds_no_database_connection_while_the_model_answers(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """A transaction holds a pooled connection. Held through the model's answer and the student's
    playback, it made the pool a worker's limit on simultaneous turns (docs/LOAD.md)."""
    llm = _Watching(db_session)
    service = ConversationService(
        llm=llm,
        messages=MessageRepository(db_session),
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
        db=db_session,
    )
    student_id = (await db_session.get(Session, student_session)).student_id  # type: ignore[union-attr]
    await db_session.commit()

    async for _fragment, _result in service.stream_turn(
        session_id=student_session, student_id=student_id, utterance="What is KVL?"
    ):
        pass

    assert llm.in_transaction_when_asked == [False]
    assert [m.content for m in await _messages(db_session, student_session)] == [
        "What is KVL?",
        "Loop voltages sum to zero.",
    ]


async def test_a_tool_turn_holds_no_database_connection_while_the_model_answers_again(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """After a tool call the model is asked again. The call's record is kept, and the connection
    handed back, before that — by the hook the service gives the tool loop (`after_tool_call`)."""
    search = ToolCall(id="c1", name="search_knowledge", arguments={"query": "KVL"})
    llm = _Watching(
        db_session,
        [
            ScriptedTurn(text="question"),  # IntentGate.classify
            ScriptedTurn(tool_calls=[search], stop_reason="tool_use"),
            ScriptedTurn(text="Loop voltages sum to zero."),
        ],
    )
    service = ConversationService(
        llm=llm,
        messages=MessageRepository(db_session),
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
        db=db_session,
        tool_registry=DEFAULT_REGISTRY,
        intent_gate=IntentGate(llm),
        rag=RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker()),
    )
    student_id = (await db_session.get(Session, student_session)).student_id  # type: ignore[union-attr]
    await db_session.commit()

    async for _fragment, _result in service.stream_turn(
        session_id=student_session, student_id=student_id, utterance="What is KVL?"
    ):
        pass

    # The intent call, the first answer, and the answer after the tool call.
    assert llm.in_transaction_when_asked == [False, False, False]


class _SlowToRecordTheAnswer(MessageRepository):
    """Holds the answer's write until released, so a cancellation can land in the middle of it."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.recording = asyncio.Event()
        self.release = asyncio.Event()

    async def append(self, **fields):  # type: ignore[no-untyped-def,override]
        if fields["role"] is MessageRole.ASSISTANT:
            self.recording.set()
            await self.release.wait()
        return await super().append(**fields)


async def test_an_answer_being_recorded_when_the_turn_is_cancelled_is_still_recorded(
    db_session: AsyncSession, settings: Settings, redis_client, student_session: uuid.UUID
) -> None:  # type: ignore[no-untyped-def]
    """A barge-in, or the student leaving, can land while the answer is being written — under
    load, while the write waits for a pooled connection. Cut off there, the answer the student
    had heard was never recorded, and a flush or commit cut off mid-way broke the transaction
    (docs/LOAD.md)."""
    messages = _SlowToRecordTheAnswer(db_session)
    service = ConversationService(
        llm=FakeLLMProvider([ScriptedTurn(text="Loop voltages sum to zero.")]),
        messages=messages,
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
        db=db_session,
    )
    student_id = (await db_session.get(Session, student_session)).student_id  # type: ignore[union-attr]
    await db_session.commit()

    async def turn() -> None:
        async for _fragment, _result in service.stream_turn(
            session_id=student_session, student_id=student_id, utterance="What is KVL?"
        ):
            pass

    running = asyncio.create_task(turn())
    await messages.recording.wait()
    running.cancel()
    messages.release.set()
    with pytest.raises(asyncio.CancelledError):
        await running

    await service.recover()
    assert not db_session.in_transaction(), "nothing left half-written"
    assert [m.content for m in await _messages(db_session, student_session)] == [
        "What is KVL?",
        "Loop voltages sum to zero.",
    ]
