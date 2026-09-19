"""The tool executor: validation, timeout, and logging — independent of what any real tool does.

Synthetic tools exercise exactly one path each (success, expected failure, timeout, a genuine bug)
that would be awkward to trigger reliably through a real tool's own business logic.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import ToolContext, ToolDefinition, ToolExecutionError, ToolInput
from app.agent.tools.executor import (
    NOT_ALLOWED_MESSAGE,
    TIMEOUT_MESSAGE,
    UNKNOWN_TOOL_MESSAGE,
    execute_tool_call,
)
from app.agent.tools.registry import ToolRegistry
from app.db.models import Session, Student, ToolStatus, User, UserRole
from app.db.models import ToolCall as ToolCallRow
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import ToolCall, ToolSpec
from app.providers.reranker.base import NoopReranker
from app.rag.service import RagService


class _EchoInput(ToolInput):
    value: str


async def _echo(args: _EchoInput, ctx: ToolContext) -> dict:  # type: ignore[type-arg]
    return {"echoed": args.value}


async def _always_fails(args: _EchoInput, ctx: ToolContext) -> dict:  # type: ignore[type-arg]
    raise ToolExecutionError("this tool always declines")


async def _always_hangs(args: _EchoInput, ctx: ToolContext) -> dict:  # type: ignore[type-arg]
    await asyncio.sleep(10)
    return {}  # pragma: no cover - never reached, the timeout fires first


async def _always_bugs(args: _EchoInput, ctx: ToolContext) -> dict:  # type: ignore[type-arg]
    raise RuntimeError("a genuine, unanticipated bug")


_TEST_REGISTRY = ToolRegistry(
    [
        ToolDefinition(
            spec=ToolSpec(name="echo", description="d", input_schema={"type": "object"}),
            input_model=_EchoInput,
            handler=_echo,
        ),
        ToolDefinition(
            spec=ToolSpec(name="fails", description="d", input_schema={"type": "object"}),
            input_model=_EchoInput,
            handler=_always_fails,
            mutating=True,
        ),
        ToolDefinition(
            spec=ToolSpec(name="hangs", description="d", input_schema={"type": "object"}),
            input_model=_EchoInput,
            handler=_always_hangs,
            timeout_seconds=0.05,
        ),
        ToolDefinition(
            spec=ToolSpec(name="bugs", description="d", input_schema={"type": "object"}),
            input_model=_EchoInput,
            handler=_always_bugs,
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
        email=f"exec-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", role=UserRole.STUDENT
    )
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name="Executor Test")
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


async def _logged_call(db_session: AsyncSession, session_id: uuid.UUID) -> ToolCallRow:
    rows = (
        (await db_session.execute(select(ToolCallRow).where(ToolCallRow.session_id == session_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    return rows[0]


async def test_a_successful_call_returns_the_handlers_output_as_json(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t1", name="echo", arguments={"value": "hello"})
    result = await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))

    assert result.is_error is False
    assert json.loads(result.content) == {"echoed": "hello"}

    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.OK
    assert logged.tool_name == "echo"
    assert logged.result == {"echoed": "hello"}


async def test_an_unknown_tool_name_is_rejected_not_a_crash(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t2", name="does_not_exist", arguments={})
    result = await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))

    assert result.is_error is True
    assert result.content == UNKNOWN_TOOL_MESSAGE
    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.REJECTED


async def test_invalid_arguments_are_rejected_before_the_handler_runs(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t3", name="echo", arguments={"wrong_field": 1})
    result = await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))

    assert result.is_error is True
    assert "Invalid arguments" in result.content
    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.REJECTED


async def test_a_tool_execution_error_becomes_a_graceful_is_error_result(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t4", name="fails", arguments={"value": "x"})
    result = await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))

    assert result.is_error is True
    assert result.content == "this tool always declines"
    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.ERROR
    assert logged.error == "this tool always declines"


async def test_a_slow_tool_is_stopped_at_its_own_timeout_and_reported_as_such(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t5", name="hangs", arguments={"value": "x"})
    result = await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))

    assert result.is_error is True
    assert result.content == TIMEOUT_MESSAGE
    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.TIMEOUT


async def test_a_call_outside_the_turns_allowlist_is_rejected_even_though_it_exists(
    db_session: AsyncSession, actor: Actor
) -> None:
    """The allowlist is enforced here, independent of what the request happened to offer — see
    the module docstring in app.agent.tools.executor for why "not offered" alone is not enough."""
    call = ToolCall(id="t7", name="fails", arguments={"value": "x"})
    result = await execute_tool_call(
        call,
        registry=_TEST_REGISTRY,
        ctx=_ctx(db_session, actor),
        allowed_tool_names=frozenset({"echo"}),
    )

    assert result.is_error is True
    assert result.content == NOT_ALLOWED_MESSAGE
    logged = await _logged_call(db_session, actor.session_id)
    assert logged.status is ToolStatus.REJECTED


async def test_allowed_tool_names_none_means_no_restriction(
    db_session: AsyncSession, actor: Actor
) -> None:
    call = ToolCall(id="t8", name="echo", arguments={"value": "hi"})
    result = await execute_tool_call(
        call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor), allowed_tool_names=None
    )
    assert result.is_error is False


async def test_an_unexpected_bug_propagates_rather_than_being_laundered_into_a_polite_decline(
    db_session: AsyncSession, actor: Actor
) -> None:
    """A real defect must surface, not be dressed up as a normal tool outcome — see the module
    docstring in app.agent.tools.executor."""
    call = ToolCall(id="t6", name="bugs", arguments={"value": "x"})
    with pytest.raises(RuntimeError, match="a genuine, unanticipated bug"):
        await execute_tool_call(call, registry=_TEST_REGISTRY, ctx=_ctx(db_session, actor))
