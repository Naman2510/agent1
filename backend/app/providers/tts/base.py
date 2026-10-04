"""Text-to-speech interface (ADR-0003).

Synthesis is per-chunk and streaming: audio must start on the first sentence, not the last
(ARCHITECTURE §6). Cancellation must abort synthesis mid-chunk, because barge-in depends on it.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.providers.base import ProviderInfo


@dataclass(frozen=True)
class Voice:
    """The exact voice in use.

    Recorded in full in telemetry and documentation. "Indian accent" is never claimed because a
    provider labels a voice that way (ADR-0003); what is claimed is the provider, model and id.
    """

    id: str
    language: str
    provider_model: str


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    voice: Voice
    # Playback rate in samples/second, needed by the client to schedule audio correctly.
    sample_rate: int = 24_000


class TTSProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @abc.abstractmethod
    def voices(self) -> tuple[Voice, ...]:
        """Available voices. Selection is per language, and per script for code-switched text."""

    @abc.abstractmethod
    def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        """Stream audio for one chunk of text."""

    async def aclose(self) -> None:  # pragma: no cover
        return None
