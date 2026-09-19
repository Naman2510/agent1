"""The agentic tool-calling loop: rounds, budgets, parallel-call fan-in, and the one property
ADR-0009 calls out by name — a tool call already running must survive the turn being cancelled.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import (
    BUDGET_EXCEEDED_MESSAGE,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_TOOL_ROUNDS,
    run_agent_turn,
)
from app.agent.tools.base import ToolContext, ToolDefinition, ToolInput
from app.agent.tools.registry import ToolRegistry
from app.db.models import Session, Student, User, UserRole
from app.db.models import ToolCall as ToolCallRow
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import TokenUsage, ToolCall, ToolSpec, TurnMessage
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.providers.reranker.base import NoopReranker
from app.rag.service import RagService


class _NoArgsInput(ToolInput):
    pass


async def _returns_ok(args: _NoArgsInput, ctx: ToolContext) -> dict:
    return {"ok": True}


_ECHO_REGISTRY = ToolRegistry(
    [
        ToolDefinition(
            spec=ToolSpec(name="lookup", description="d", input_schema={"type": "object"}),
            input_model=_NoArgsInput,
            handler=_returns_ok,
        ),
    ]
)


@dataclass
class Actor:
    student_id: uuid.UUID
    session_id: uuid.UUID


@pytest.fixture
async def actor(db_session: AsyncSession) -> Actor:
    user = User(
        email=f"orch-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", role=UserRole.STUDENT
    )
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name="Orchestrator Test")
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()
    return Actor(student_id=student.id, session_id=session.id)


def _ctx(db_session: AsyncSession, actor: Actor) -> ToolContext:
    rag = RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
    return ToolContext(
        student_id=actor.student_id,
        session_id=actor.session_id,
        turn_index=0,
        db=db_session,
        rag=rag,
        citation_sources={},
    )


async def _run(llm, registry, allowed, ctx, **kwargs):
    fragments = []
    outcome = None
    async for fragment, maybe_outcome in run_agent_turn(
        llm=llm,
        system=[],
        initial_messages=[TurnMessage(role="user", text="hello")],
        registry=registry,
        allowed_tool_names=allowed,
        tool_ctx=ctx,
        max_output_tokens=200,
        **kwargs,
    ):
        if maybe_outcome is not None:
            outcome = maybe_outcome
        elif fragment:
            fragments.append(fragment)
    assert outcome is not None
    return "".join(fragments), outcome


# --- no tools requested: must behave like a plain single-shot turn -----------


async def test_no_tool_use_is_a_single_round_plain_answer(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider([ScriptedTurn(text="The answer is 42.")])
    text, outcome = await _run(llm, _ECHO_REGISTRY, frozenset(), _ctx(db_session, actor))

    assert text == "The answer is 42."
    assert outcome.text == "The answer is 42."
    assert outcome.stop_reason == "end_turn"
    assert outcome.budget_exceeded is False
    assert len(llm.requests) == 1


async def test_an_empty_allowlist_offers_no_tools_to_the_model(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider([ScriptedTurn(text="hi")])
    await _run(llm, _ECHO_REGISTRY, frozenset(), _ctx(db_session, actor))
    assert list(llm.last_request.tools) == []


# --- one tool round ------------------------------------------------------


async def test_a_tool_round_executes_and_feeds_the_result_back(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                tool_calls=[ToolCall(id="c1", name="lookup", arguments={})],
                stop_reason="tool_use",
            ),
            ScriptedTurn(text="Here is your answer.", stop_reason="end_turn"),
        ]
    )
    text, outcome = await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))

    assert len(llm.requests) == 2
    assert text == "Here is your answer."
    assert outcome.stop_reason == "end_turn"

    second_request_messages = llm.requests[1].messages
    assert second_request_messages[-2].role == "assistant"
    assert second_request_messages[-2].tool_calls[0].name == "lookup"
    assert second_request_messages[-1].role == "user"
    assert second_request_messages[-1].tool_results[0].tool_use_id == "c1"


async def test_interim_text_before_a_tool_call_is_streamed_and_kept(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                text="Let me check that.",
                tool_calls=[ToolCall(id="c1", name="lookup", arguments={})],
                stop_reason="tool_use",
            ),
            ScriptedTurn(text=" Found it.", stop_reason="end_turn"),
        ]
    )
    text, outcome = await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))
    assert text == "Let me check that. Found it."
    assert outcome.text == "Let me check that. Found it."


async def test_parallel_tool_calls_in_one_round_are_fed_back_in_a_single_message(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="c1", name="lookup", arguments={}),
                    ToolCall(id="c2", name="lookup", arguments={}),
                ],
                stop_reason="tool_use",
            ),
            ScriptedTurn(text="Done.", stop_reason="end_turn"),
        ]
    )
    await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))

    tool_result_messages = [m for m in llm.requests[1].messages if m.tool_results]
    assert len(tool_result_messages) == 1
    assert {r.tool_use_id for r in tool_result_messages[0].tool_results} == {"c1", "c2"}


# --- budgets (ARCHITECTURE §8.1) ---------------------------------------------


async def test_exceeding_max_rounds_stops_and_reports_budget_exceeded(
    db_session: AsyncSession, actor: Actor
) -> None:
    tool_use_turn = ScriptedTurn(
        tool_calls=[ToolCall(id="c", name="lookup", arguments={})], stop_reason="tool_use"
    )
    # One more tool_use turn than the round budget allows, so the last one is the one that trips it.
    llm = FakeLLMProvider([tool_use_turn] * (MAX_TOOL_ROUNDS + 1))

    text, outcome = await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))

    assert outcome.budget_exceeded is True
    assert BUDGET_EXCEEDED_MESSAGE in text
    assert len(llm.requests) == MAX_TOOL_ROUNDS + 1


async def test_a_single_round_requesting_more_than_the_call_budget_is_declined_up_front(
    db_session: AsyncSession, actor: Actor
) -> None:
    """A round that alone exceeds the whole turn's call budget never gets any of its tools run —
    not even a partial batch."""
    calls = [
        ToolCall(id=f"c{i}", name="lookup", arguments={})
        for i in range(MAX_TOOL_CALLS_PER_TURN + 1)
    ]
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=calls, stop_reason="tool_use")])

    _, outcome = await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))

    assert outcome.budget_exceeded is True
    assert len(llm.requests) == 1  # never asked the model again after declining
    stmt = select(ToolCallRow).where(ToolCallRow.session_id == actor.session_id)
    logged = (await db_session.execute(stmt)).scalars().all()
    assert logged == []  # none of the over-budget round's calls were even attempted


# --- usage accounting ---------------------------------------------------------


async def test_usage_is_summed_across_every_round_not_just_the_last(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                tool_calls=[ToolCall(id="c1", name="lookup", arguments={})],
                stop_reason="tool_use",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            ),
            ScriptedTurn(
                text="done",
                stop_reason="end_turn",
                usage=TokenUsage(input_tokens=20, output_tokens=8),
            ),
        ]
    )
    _, outcome = await _run(llm, _ECHO_REGISTRY, frozenset({"lookup"}), _ctx(db_session, actor))

    assert outcome.usage.input_tokens == 30
    assert outcome.usage.output_tokens == 13


# --- authority: the allowlist is enforced even if the model asks anyway ------


async def test_a_tool_call_outside_the_allowlist_is_rejected_not_executed(
    db_session: AsyncSession, actor: Actor
) -> None:
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                tool_calls=[ToolCall(id="c1", name="lookup", arguments={})], stop_reason="tool_use"
            ),
            ScriptedTurn(text="ok", stop_reason="end_turn"),
        ]
    )
    # allowed_tool_names is empty even though the fake model calls "lookup" anyway.
    await _run(llm, _ECHO_REGISTRY, frozenset(), _ctx(db_session, actor))

    second_request_messages = llm.requests[1].messages
    tool_result = second_request_messages[-1].tool_results[0]
    assert tool_result.is_error is True


# --- cancellation must not cancel an in-flight tool call (Gate 0, C-04 item 3) ---


async def test_a_cancelled_turn_does_not_cancel_an_in_flight_tool_call(
    db_session: AsyncSession, actor: Actor
) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()

    async def _slow_handler(args: _NoArgsInput, ctx: ToolContext) -> dict:
        started.set()
        await asyncio.sleep(0.2)
        finished.set()
        return {"ok": True}

    slow_registry = ToolRegistry(
        [
            ToolDefinition(
                spec=ToolSpec(name="slow", description="d", input_schema={"type": "object"}),
                input_model=_NoArgsInput,
                handler=_slow_handler,
                mutating=True,
            ),
        ]
    )
    llm = FakeLLMProvider(
        [
            ScriptedTurn(
                tool_calls=[ToolCall(id="c1", name="slow", arguments={})], stop_reason="tool_use"
            ),
            ScriptedTurn(text="done", stop_reason="end_turn"),
        ]
    )

    async def _consume() -> None:
        async for _fragment, _outcome in run_agent_turn(
            llm=llm,
            system=[],
            initial_messages=[TurnMessage(role="user", text="go")],
            registry=slow_registry,
            allowed_tool_names=frozenset({"slow"}),
            tool_ctx=_ctx(db_session, actor),
            max_output_tokens=100,
        ):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(started.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The handler must still be allowed to run to completion in the background, even though the
    # turn that started it was cancelled while it was mid-flight.
    await asyncio.wait_for(finished.wait(), timeout=2.0)

    # `finished` proves the *handler* ran to completion, but `execute_tool_call` still has a
    # trailing DB write after the handler returns (the tool_calls audit row) — real work on the
    # very `db_session` this test's fixture owns, still in flight on the shielded background
    # task. A short grace period lets it finish before this test returns and fixture teardown
    # (`session.rollback()`) starts touching that same session from a different coroutine —
    # otherwise the two race on one AsyncSession, which is not safe for concurrent use (the exact
    # hazard `run_agent_turn`'s sequential tool execution exists to avoid in production; here it
    # is a test-only artifact of deliberately outliving the cancelled task). Found by the test
    # suite hanging in fixture teardown after every test had already reported PASSED, not by any
    # assertion failing.
    await asyncio.sleep(0.1)
