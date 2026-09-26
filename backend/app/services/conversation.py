"""The text turn: assemble, stream, persist.

This is also where Phase 6's agentic loop plugs in. When a service is constructed with a
`tool_registry` (and the `db`/`rag` a tool execution needs), `stream_turn` delegates its streaming
section to `run_agent_turn` (ADR-0009) instead of a single-shot `llm.stream()` call; a service
built without those — every existing Phase 2/3 caller, unless it opts in — gets exactly the
single-shot behaviour it always had. One method, one yield contract, either way.

One invariant is enforced here regardless of which path runs: **what is stored is what the user
actually received.** If the consumer goes away mid-stream, the partial text is persisted and
marked interrupted rather than the full generation being written as though it had been delivered.
Getting this wrong means the mentor later refers to things the student never saw (Gate 0 finding
C-03).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent import IntentGate
from app.agent.language import script_of
from app.agent.memory_extractor import MemoryExtractor
from app.agent.orchestrator import ToolActivityEntry, run_agent_turn
from app.agent.prompts import PROMPT_VERSION, assemble
from app.agent.tools.base import ToolContext
from app.agent.tools.registry import ToolRegistry
from app.core.background import spawn
from app.core.config import Settings
from app.db.models import MessageRole
from app.db.repositories.memory import StudentProfileRepository
from app.db.repositories.sessions import MessageRepository
from app.providers.base import ProviderError
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRequest,
    StopReason,
    StreamCompleted,
    TextDelta,
    TokenUsage,
    ToolCallDelta,
    TurnMessage,
)
from app.rag.context import Citation, ContextBlock, extract_cited_refs, resolve_citations
from app.rag.retrieve import RetrievedChunk
from app.rag.service import RagService
from app.services.memory_window import SessionWindowCache
from app.services.usage import TurnCost, UsageLedger

log = structlog.get_logger(__name__)

# What the mentor says when the model declines or a provider fails. Spoken aloud in the voice
# path, so it is a sentence, not an error code.
REFUSAL_REPLY = "I can't help with that one. Ask me something from your course and I'll take it."
FAILURE_REPLY = "Sorry — I lost that. Could you say it again?"


class DeliveryTracker(Protocol):
    """Reports what the listener actually received.

    The text path has no gap between "yielded" and "received", so it passes nothing. The voice
    path passes its playback ledger: the model generates further ahead than the speaker plays, so
    only the ledger knows what was heard (ARCHITECTURE §5.3).
    """

    def delivered(self) -> str: ...

    def remainder(self) -> str: ...

    async def settle(self) -> None:
        """Return once the listener has received everything generated.

        Generation ending is not the turn ending: the student is still hearing the answer, and an
        interruption now is still an interruption (ARCHITECTURE §4.1, "playback drained").
        """
        ...


@dataclass
class TurnResult:
    """What a completed turn produced. Returned after the stream is exhausted."""

    text: str = ""
    stop_reason: StopReason = "end_turn"
    interrupted: bool = False
    language: str | None = None
    cost: TurnCost | None = None
    latency_ms: dict[str, int] = field(default_factory=dict)
    turn_index: int = 0
    # Generated but never heard. Kept for failure analysis; never replayed into model context.
    unspoken_remainder: str | None = None
    # True when a cache breakpoint was requested but produced no cache activity — normally a
    # prefix shorter than the model's minimum cacheable length, which fails silently.
    cache_breakpoint_ineffective: bool = False
    # Resolved against this turn's own retrieved sources only (spec §16) — empty unless the tool
    # loop ran and at least one search_knowledge call actually found something.
    citations: list[Citation] = field(default_factory=list)
    # Empty unless the tool loop ran (ARCHITECTURE §10's `agent.activity`) — every tool this turn
    # actually executed, in call order, coarsely ok/not-ok. The voice path surfaces this live;
    # the full per-call detail (arguments, exact status, duration) is the `tool_calls` audit row.
    tool_activity: tuple[ToolActivityEntry, ...] = ()


class ConversationService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        messages: MessageRepository,
        ledger: UsageLedger,
        settings: Settings,
        db: AsyncSession | None = None,
        tool_registry: ToolRegistry | None = None,
        intent_gate: IntentGate | None = None,
        rag: RagService | None = None,
        student_profiles: StudentProfileRepository | None = None,
        window_cache: SessionWindowCache | None = None,
        memory_extractor: MemoryExtractor | None = None,
    ) -> None:
        """`db`/`tool_registry`/`intent_gate`/`rag`/`student_profiles`/`window_cache`/
        `memory_extractor` are all optional and all Phase 6: a caller that omits them gets the
        exact Phase 2/3 single-shot turn, unchanged. Tool execution additionally needs `db` and
        `rag` (a `ToolContext` cannot be built without them), so the tool loop only actually runs
        when every one of `tool_registry`, `db`, and `rag` is set. `intent_gate` decides the
        allowlist for that loop; if it is omitted while the others are set, the allowlist is empty
        (fail closed — no tool reachable, never "every tool reachable") rather than assumed to be
        everything in the registry. `window_cache` and `memory_extractor` are independent of the
        tool loop entirely — they run post-turn, off the critical path (`app.core.background`),
        and need only `db`/`student_profiles` (extractor) or nothing (window cache).
        """
        self._llm = llm
        self._messages = messages
        self._ledger = ledger
        self._settings = settings
        self._db = db
        self._tool_registry = tool_registry
        self._intent_gate = intent_gate
        self._rag = rag
        self._student_profiles = student_profiles
        self._window_cache = window_cache
        self._memory_extractor = memory_extractor

    async def history(self, session_id: uuid.UUID, *, limit: int = 20) -> list[TurnMessage]:
        """Recent turns as provider-neutral messages.

        Trimmed to the last `limit` messages: the context window is large, but every token resent
        costs money and latency, so history is bounded even where it would fit.
        """
        rows = await self._messages.list_for_session(session_id, limit=500)
        recent = [r for r in rows if r.role in (MessageRole.USER, MessageRole.ASSISTANT)][-limit:]
        return [
            TurnMessage(role="user" if r.role is MessageRole.USER else "assistant", text=r.content)
            for r in recent
        ]

    async def _recent_context(self, session_id: uuid.UUID) -> tuple[list[TurnMessage], str | None]:
        """Verbatim history plus the rolling summary of whatever is older than it.

        Cache-first (`sess:{id}:window`): a hit skips the Postgres query entirely and also
        recovers the summary, which `history()` alone has no way to produce. A miss — no
        `window_cache` configured, nothing cached yet, or a Redis outage — falls back to exactly
        `history()`'s existing Postgres-only behaviour, with no summary (ARCHITECTURE §13: losing
        this cache costs a rebuild, never correctness).
        """
        if self._window_cache is not None:
            window = await self._window_cache.get(session_id)
            if window is not None:
                return list(window.turns), window.summary
        history = await self.history(session_id, limit=self._settings.llm_history_turns)
        return history, None

    async def stream_turn(
        self,
        *,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        utterance: str,
        delivery: DeliveryTracker | None = None,
        language: str | None = None,
        marks: dict[str, int] | None = None,
        language_directive: str | None = None,
    ) -> AsyncGenerator[tuple[str, TurnResult | None], None]:
        """Run one turn, yielding `(text_fragment, None)` and finally `("", result)`.

        The caller is responsible for delivering fragments; this method is responsible for making
        the stored record match what was delivered.
        """
        # Refuse before spending, not after (Gate 0 finding M-11).
        await self._ledger.check_spend_cap()

        turn_index = await self._messages.next_turn_index(session_id)
        result = TurnResult(turn_index=turn_index)

        history, earlier_turns_summary = await self._recent_context(session_id)

        memory_digest: str | None = None
        if self._student_profiles is not None:
            profile = await self._student_profiles.get_or_create(student_id)
            memory_digest = profile.digest or None

        # Fail closed (see __init__): no intent_gate means no tool is offered, not every tool.
        allowed_tools: frozenset[str] = frozenset()
        if self._intent_gate is not None and self._tool_registry is not None:
            intent = await self._intent_gate.classify(utterance)
            allowed_tools = self._intent_gate.tools_for(intent)

        # The directive goes in a non-cacheable block, so it can change per turn without
        # invalidating the cached prefix (ARCHITECTURE §8.5).
        prompt = assemble(
            history=history,
            utterance=utterance,
            memory_digest=memory_digest,
            earlier_turns_summary=earlier_turns_summary,
            language_directive=language_directive,
        )

        await self._messages.append(
            session_id=session_id,
            turn_index=turn_index,
            seq=0,
            role=MessageRole.USER,
            content=utterance,
            language=language or script_of(utterance),
        )

        started = time.perf_counter()
        first_token_at: float | None = None
        chunks: list[str] = []
        usage = TokenUsage()
        model = self._llm.info.model
        # Populated only by the tool loop (search_knowledge merges its sources into this as it
        # runs); stays empty, and therefore never triggers citation resolution, on the plain path.
        citation_sources: dict[str, RetrievedChunk] = {}

        settled = False

        try:
            try:
                if (
                    self._tool_registry is not None
                    and self._db is not None
                    and self._rag is not None
                ):
                    tool_ctx = ToolContext(
                        student_id=student_id,
                        session_id=session_id,
                        turn_index=turn_index,
                        db=self._db,
                        rag=self._rag,
                        citation_sources=citation_sources,
                    )
                    async for fragment, outcome in run_agent_turn(
                        llm=self._llm,
                        system=prompt.system,
                        initial_messages=prompt.messages,
                        registry=self._tool_registry,
                        allowed_tool_names=allowed_tools,
                        tool_ctx=tool_ctx,
                        max_output_tokens=self._settings.llm_max_output_tokens,
                        effort=Effort(self._settings.llm_effort),
                    ):
                        if outcome is not None:
                            usage = outcome.usage
                            model = outcome.model
                            result.stop_reason = outcome.stop_reason
                            result.tool_activity = outcome.tool_activity
                        elif fragment:
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            chunks.append(fragment)
                            yield fragment, None
                else:
                    request = LLMRequest(
                        system=prompt.system,
                        messages=prompt.messages,
                        max_output_tokens=self._settings.llm_max_output_tokens,
                        effort=Effort(self._settings.llm_effort),
                    )
                    async for event in self._llm.stream(request):
                        if isinstance(event, TextDelta):
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            chunks.append(event.text)
                            yield event.text, None
                        elif isinstance(event, ToolCallDelta):
                            # No tools were offered on this path: the model invented one.
                            log.warning("conversation.unexpected_tool_call", tool=event.call.name)
                        elif isinstance(event, StreamCompleted):
                            usage = event.usage
                            model = event.model
                            result.stop_reason = event.stop_reason
                            result.cache_breakpoint_ineffective = event.cache_breakpoint_ineffective

                if result.stop_reason == "refusal" and not chunks:
                    # A decline must still produce something the mentor can say; an empty turn would
                    # read as the system having hung.
                    chunks.append(REFUSAL_REPLY)
                    yield REFUSAL_REPLY, None

            except ProviderError as exc:
                log.error(
                    "conversation.provider_failed",
                    provider=exc.provider,
                    retryable=exc.retryable,
                    exc_info=True,
                )
                result.stop_reason = "cancelled"
                chunks.append(FAILURE_REPLY)
                yield FAILURE_REPLY, None

            if delivery is not None:
                await delivery.settle()
            settled = True

        except (GeneratorExit, asyncio.CancelledError):
            # The consumer went away mid-stream, or the student interrupted before hearing all
            # of it. Keep the partial text: it is what the student actually received, and the
            # stored record must match that (Gate 0 finding C-03).
            result.interrupted = True
            raise

        finally:
            # Runs on the normal path, on a provider failure, and on cancellation (via the
            # generator's aclose), so a turn is never left unrecorded.
            generated = "".join(chunks)
            if delivery is not None and not settled:
                # What was heard, not what was generated. For a voice turn these differ by
                # however far generation ran ahead of playback.
                result.text = delivery.delivered()
                result.unspoken_remainder = delivery.remainder() or None
            else:
                # Settled means received in full, so what was generated is what was heard.
                result.text = generated
            result.language = language or (script_of(result.text) if result.text else None)
            result.cost = self._ledger.price_turn(model, usage)
            result.latency_ms["llm_total_ms"] = int((time.perf_counter() - started) * 1000)
            if first_token_at is not None:
                result.latency_ms["llm_ttft_ms"] = int((first_token_at - started) * 1000)
            if marks:
                # Voice turns carry the full nine-stage picture; a text turn has only its own two.
                result.latency_ms.update(marks)

            if citation_sources:
                # Resolved against exactly this turn's own retrieved sources — an id the model
                # invents, or one left over from how a previous turn numbered its own sources,
                # resolves to nothing (spec §16, app.rag.context).
                cited_refs = extract_cited_refs(result.text)
                result.citations = resolve_citations(
                    cited_refs, ContextBlock(text="", sources=citation_sources)
                )

            message_id = await self._persist_assistant_turn(
                session_id=session_id, turn_index=turn_index, result=result
            )
            if self._db is not None:
                # Commit now rather than leaving it to the request's own outer transaction scope:
                # a background task below connects on its own session and writes a memory_events
                # row with a foreign key to this message. That insert races an outer commit that
                # has not happened yet — a real foreign-key violation, not a theoretical one, is
                # exactly what an uncommitted message row produces (caught by a real test against
                # a real schema, not by inspection). expire_on_commit=False on every session this
                # service is built with means nothing already loaded needs a re-fetch afterwards.
                await self._db.commit()
            await self._ledger.record_turn(result.cost)

            # Off the critical path (app.core.background): the response has already been streamed
            # to the student by the time either of these runs. Independent of each other and of
            # the tool loop above — a window-cache outage must not block memory extraction or vice
            # versa, so each gets its own tracked task rather than one that fails as a unit.
            if self._window_cache is not None:
                spawn(
                    self._window_cache.record_turn(
                        session_id,
                        user_message=TurnMessage(role="user", text=utterance),
                        assistant_message=TurnMessage(role="assistant", text=result.text),
                    ),
                    name=f"memory_window.record_turn:{session_id}",
                )
            if self._memory_extractor is not None:
                spawn(
                    self._memory_extractor.extract_and_apply(
                        student_id=student_id,
                        session_id=session_id,
                        message_id=message_id,
                        utterance=utterance,
                        reply=result.text,
                    ),
                    name=f"memory_extractor.extract_and_apply:{session_id}",
                )
            log.info(
                "conversation.turn_completed",
                session_id=str(session_id),
                turn_index=turn_index,
                stop_reason=result.stop_reason,
                interrupted=result.interrupted,
                prompt_version=PROMPT_VERSION,
                cache_read_tokens=usage.cache_read_input_tokens,
                estimated_cost_usd=round(result.cost.cost_usd, 6) if result.cost else 0.0,
                **result.latency_ms,
            )

        yield "", result

    async def _persist_assistant_turn(
        self, *, session_id: uuid.UUID, turn_index: int, result: TurnResult
    ) -> uuid.UUID:
        token_usage = result.cost.as_dict() if result.cost else None
        message = await self._messages.append(
            session_id=session_id,
            turn_index=turn_index,
            seq=1,
            role=MessageRole.ASSISTANT,
            content=result.text,
            language=result.language,
            was_interrupted=result.interrupted,
            # For a text turn the "spoken prefix" is what was actually sent to the client.
            spoken_prefix_chars=len(result.text) if result.interrupted else None,
            unspoken_remainder=result.unspoken_remainder if result.interrupted else None,
            latency_ms=result.latency_ms,
            token_usage=token_usage,
        )
        return message.id
