"""Local speech recognition with faster-whisper (ADR-0002).

For evaluation, CI and fully local development — not the real-time path, which ADR-0002 gives to
a managed streaming recogniser. Whisper is not a streaming model: this adapter hears the utterance
as it arrives but transcribes it once, when it ends. So it sends no partials, and the turn
detector has no stable prefix to read (semantic endpointing, EXP-003, has nothing to act on).

It needs the `voice-local` extra (`pip install -e '.[voice-local]'`), which the production image
does not install, and the model weights, which faster-whisper fetches from Hugging Face on first
use — something some networks block, this project's own development environment among them.

Whisper's own decoding is beam search and then, when the result looks wrong (too repetitive, or
too unlikely), the whole decode again by sampling at each of five rising temperatures, each pass up
to the model's length limit. Audio it cannot make sense of, eSpeak's Hindi among it (FC-005), costs
six passes, and in a conversation that is longer than the session waits. The wait ends but the
decode does not: nothing can stop one once started, and the model serves one decode at a time, for
every connection in the process, so each later utterance waited behind it and failed too (FC-019).
So this adapter decodes once by default, and stops at a length no speech of that duration needs.
The stt suite measures both ways (eval/configs/stt.toml, stt-live.toml). The fallback's sampling is
unseeded, so the same audio can come back as different text on another run; the stt suite seeds it.
"""

from __future__ import annotations

import asyncio
import math
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

# Whisper's own retry schedule, faster-whisper's default: when a decode looks wrong, decode again at
# the next temperature. Six passes at worst.
WHISPER_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
# A decode's length budget, per second of audio. Generous: the voice dataset's Hindi runs at up to
# 13 characters a second, and Devanagari can take a token or more a character (English, about four
# characters a token, needs a fraction of it). Repetition, Whisper's way of failing, runs on to the
# model's limit without one.
LIVE_TOKENS_PER_SECOND = 20
# Room for the timestamps and the shortest utterances, and Whisper's usual cap on a decode (half
# its 448-token context, which the prompt also takes from).
MIN_NEW_TOKENS = 32
MAX_NEW_TOKENS = 224


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
        temperature: float | tuple[float, ...] = 0.0,
        tokens_per_second: float | None = LIVE_TOKENS_PER_SECOND,
        model: Any = None,
    ) -> None:
        """`language` None lets Whisper detect it per utterance, as it must for a student who
        switches mid-session. `temperature` and `tokens_per_second` bound each decode (FC-019):
        `WHISPER_FALLBACK` and None are Whisper's own unbounded decoding. `model` is for tests;
        normally it is loaded (and shared)."""
        self._model_size = model_size
        self._model = model if model is not None else load_model(model_size, compute_type)
        self._beam_size = beam_size
        self._language = language
        self._temperature = temperature
        self._tokens_per_second = tokens_per_second

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
        yield await asyncio.to_thread(self.transcribe, audio)

    def transcribe(self, audio: np.ndarray) -> FinalTranscript:
        """One whole utterance (float32, 16 kHz mono), synchronously: what `transcribe_stream` runs
        off the event loop, and what the stt suite measures."""
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            temperature=self._temperature,
            max_new_tokens=self.token_budget(audio.size / AudioFormat().sample_rate),
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

    def token_budget(self, seconds: float) -> int | None:
        """The most tokens a decode of `seconds` of audio may produce; None is no limit."""
        if self._tokens_per_second is None:
            return None
        return min(MAX_NEW_TOKENS, MIN_NEW_TOKENS + math.ceil(seconds * self._tokens_per_second))
