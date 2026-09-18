"""Speech-to-text interface (ADR-0002).

Partials are explicitly unstable. Whisper-family models are not streaming models — partials come
from re-decoding a growing buffer with a stability policy — so `stable_prefix_chars` tells the
caller how much of the text is safe to show without it visibly rewriting itself.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.providers.base import ProviderInfo


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int = 16_000
    channels: int = 1
    sample_width_bytes: int = 2  # 16-bit signed little-endian PCM


@dataclass(frozen=True)
class PartialTranscript:
    text: str
    stable_prefix_chars: int = 0
    language_hint: str | None = None


@dataclass(frozen=True)
class FinalTranscript:
    text: str
    # A weak signal only: providers tend to label romanized Hindi as English (ADR-0011).
    language_hint: str | None = None
    confidence: float | None = None
    duration_ms: int = 0


TranscriptEvent = PartialTranscript | FinalTranscript


@dataclass(frozen=True)
class TranscriptionContext:
    """Per-utterance hints. Ignored by providers that do not declare the capability."""

    language_hints: tuple[str, ...] = ()
    # Subject vocabulary and the student's current topic, to bias technical terms (EXP-002).
    vocabulary: tuple[str, ...] = field(default_factory=tuple)


class STTProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    @abc.abstractmethod
    def audio_format(self) -> AudioFormat: ...

    @abc.abstractmethod
    def transcribe_stream(
        self,
        frames: AsyncIterator[bytes],
        context: TranscriptionContext | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """Transcribe a stream of PCM frames.

        Yields zero or more partials and exactly one final per utterance. Cancelling the consumer
        must abort the upstream request.
        """

    async def aclose(self) -> None:  # pragma: no cover
        return None
