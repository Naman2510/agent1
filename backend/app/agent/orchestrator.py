"""The agentic tool-calling loop (ADR-0009): stream, collect `tool_use`, execute in parallel,
feed results back as one message, repeat under budget.

A hand-written loop rather than a framework, for the reasons ADR-0009 gives: cancellation must
reach an in-flight stream cleanly (barge-in depends on it), and per-stage timing requires owning
the control flow. This module owns exactly that loop; `ConversationService` still owns turn
bookkeeping (history, persistence, delivery tracking) and delegates to `run_agent_turn` only when
a tool registry was actually configured — a caller that never passes one gets the exact single-shot
behaviour Phase 2 always had, unchanged.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass

import structlog

from app.agent.tools.base import ToolContext
from app.agent.tools.executor import execute_tool_call
from app.agent.tools.registry import ToolRegistry
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRequest,
    StopReason,
    StreamCompleted,
    SystemBlock,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
    TurnMessage,
)

log = structlog.get_logger(__name__)

# ARCHITECTURE §8.1's hard budgets — enforced here, not trusted to the model to self-limit.
MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS_PER_TURN = 6
MAX_TOOL_WALL_CLOCK_MS = 2500

BUDGET_EXCEEDED_MESSAGE = " I couldn't finish checking everything just now — here's what I have."


@dataclass(frozen=True)
class AgentTurnOutcome:
    """What one full turn (all rounds) produced. `usage` is summed across every round: each round
    is a separate billed API call, and a round's input includes the previous round's history
    resent — a real cost, not double-counting (prompt caching is what makes the resend cheap, not
    free)."""

    text: str
    stop_reason: StopReason
    usage: TokenUsage
    model: str
    budget_exceeded: bool = False


def _add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_creation_input_tokens=a.cache_creation_input_tokens + b.cache_creation_input_tokens,
        cache_read_input_tokens=a.cache_read_input_tokens + b.cache_read_input_tokens,
    )


async def run_agent_turn(
    *,
    llm: LLMProvider,
    system: Sequence[SystemBlock],
    initial_messages: Sequence[TurnMessage],
    registry: ToolRegistry,
    allowed_tool_names: frozenset[str],
    tool_ctx: ToolContext,
    max_output_tokens: int,
    effort: Effort | None = None,
) -> AsyncGenerator[tuple[str, AgentTurnOutcome | None], None]:
    """Run the loop for one turn. Yields `(text_fragment, None)` as it streams, then exactly one
    final `("", outcome)` — the same yield contract `ConversationService.stream_turn` already
    uses, so the two compose without the caller needing a different protocol for the tool path.

    Disabling every tool (`allowed_tool_names` empty, e.g. a CASUAL/CLARIFICATION intent) still
    goes through this loop rather than a separate no-tools code path — one loop to trust, not two
    that could silently diverge; it simply never sees a `tool_use` stop reason to act on.
    """
    messages = list(initial_messages)
    tools = registry.specs_for(allowed_tool_names)

    rounds = 0
    total_calls = 0
    tool_wall_clock_ms = 0
    accumulated_text: list[str] = []
    usage_total = TokenUsage()
    model = llm.info.model
    budget_exceeded = False
    stop_reason: StopReason = "end_turn"

    while True:
        request = LLMRequest(
            system=system,
            messages=messages,
            tools=tools,
            max_output_tokens=max_output_tokens,
            effort=effort,
        )
        round_text_parts: list[str] = []
        round_calls: list[ToolCall] = []
        round_usage = TokenUsage()

        async for event in llm.stream(request):
            if isinstance(event, TextDelta):
                round_text_parts.append(event.text)
                accumulated_text.append(event.text)
                yield event.text, None
            elif isinstance(event, ToolCallDelta):
                round_calls.append(event.call)
            elif isinstance(event, StreamCompleted):
                stop_reason = event.stop_reason
                round_usage = event.usage
                model = event.model

        usage_total = _add_usage(usage_total, round_usage)

        if stop_reason != "tool_use" or not round_calls:
            break

        rounds += 1
        total_calls += len(round_calls)
        if (
            rounds > MAX_TOOL_ROUNDS
            or total_calls > MAX_TOOL_CALLS_PER_TURN
            or tool_wall_clock_ms > MAX_TOOL_WALL_CLOCK_MS
        ):
            log.warning(
                "agent.tool_budget_exceeded",
                rounds=rounds,
                total_calls=total_calls,
                tool_wall_clock_ms=tool_wall_clock_ms,
            )
            budget_exceeded = True
            accumulated_text.append(BUDGET_EXCEEDED_MESSAGE)
            yield BUDGET_EXCEEDED_MESSAGE, None
            break

        messages.append(
            TurnMessage(
                role="assistant", text="".join(round_text_parts), tool_calls=tuple(round_calls)
            )
        )

        started = time.perf_counter()
        # Sequential, not asyncio.gather — every tool call in a turn shares one ToolContext.db
        # (one AsyncSession), and SQLAlchemy sessions are not safe for concurrent use: two
        # coroutines flushing the same session at once raises "Session is already flushing"
        # (found by running exactly this case, a two-call round, not by inspection). A single DB
        # connection could not truly parallelize these anyway. ADR-0009's "parallel tool results
        # go back in one message" is about that message shape, not about concurrent execution —
        # satisfied here by still batching every result from the round into one TurnMessage below.
        #
        # Each call is still individually shielded: Gate 0 finding C-04, item 3 — cancellation
        # must not leave a half-applied write. A mutating tool (create_study_plan, generate_quiz,
        # update_student_progress) could otherwise be interrupted (barge-in) mid-commit. Shielding
        # lets a call that has already started finish its transaction even if this turn's
        # cancellation propagates right after it — the turn still ends and the result is
        # discarded, exactly as C-04 specifies ("cancellation waits or times out, then discards
        # results"); the write itself completes, and any calls after it simply never start.
        # Not yet done: the same finding's idempotency key (`(session, turn, tool, args_hash)`),
        # which would let a *retried* call detect it already ran — recorded as a gap, not silently
        # skipped (see the Phase 6 audit).
        results = []
        for call in round_calls:
            result = await asyncio.shield(
                execute_tool_call(
                    call, registry=registry, ctx=tool_ctx, allowed_tool_names=allowed_tool_names
                )
            )
            results.append(result)
        tool_wall_clock_ms += int((time.perf_counter() - started) * 1000)

        # ADR-0009: every tool result for a round goes in ONE user message. Splitting them across
        # messages measurably degrades the model's willingness to make parallel calls again.
        messages.append(TurnMessage(role="user", tool_results=tuple(results)))

    yield "", AgentTurnOutcome(
        text="".join(accumulated_text),
        stop_reason=stop_reason,
        usage=usage_total,
        model=model,
        budget_exceeded=budget_exceeded,
    )
