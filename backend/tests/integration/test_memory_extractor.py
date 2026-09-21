"""`MemoryExtractor` against a real database: EWMA at the conversational alpha, confidence gating,
and the `memory_events` audit trail (ARCHITECTURE §12, ADR-0012).

The last test in this file is Gate 6's own acceptance criterion made concrete: "a memory delta is
traceable end to end" — from a real `ConversationService.stream_turn` call, through the
off-critical-path background task, to a `student_topics` row and a `memory_events` row that
reference the exact session and message that produced them.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agent.intent import IntentGate
from app.agent.memory_extractor import PROPOSE_MEMORY_DELTAS_TOOL, MemoryExtractor
from app.agent.tools.registry import DEFAULT_REGISTRY
from app.core.background import drain
from app.core.config import Settings
from app.db.models import (
    MemoryEvent,
    MemoryKind,
    Session,
    Student,
    StudentProfile,
    User,
    UserRole,
)
from app.db.repositories.memory import StudentProfileRepository
from app.db.repositories.sessions import MessageRepository
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import ToolCall
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.providers.reranker.base import NoopReranker
from app.rag.service import RagService
from app.services.conversation import ConversationService
from app.services.usage import UsageLedger


@pytest.fixture(autouse=True)
async def _clean_tables(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE memory_events, student_topics, student_profiles, messages, sessions, "
                "students, users RESTART IDENTITY CASCADE"
            )
        )


async def _make_student(db_session: AsyncSession, *, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name=label)
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()
    return student.id, session.id


def _topic_call(*, signal: str, confidence: float) -> ToolCall:
    return ToolCall(
        id="c1",
        name=PROPOSE_MEMORY_DELTAS_TOOL.name,
        arguments={
            "topic_signals": [
                {
                    "subject": "EMT",
                    "topic": "KVL",
                    "signal": signal,
                    "confidence": confidence,
                    "evidence": "asked for a third re-explanation",
                }
            ],
            "preference_signals": [],
        },
    )


def _preference_call(*, key: str, value: str, confidence: float) -> ToolCall:
    return ToolCall(
        id="c1",
        name=PROPOSE_MEMORY_DELTAS_TOOL.name,
        arguments={
            "topic_signals": [],
            "preference_signals": [{"key": key, "value": value, "confidence": confidence}],
        },
    )


def _extractor(engine: AsyncEngine, llm: FakeLLMProvider) -> MemoryExtractor:
    # A real, separate session factory against the same test database — exactly app/main.py's own
    # wiring — rather than the test's own db_session: extract_and_apply commits internally, and a
    # session it does not own the lifecycle of is the wrong thing to hand it, even in a test.
    return MemoryExtractor(llm, async_sessionmaker(engine, expire_on_commit=False))


async def test_confidence_below_threshold_is_logged_but_not_applied(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="low-conf")
    call = _topic_call(signal="struggled", confidence=0.3)
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    await _extractor(engine, llm).extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="I don't get KVL",
        reply="Let's try again",
    )

    topics = (
        await db_session.execute(
            text("SELECT count(*) FROM student_topics WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).scalar_one()
    assert topics == 0, "a below-threshold signal must not create or move a mastery row"

    events = (
        (await db_session.execute(select(MemoryEvent).where(MemoryEvent.student_id == student_id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].kind is MemoryKind.OBSERVATION
    assert events[0].applied is False
    assert events[0].rejection_reason == "confidence below threshold"
    assert events[0].session_id == session_id
    assert events[0].message_id is None


async def test_a_topic_signal_above_threshold_applies_ewma_at_the_conversational_alpha(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="struggled")
    call = _topic_call(signal="struggled", confidence=0.7)
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    await _extractor(engine, llm).extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="I don't get KVL",
        reply="Let's try again",
    )

    mastery = (
        await db_session.execute(
            text("SELECT mastery FROM student_topics WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).scalar_one()
    # new = alpha * sample + (1 - alpha) * old = 0.1 * 0.2 + 0.9 * 0.5 (fresh topic starts at 0.5)
    assert float(mastery) == pytest.approx(0.47, abs=1e-3)

    event = (
        await db_session.execute(select(MemoryEvent).where(MemoryEvent.student_id == student_id))
    ).scalar_one()
    assert event.kind is MemoryKind.TOPIC_UPDATE
    assert event.applied is True
    assert event.extractor_version == "memory-extractor-v1"


async def test_a_second_signal_blends_rather_than_replaces(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="two-turns")
    first_call = _topic_call(signal="struggled", confidence=0.7)
    second_call = _topic_call(signal="confident", confidence=0.9)
    llm = FakeLLMProvider(
        [
            ScriptedTurn(tool_calls=[first_call], stop_reason="tool_use"),
            ScriptedTurn(tool_calls=[second_call], stop_reason="tool_use"),
        ]
    )
    extractor = _extractor(engine, llm)

    await extractor.extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="a",
        reply="b",
    )
    after_first = (
        await db_session.execute(
            text("SELECT mastery, evidence_count FROM student_topics WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).one()
    assert float(after_first.mastery) == pytest.approx(0.47, abs=1e-3)

    await extractor.extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="c",
        reply="d",
    )
    after_second = (
        await db_session.execute(
            text("SELECT mastery, evidence_count FROM student_topics WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).one()
    # new = 0.1 * 0.9 + 0.9 * 0.47 = 0.513 — nudged, not jumped to 0.9.
    assert float(after_second.mastery) == pytest.approx(0.513, abs=1e-3)
    assert after_second.evidence_count == after_first.evidence_count + 1


async def test_a_preference_signal_updates_explanation_style(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="pref-style")
    call = _preference_call(key="explanation_style", value="analogies", confidence=0.6)
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    await _extractor(engine, llm).extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="a",
        reply="b",
    )

    profile = (
        await db_session.execute(
            select(StudentProfile).where(StudentProfile.student_id == student_id)
        )
    ).scalar_one()
    assert profile.explanation_style == "analogies"

    event = (
        await db_session.execute(select(MemoryEvent).where(MemoryEvent.student_id == student_id))
    ).scalar_one()
    assert event.kind is MemoryKind.PROFILE_UPDATE


async def test_a_preference_signal_with_another_key_lands_in_learning_preferences(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="pref-other")
    call = _preference_call(key="pace", value="slower", confidence=0.6)
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    await _extractor(engine, llm).extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="a",
        reply="b",
    )

    profile = (
        await db_session.execute(
            select(StudentProfile).where(StudentProfile.student_id == student_id)
        )
    ).scalar_one()
    assert profile.learning_preferences == {"pace": "slower"}


async def test_no_signals_writes_no_events_at_all(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    student_id, session_id = await _make_student(db_session, label="quiet")
    llm = FakeLLMProvider([ScriptedTurn(text="just chatting, nothing notable")])

    await _extractor(engine, llm).extract_and_apply(
        student_id=student_id,
        session_id=session_id,
        message_id=None,
        utterance="hi",
        reply="hey",
    )

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM memory_events WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).scalar_one()
    assert count == 0


# --- Gate 6: "a memory delta is traceable end to end" ------------------------


async def test_a_memory_delta_is_traceable_end_to_end_from_a_real_turn(
    db_session: AsyncSession,
    settings: Settings,
    redis_client,  # type: ignore[no-untyped-def]
    engine: AsyncEngine,
) -> None:
    student_id, session_id = await _make_student(db_session, label="e2e")

    struggled_call = _topic_call(signal="struggled", confidence=0.8)
    llm = FakeLLMProvider(
        [
            ScriptedTurn(text="question"),  # IntentGate.classify
            ScriptedTurn(text="Let's go through KVL again with a water-pipe analogy."),
            ScriptedTurn(tool_calls=[struggled_call], stop_reason="tool_use"),  # in the background
        ]
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = ConversationService(
        llm=llm,
        messages=MessageRepository(db_session),
        ledger=UsageLedger(redis_client, settings),
        settings=settings,
        db=db_session,
        tool_registry=DEFAULT_REGISTRY,
        intent_gate=IntentGate(llm),
        rag=RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker()),
        student_profiles=StudentProfileRepository(db_session),
        memory_extractor=MemoryExtractor(llm, session_factory),
    )

    result = None
    async for _fragment, maybe_result in service.stream_turn(
        session_id=session_id,
        student_id=student_id,
        utterance="I still don't get KVL, explain again?",
    ):
        if maybe_result is not None:
            result = maybe_result
    assert result is not None

    message_id = (
        await db_session.execute(
            text("SELECT id FROM messages WHERE session_id = :sid AND role = 'assistant'"),
            {"sid": session_id},
        )
    ).scalar_one()

    await drain()  # the extraction ran in the background — wait for it, do not race it

    topic = (
        await db_session.execute(
            text("SELECT subject, topic, mastery FROM student_topics WHERE student_id = :sid"),
            {"sid": student_id},
        )
    ).one()
    assert (topic.subject, topic.topic) == ("EMT", "KVL")
    assert float(topic.mastery) == pytest.approx(0.47, abs=1e-3)

    event = (
        await db_session.execute(select(MemoryEvent).where(MemoryEvent.student_id == student_id))
    ).scalar_one()
    assert event.kind is MemoryKind.TOPIC_UPDATE
    assert event.applied is True
    assert event.session_id == session_id
    assert event.message_id == message_id
    assert event.payload["evidence"] == "asked for a third re-explanation"
