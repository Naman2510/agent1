"""Local speech recognition with faster-whisper (ADR-0002).

For evaluation, CI and fully local development — not the real-time path, which ADR-0002 gives to
a managed streaming recogniser. Whisper is not a streaming model: this adapter hears the utterance
as it arrives but transcribes it once, when it ends. So it sends no partials, and the turn
detector has no stable prefix to read (semantic endpointing, EXP-003, has nothing to act on).

It needs the `voice-local` extra (`pip install -e '.[voice-local]'`), which the production image
does not install, and the model weights, which faster-whisper fetches from Hugging Face on first
use — something some networks block, this project's own development environment among them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import numpy as np

from app.providers.base import Capability, ProviderInfo
from app.providers.stt.base import (
    AudioFormat,
    FinalTranscript,
    STTProvider,
    TranscriptEvent,
    TranscriptionContext,
)


@lru_cache(maxsize=2)
def load_model(model_size: str, compute_type: str = "int8") -> Any:
    """One model per process: loading takes seconds, and every voice connection needs one."""
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type=compute_type)


class FasterWhisperSTT(STTProvider):
    def __init__(
        self,
        model_size: str = "small",
        *,
        compute_type: str = "int8",
        beam_size: int = 5,
        language: str | None = None,
        model: Any = None,
    ) -> None:
        """`language` None lets Whisper detect it per utterance, as it must for a student who
        switches mid-session. `model` is for tests; normally it is loaded (and shared)."""
        self._model_size = model_size
        self._model = model if model is not None else load_model(model_size, compute_type)
        self._beam_size = beam_size
        self._language = language

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="stt",
            name="faster-whisper",
            model=self._model_size,
            capabilities=frozenset({Capability.LANGUAGE_HINT}),
        )

    @property
    def audio_format(self) -> AudioFormat:
        return AudioFormat()

    async def transcribe_stream(
        self,
        frames: AsyncIterator[bytes],
        context: TranscriptionContext | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        pcm = bytearray()
        async for chunk in frames:
            pcm.extend(chunk)
        if not pcm:
            yield FinalTranscript(text="")
            return
        audio = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0
        # Off the event loop: a few hundred milliseconds of CPU per utterance would stall every
        # other connection's audio.
        yield await asyncio.to_thread(self._transcribe, audio)

    def _transcribe(self, audio: np.ndarray) -> FinalTranscript:
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            # Each utterance stands alone; carrying text across is how Whisper repeats itself.
            condition_on_previous_text=False,
            # The session's own VAD already decided where the speech is.
            vad_filter=False,
        )
        # `segments` is lazy: iterating it is the transcription, so it happens here, off-loop.
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return FinalTranscript(
            text=text,
            language_hint=info.language,
            confidence=float(info.language_probability),
            duration_ms=round(float(info.duration) * 1000),
        )
