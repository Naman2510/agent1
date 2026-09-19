"""Runs one tool call: validate, run under a timeout, log, and return a result the model can see.

Only *expected* failures become a graceful `is_error=True` result — a `ToolExecutionError` a
handler raised on purpose, an unknown tool name, bad arguments, or a timeout. Anything else is a
real bug and is left to propagate, the same way `ConversationService` lets an unexpected exception
surface rather than dressing it up as a normal outcome: laundering a genuine defect into a polite
"sorry, couldn't do that" would hide it from everyone who'd otherwise notice and fix it.
"""

from __future__ import annotations

import asyncio
import json
import time

import structlog
from pydantic import ValidationError

from app.agent.tools.base import ToolContext, ToolExecutionError
from app.agent.tools.registry import ToolRegistry
from app.db.models import ToolStatus
from app.db.repositories.tool_calls import ToolCallRepository
from app.providers.llm.base import ToolCall, ToolResult

log = structlog.get_logger(__name__)

UNKNOWN_TOOL_MESSAGE = "That tool does not exist."
NOT_ALLOWED_MESSAGE = "That tool is not available for this kind of request."
TIMEOUT_MESSAGE = "That took too long, so I couldn't get an answer."


async def execute_tool_call(
    call: ToolCall,
    *,
    registry: ToolRegistry,
    ctx: ToolContext,
    allowed_tool_names: frozenset[str] | None = None,
) -> ToolResult:
    """`allowed_tool_names` is `IntentGate`'s allowlist for this turn. It is enforced *here*, not
    only by which tools were offered in the request: a strict JSON schema makes the model asking
    for an unoffered tool rare, but rare is not the same as impossible, and a mutating tool
    reachable only because the request happened not to include its schema is not actually gated
    (ARCHITECTURE §8.2/§8.4). Passing `None` skips the check — used by callers (tests, and any
    future path with no intent gate at all) that mean to offer every tool in `registry`.
    """
    tool_calls = ToolCallRepository(ctx.db)
    definition = registry.get(call.name)

    if definition is None:
        # The model invented a tool name — strict schemas make this rare, not impossible.
        log.warning("tool.unknown", tool=call.name)
        await tool_calls.record(
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            tool_name=call.name,
            arguments=call.arguments,
            status=ToolStatus.REJECTED,
            error="unknown tool",
        )
        return ToolResult(tool_use_id=call.id, content=UNKNOWN_TOOL_MESSAGE, is_error=True)

    if allowed_tool_names is not None and call.name not in allowed_tool_names:
        log.warning("tool.not_allowed", tool=call.name)
        await tool_calls.record(
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            tool_name=call.name,
            arguments=call.arguments,
            status=ToolStatus.REJECTED,
            error="not in this turn's allowlist",
        )
        return ToolResult(tool_use_id=call.id, content=NOT_ALLOWED_MESSAGE, is_error=True)

    try:
        args = definition.input_model.model_validate(call.arguments)
    except ValidationError as exc:
        log.warning("tool.rejected", tool=call.name, error=str(exc))
        await tool_calls.record(
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            tool_name=call.name,
            arguments=call.arguments,
            status=ToolStatus.REJECTED,
            error=str(exc),
        )
        return ToolResult(tool_use_id=call.id, content=f"Invalid arguments: {exc}", is_error=True)

    started = time.perf_counter()
    try:
        async with asyncio.timeout(definition.timeout_seconds):
            output = await definition.handler(args, ctx)
    except ToolExecutionError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await tool_calls.record(
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            tool_name=call.name,
            arguments=call.arguments,
            status=ToolStatus.ERROR,
            error=str(exc),
            duration_ms=duration_ms,
        )
        return ToolResult(tool_use_id=call.id, content=str(exc), is_error=True)
    except TimeoutError:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log.warning("tool.timeout", tool=call.name, timeout_seconds=definition.timeout_seconds)
        await tool_calls.record(
            session_id=ctx.session_id,
            turn_index=ctx.turn_index,
            tool_name=call.name,
            arguments=call.arguments,
            status=ToolStatus.TIMEOUT,
            error="timeout",
            duration_ms=duration_ms,
        )
        return ToolResult(tool_use_id=call.id, content=TIMEOUT_MESSAGE, is_error=True)

    duration_ms = int((time.perf_counter() - started) * 1000)
    await tool_calls.record(
        session_id=ctx.session_id,
        turn_index=ctx.turn_index,
        tool_name=call.name,
        arguments=call.arguments,
        result=output,
        status=ToolStatus.OK,
        duration_ms=duration_ms,
    )
    return ToolResult(tool_use_id=call.id, content=json.dumps(output))
