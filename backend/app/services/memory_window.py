"""The short-term session memory cache (ARCHITECTURE §12/§13, ADR-0012).

`sess:{id}:window` holds the last `capacity` turns verbatim plus a rolling summary of what has
aged out of that window, TTL 2 hours. Postgres (`messages`) remains the record of truth — this is
a *cache*, not a second store: `ConversationService` falls back to its existing Postgres query on a
miss or a Redis outage, exactly as it did before this class existed (see `_recent_context`).
Losing this key costs one cache-rebuild, never a conversation.

The rolling summary is what lets a session survive past `capacity` turns without either resending
the full transcript on every request or silently forgetting everything before it: once the window
is full, folding in a new turn pushes the oldest one out, and that overflow is compressed into the
summary by one small, cheap (`Effort.LOW`) LLM call rather than dropped. That call runs off the
critical path (`app.core.background`), the same way `MemoryExtractor` does — once a session is long
enough to be full, the window overflows on every subsequent turn, and paying for that inline on
every turn of a long conversation is exactly the latency this tier exists to avoid.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import redis.asyncio as redis
import structlog

from app.providers.base import ProviderError
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRequest,
    StreamCompleted,
    SystemBlock,
    TurnMessage,
)
from app.providers.llm.base import TextDelta as LLMTextDelta

log = structlog.get_logger(__name__)

_TTL_SECONDS = 2 * 3600

_FOLD_SYSTEM = SystemBlock(
    text=(
        "Compress the following older exchange from an ongoing tutoring conversation into at "
        "most two short sentences: which topics came up, and anything the student struggled "
        "with or asked to revisit. No greetings, no small talk, no preamble. Reply with only "
        "the summary text."
    ),
    cacheable=False,
)


@dataclass(frozen=True)
class SessionWindow:
    turns: tuple[TurnMessage, ...]
    summary: str | None = None


class SessionWindowCache:
    def __init__(self, client: redis.Redis, *, capacity: int, llm: LLMProvider) -> None:
        self._redis = client
        self._capacity = capacity
        self._llm = llm

    @staticmethod
    def _key(session_id: uuid.UUID) -> str:
        return f"sess:{session_id}:window"

    async def get(self, session_id: uuid.UUID) -> SessionWindow | None:
        try:
            raw = await self._redis.get(self._key(session_id))
        except redis.RedisError:
            log.warning("memory_window.read_failed", session_id=str(session_id), exc_info=True)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            turns = tuple(
                TurnMessage(role=t["role"], text=t["text"])
                for t in data["turns"]
                if t["role"] in ("user", "assistant")
            )
            return SessionWindow(turns=turns, summary=data.get("summary") or None)
        except (ValueError, KeyError, TypeError):
            # A schema change or a bit-rotted entry, not a call site bug — treated as a miss, not
            # a crash, same as any other cache corruption.
            log.warning("memory_window.corrupt_entry", session_id=str(session_id))
            return None

    async def record_turn(
        self, session_id: uuid.UUID, *, user_message: TurnMessage, assistant_message: TurnMessage
    ) -> None:
        """Append this turn, folding whatever falls out of the window into the rolling summary."""
        window = await self.get(session_id) or SessionWindow(turns=())
        new_turns = (*window.turns, user_message, assistant_message)

        if len(new_turns) > self._capacity:
            overflow_count = len(new_turns) - self._capacity
            overflow, keep = new_turns[:overflow_count], new_turns[overflow_count:]
            summary = await self._fold(window.summary, overflow)
        else:
            keep, summary = new_turns, window.summary

        await self._replace(session_id, SessionWindow(turns=keep, summary=summary))

    async def _fold(self, existing: str | None, overflow: tuple[TurnMessage, ...]) -> str | None:
        transcript = "\n".join(f"{m.role}: {m.text}" for m in overflow if m.text)
        if not transcript:
            return existing

        prior = f"Summary so far: {existing}\n\n" if existing else ""
        fold_text = f"{prior}New exchange to fold in:\n{transcript}"
        request = LLMRequest(
            system=[_FOLD_SYSTEM],
            messages=[TurnMessage(role="user", text=fold_text)],
            max_output_tokens=120,
            effort=Effort.LOW,
        )
        text = ""
        try:
            async for event in self._llm.stream(request):
                if isinstance(event, LLMTextDelta):
                    text += event.text
                elif isinstance(event, StreamCompleted) and event.stop_reason == "refusal":
                    return existing
        except ProviderError:
            # A summarisation hiccup must not lose the turn itself — the overflow is simply
            # dropped from the window this time, same as if the cache had expired.
            log.warning("memory_window.fold_failed", exc_info=True)
            return existing
        return text.strip() or existing

    async def _replace(self, session_id: uuid.UUID, window: SessionWindow) -> None:
        payload = json.dumps(
            {
                "turns": [{"role": t.role, "text": t.text} for t in window.turns],
                "summary": window.summary,
            }
        )
        try:
            await self._redis.set(self._key(session_id), payload, ex=_TTL_SECONDS)
        except redis.RedisError:
            log.warning("memory_window.write_failed", session_id=str(session_id), exc_info=True)
