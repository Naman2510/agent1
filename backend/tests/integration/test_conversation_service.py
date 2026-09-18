"""The turn service directly: cancellation, provider swapping, and history bounds.

The cancellation test is the important one here. It asserts the invariant from Gate 0 finding
C-03 — *what is stored is what the user actually received* — while the thing that makes it matter
(barge-in) does not exist yet. Phase 3 inherits a tested invariant rather than discovering it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Message, MessageRole, Session, Student, User, UserRole
from app.db.repositories.sessions import MessageRepository
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
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
