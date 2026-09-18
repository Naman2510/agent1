"""Types shared by every provider interface.

The boundaries here exist because each one has a real competing implementation that the evaluation
suites will compare (ADR-0016). Two rules apply to all of them:

* **Capabilities are declared, not assumed.** Providers differ (streaming ASR, contextual
  vocabulary, word timestamps). Rather than flattening every interface to a lowest common
  denominator, a provider states what it supports and callers degrade explicitly — silently
  ignoring a requested capability would corrupt experiment results.
* **Streaming providers must be cancellable.** Barge-in aborts generation and synthesis mid-flight
  (ARCHITECTURE §5.2), so every streaming method is an async generator: cancelling the consuming
  task closes the upstream stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProviderError(Exception):
    """A provider failed in a way the caller may be able to handle.

    `retryable` distinguishes a transient upstream problem from a request that will never work.
    """

    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached at all."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class Capability(StrEnum):
    """Optional behaviours a provider may or may not support."""

    # LLM
    TOOL_CALLING = "tool_calling"
    PROMPT_CACHING = "prompt_caching"
    EFFORT_CONTROL = "effort_control"
    REFUSAL_FALLBACK = "refusal_fallback"
    # STT
    TRUE_STREAMING = "true_streaming"  # incremental decode, not repeated re-decode
    CONTEXTUAL_VOCABULARY = "contextual_vocabulary"
    WORD_TIMESTAMPS = "word_timestamps"
    LANGUAGE_HINT = "language_hint"
    # TTS
    STREAMING_SYNTHESIS = "streaming_synthesis"
    INDIC_VOICES = "indic_voices"


@dataclass(frozen=True)
class ProviderInfo:
    """Identity recorded in telemetry and in every `evaluation_runs.config`.

    Without this a metric is ambiguous about what produced it, which makes the whole evaluation
    framework unfalsifiable.
    """

    kind: str  # llm | stt | tts | embedding | reranker | vector
    name: str  # adapter name, e.g. "anthropic"
    model: str  # exact model identifier
    capabilities: frozenset[Capability] = field(default_factory=frozenset)

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "model": self.model,
            "capabilities": sorted(str(c) for c in self.capabilities),
        }
