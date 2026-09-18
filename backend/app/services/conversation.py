"""The text turn: assemble, stream, persist.

This is the Phase 2 slice of the orchestrator. It owns what ARCHITECTURE §4 calls a turn — one
user utterance, one assistant reply — with per-stage timing and honest accounting, and without
tools, retrieval or memory, which arrive in Phases 5 and 6.

One invariant is enforced here even though the thing that makes it matter (barge-in) does not
exist yet: **what is stored is what the user actually received.** If the consumer goes away
mid-stream, the partial text is persisted and marked interrupted rather than the full generation
being written as though it had been delivered. Getting this wrong means the mentor later refers to
things the student never saw (Gate 0 finding C-03).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from app.agent.language import script_of
from app.agent.prompts import PROMPT_VERSION, assemble
from app.core.config import Settings
from app.db.models import MessageRole
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


class ConversationService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        messages: MessageRepository,
        ledger: UsageLedger,
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._messages = messages
        self._ledger = ledger
        self._settings = settings

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

    async def stream_turn(
        self,
        *,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        utterance: str,
        delivery: DeliveryTracker | None = None,
        language: str | None = None,
        marks: dict[str, int] | None = None,
    ) -> AsyncGenerator[tuple[str, TurnResult | None], None]:
        """Run one turn, yielding `(text_fragment, None)` and finally `("", result)`.

        The caller is responsible for delivering fragments; this method is responsible for making
        the stored record match what was delivered.
        """
        # Refuse before spending, not after (Gate 0 finding M-11).
        await self._ledger.check_spend_cap()

        turn_index = await self._messages.next_turn_index(session_id)
        result = TurnResult(turn_index=turn_index)

        history = await self.history(session_id, limit=self._settings.llm_history_turns)
        prompt = assemble(history=history, utterance=utterance)

        request = LLMRequest(
            system=prompt.system,
            messages=prompt.messages,
            max_output_tokens=self._settings.llm_max_output_tokens,
            effort=Effort(self._settings.llm_effort),
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

        try:
            async for event in self._llm.stream(request):
                if isinstance(event, TextDelta):
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    chunks.append(event.text)
                    yield event.text, None
                elif isinstance(event, ToolCallDelta):
                    # No tools are offered in Phase 2, so this means the model invented one.
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

        except (GeneratorExit, asyncio.CancelledError):
            # The consumer went away mid-stream. Keep the partial text: it is what the student
            # actually received, and the stored record must match that (Gate 0 finding C-03).
            result.interrupted = True
            raise

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

        finally:
            # Runs on the normal path, on a provider failure, and on cancellation (via the
            # generator's aclose), so a turn is never left unrecorded.
            generated = "".join(chunks)
            if delivery is not None:
                # What was heard, not what was generated. For a voice turn these differ by
                # however far generation ran ahead of playback.
                result.text = delivery.delivered()
                result.unspoken_remainder = delivery.remainder() or None
            else:
                result.text = generated
            result.language = language or (script_of(result.text) if result.text else None)
            result.cost = self._ledger.price_turn(model, usage)
            result.latency_ms["llm_total_ms"] = int((time.perf_counter() - started) * 1000)
            if first_token_at is not None:
                result.latency_ms["llm_ttft_ms"] = int((first_token_at - started) * 1000)
            if marks:
                # Voice turns carry the full nine-stage picture; a text turn has only its own two.
                result.latency_ms.update(marks)

            await self._persist_assistant_turn(
                session_id=session_id, turn_index=turn_index, result=result
            )
            await self._ledger.record_turn(result.cost)
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
    ) -> None:
        token_usage = result.cost.as_dict() if result.cost else None
        await self._messages.append(
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
