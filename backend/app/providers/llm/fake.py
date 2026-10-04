"""Deterministic LLM double for tests and offline development.

Mocking at the provider interface rather than at HTTP is what keeps tier-T0 CI free and
deterministic while still exercising the real orchestration, persistence and streaming code
(EVALUATION.md §6).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from app.providers.base import Capability, ProviderError, ProviderInfo
from app.providers.llm.base import (
    LLMProvider,
    LLMRequest,
    StopReason,
    StreamCompleted,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
)


@dataclass
class ScriptedTurn:
    """One canned response."""

    text: str = ""
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    stop_reason: StopReason = "end_turn"
    usage: TokenUsage = field(default_factory=lambda: TokenUsage(input_tokens=42, output_tokens=7))
    raise_error: ProviderError | None = None


class FakeLLMProvider(LLMProvider):
    """Replays scripted turns and records the requests it was given.

    `requests` is the useful part: assertions about cache-breakpoint placement, tool exposure and
    prompt ordering are made against what the application actually asked for.
    """

    def __init__(
        self,
        turns: Sequence[ScriptedTurn] | None = None,
        *,
        model: str = "fake-llm-1",
        chunk_size: int = 8,
    ) -> None:
        self._turns = list(turns or [ScriptedTurn(text="This is a fake mentor response.")])
        self._model = model
        self._chunk_size = chunk_size
        self._index = 0
        self.requests: list[LLMRequest] = []

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="llm",
            name="fake",
            model=self._model,
            capabilities=frozenset({Capability.TOOL_CALLING, Capability.PROMPT_CACHING}),
        )

    @property
    def last_request(self) -> LLMRequest:
        if not self.requests:
            raise AssertionError("no request was made")
        return self.requests[-1]

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        turn = self._turns[min(self._index, len(self._turns) - 1)]
        self._index += 1

        if turn.raise_error is not None:
            raise turn.raise_error

        # Chunked so tests exercise incremental delivery rather than a single blob.
        for start in range(0, len(turn.text), self._chunk_size):
            yield TextDelta(text=turn.text[start : start + self._chunk_size])

        for call in turn.tool_calls:
            yield ToolCallDelta(call=call)

        yield StreamCompleted(stop_reason=turn.stop_reason, usage=turn.usage, model=self._model)

    async def count_tokens(self, request: LLMRequest) -> int:
        # A crude but deterministic stand-in; no test should depend on the exact value.
        text = "".join(b.text for b in request.system) + "".join(m.text for m in request.messages)
        return max(1, len(text) // 4)
