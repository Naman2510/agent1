"""Deterministic STT double."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.providers.base import Capability, ProviderInfo
from app.providers.stt.base import (
    AudioFormat,
    FinalTranscript,
    PartialTranscript,
    STTProvider,
    TranscriptEvent,
    TranscriptionContext,
)


class FakeSTTProvider(STTProvider):
    def __init__(
        self,
        transcript: str = "Kirchhoff ka voltage law samjhao",
        *,
        language: str = "hi-Latn",
        partials: int = 2,
    ) -> None:
        self._transcript = transcript
        self._language = language
        self._partials = partials
        self.contexts: list[TranscriptionContext | None] = []
        self.frame_count = 0

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="stt",
            name="fake",
            model="fake-stt-1",
            capabilities=frozenset({Capability.LANGUAGE_HINT, Capability.CONTEXTUAL_VOCABULARY}),
        )

    @property
    def audio_format(self) -> AudioFormat:
        return AudioFormat()

    async def transcribe_stream(
        self,
        frames: AsyncIterator[bytes],
        context: TranscriptionContext | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        self.contexts.append(context)
        async for _frame in frames:
            self.frame_count += 1

        words: Sequence[str] = self._transcript.split()
        for index in range(1, self._partials + 1):
            cut = max(1, len(words) * index // (self._partials + 1))
            text = " ".join(words[:cut])
            # Deliberately understates stability, as a real LocalAgreement policy does.
            yield PartialTranscript(
                text=text, stable_prefix_chars=len(text) // 2, language_hint=self._language
            )

        yield FinalTranscript(
            text=self._transcript,
            language_hint=self._language,
            confidence=0.91,
            duration_ms=self.frame_count * 20,
        )
