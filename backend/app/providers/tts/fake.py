"""Deterministic TTS double: emits silence of a plausible duration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.providers.base import Capability, ProviderInfo
from app.providers.tts.base import SynthesisRequest, TTSProvider, Voice

_VOICES = (
    Voice(id="fake-en", language="en", provider_model="fake-tts-1"),
    Voice(id="fake-hi", language="hi", provider_model="fake-tts-1"),
    Voice(id="fake-ta", language="ta", provider_model="fake-tts-1"),
)


class FakeTTSProvider(TTSProvider):
    def __init__(
        self,
        *,
        chars_per_second: float = 14.0,
        chunk_bytes: int = 960,
        chunk_delay_s: float = 0.0,
    ) -> None:
        self._chars_per_second = chars_per_second
        self._chunk_bytes = chunk_bytes
        # A non-zero delay yields to the event loop between chunks, which is what lets a test
        # interrupt a turn that is genuinely in flight rather than one already finished.
        self._chunk_delay_s = chunk_delay_s
        self.requests: list[SynthesisRequest] = []

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="tts",
            name="fake",
            model="fake-tts-1",
            capabilities=frozenset({Capability.STREAMING_SYNTHESIS, Capability.INDIC_VOICES}),
        )

    def voices(self) -> tuple[Voice, ...]:
        return _VOICES

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        self.requests.append(request)
        # Duration proportional to text length, so playback-position tests (the barge-in spoken
        # prefix ledger) have something realistic to measure.
        seconds = max(0.08, len(request.text) / self._chars_per_second)
        total_bytes = int(seconds * request.sample_rate) * 2
        emitted = 0
        while emitted < total_bytes:
            size = min(self._chunk_bytes, total_bytes - emitted)
            if self._chunk_delay_s:
                await asyncio.sleep(self._chunk_delay_s)
            yield b"\x00" * size
            emitted += size
