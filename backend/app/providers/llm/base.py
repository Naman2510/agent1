"""The LLM provider interface.

Deliberately not a thin pass-through of one vendor's request shape: the parts this application
needs to control — where the cache breakpoints sit, how tools are declared, what a refusal does,
how usage is reported — are first-class here, and vendor-specific tuning lives in the adapter.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from app.providers.base import ProviderInfo

Role = Literal["user", "assistant"]


class Effort(StrEnum):
    """How much the model should spend on a turn.

    A latency/quality dial, not a model downgrade. The right setting per route is a measured
    question (EXP-004), so it is configuration rather than a constant.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class SystemBlock:
    """A block of system prompt, with an explicit cache intent.

    `cacheable=True` means "this text is stable across turns, so a cache breakpoint may be placed
    after it". Anything that changes per turn must be `False`, or it invalidates the prefix and
    silently costs money on every request.
    """

    text: str
    cacheable: bool = False


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model.

    `strict` requests schema-valid arguments from the API, which is what makes typed tool inputs
    (spec §13) a guarantee rather than a hope.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class TurnMessage:
    """One message of conversation history.

    `tool_calls` and `tool_results` are carried here so the adapter can rebuild provider-native
    blocks; the application never stores a vendor's message format.
    """

    role: Role
    text: str = ""
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    tool_results: Sequence[ToolResult] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMRequest:
    system: Sequence[SystemBlock]
    messages: Sequence[TurnMessage]
    tools: Sequence[ToolSpec] = field(default_factory=tuple)
    max_output_tokens: int = 1024
    effort: Effort | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
        }


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "cancelled"]


# --- stream events ---------------------------------------------------------


@dataclass(frozen=True)
class TextDelta:
    """A fragment of the answer. Fed straight to the sentence chunker in the voice path."""

    text: str


@dataclass(frozen=True)
class ToolCallDelta:
    """A completed tool-call request. Emitted whole rather than incrementally: the orchestrator
    cannot act on half a set of arguments, and partial JSON is a known source of silent
    truncation bugs."""

    call: ToolCall


@dataclass(frozen=True)
class StreamCompleted:
    stop_reason: StopReason
    usage: TokenUsage
    model: str
    # True when a cache breakpoint was requested but the provider reported no cache activity —
    # usually a prefix below the model's minimum cacheable length, which fails silently.
    cache_breakpoint_ineffective: bool = False


StreamEvent = TextDelta | ToolCallDelta | StreamCompleted


class LLMProvider(abc.ABC):
    """Streaming text generation with tool calling."""

    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @abc.abstractmethod
    def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        """Stream a response.

        Yields zero or more `TextDelta`/`ToolCallDelta` events and exactly one
        `StreamCompleted` as the final event. Cancelling the consuming task must abort the
        upstream request — barge-in depends on it.
        """

    @abc.abstractmethod
    async def count_tokens(self, request: LLMRequest) -> int:
        """Token count for a request, from the provider's own tokenizer.

        Never estimated locally: a third-party tokenizer gives a number that is wrong in a way
        that looks right.
        """

    async def aclose(self) -> None:  # pragma: no cover - adapters override when needed
        return None
