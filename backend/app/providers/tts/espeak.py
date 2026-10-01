"""Local speech synthesis with eSpeak NG (ADR-0018).

For development, evaluation and CI, not the real-time path, which ADR-0003 gives to a managed
streaming provider. eSpeak NG is a formant synthesiser: intelligible, robotic, and the same on
every run. Nothing about how it sounds says how a neural or managed voice would sound (ADR-0003
keeps voice quality to human ratings). It is here so that a voice turn ends in real speech without
a network or a credential, and so the voice loop can be timed with a synthesiser that does real
work.

Each chunk (a sentence) is synthesised whole, then streamed in 20 ms frames at the session's rate.
That is still streaming where the design needs it: audio starts on the first sentence, not the
last (ARCHITECTURE §6). eSpeak NG takes about 25 ms on one core for a sentence that plays for about
four seconds. Barge-in cancels synthesis by killing the process.

It needs the `espeak-ng` program (`apt install espeak-ng`), which the production image does not
install.
"""

from __future__ import annotations

import asyncio
import functools
import math
import shutil
import subprocess
from collections.abc import AsyncIterator

import numpy as np
from scipy.signal import resample_poly

from app.providers.base import Capability, ProviderError, ProviderInfo
from app.providers.tts.base import SynthesisRequest, TTSProvider, Voice

# eSpeak NG's output: mono, 16-bit, 22,050 samples a second.
ESPEAK_RATE = 22_050
FRAME_MS = 20
# Slower than eSpeak's default of 175, which is quick for an explanation.
WORDS_PER_MINUTE = 160

# The voice for each language the system routes (agent/lang/policy.py), by eSpeak NG's own name.
# None of them has an Indian accent, and none is claimed to (ADR-0003's honesty rule).
VOICES = {"en": "en-us", "hi": "hi", "ta": "ta"}


class EspeakNotInstalledError(RuntimeError):
    """The configured synthesiser is not on this machine: a configuration error, raised at
    startup rather than at a student's first answer."""


@functools.cache
def _version(binary: str) -> str:
    out = subprocess.run(  # noqa: S603 - the resolved espeak-ng binary, fixed arguments
        [binary, "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout
    # "eSpeak NG text-to-speech: 1.51  Data at: ..."
    return out.split(":", 1)[1].split()[0] if ":" in out else out.strip()


def pcm_from_wav(data: bytes) -> np.ndarray:
    """The samples of eSpeak NG's `--stdout` output. Writing to a pipe, it cannot seek back to fill
    in the sizes, so the header's sizes are placeholders: the samples are whatever follows the
    `data` chunk's header."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV stream")
    position = 12
    channels = rate = width = None
    while position + 8 <= len(data):
        chunk = data[position : position + 4]
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        body = position + 8
        if chunk == b"fmt ":
            channels = int.from_bytes(data[body + 2 : body + 4], "little")
            rate = int.from_bytes(data[body + 4 : body + 8], "little")
            width = int.from_bytes(data[body + 14 : body + 16], "little") // 8
            position = body + size + (size & 1)
        elif chunk == b"data":
            if (channels, rate, width) != (1, ESPEAK_RATE, 2):
                found = f"{channels} channels, {rate} Hz, {width} bytes a sample"
                raise ValueError(f"unexpected format: {found}")
            samples = data[body:]
            return np.frombuffer(samples[: len(samples) // 2 * 2], dtype="<i2")
        else:
            position = body + size + (size & 1)
    raise ValueError("no audio in the WAV stream")


def resample(samples: np.ndarray, rate: int) -> bytes:
    """eSpeak NG's 22,050 Hz audio at the session's rate, as 16-bit little-endian PCM."""
    if rate == ESPEAK_RATE or samples.size == 0:
        return samples.astype("<i2").tobytes()
    common = math.gcd(rate, ESPEAK_RATE)
    resampled = resample_poly(samples.astype(np.float64), rate // common, ESPEAK_RATE // common)
    return np.clip(np.rint(resampled), -32768, 32767).astype("<i2").tobytes()


class EspeakTTSProvider(TTSProvider):
    def __init__(
        self, *, binary: str | None = None, words_per_minute: int = WORDS_PER_MINUTE
    ) -> None:
        path = binary or shutil.which("espeak-ng")
        if path is None:
            raise EspeakNotInstalledError(
                "tts_provider=espeak needs the espeak-ng program (apt install espeak-ng), which "
                "the production image does not install (ADR-0018)"
            )
        self._binary = path
        self._words_per_minute = words_per_minute
        self._model = f"espeak-ng {_version(path)}"
        self._voices = tuple(
            Voice(id=voice, language=language, provider_model=self._model)
            for language, voice in VOICES.items()
        )

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="tts",
            name="espeak",
            model=self._model,
            capabilities=frozenset({Capability.STREAMING_SYNTHESIS, Capability.INDIC_VOICES}),
        )

    def voices(self) -> tuple[Voice, ...]:
        return self._voices

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        # The text goes in on standard input, never as an argument: an answer that begins with a
        # dash must not become an option.
        process = await asyncio.create_subprocess_exec(
            self._binary,
            "-v",
            request.voice.id,
            "-s",
            str(self._words_per_minute),
            "--stdin",
            "--stdout",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await process.communicate(request.text.encode("utf-8"))
        except BaseException:
            # Cancelled mid-synthesis: a barge-in, or a stall timeout. Nothing is left running.
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            raise ProviderError(
                f"espeak-ng exited {process.returncode}: {err.decode(errors='replace').strip()}",
                provider="espeak",
            )
        try:
            samples = pcm_from_wav(out)
        except ValueError as exc:
            raise ProviderError(f"espeak-ng output unreadable: {exc}", provider="espeak") from exc
        audio = await asyncio.to_thread(resample, samples, request.sample_rate)
        frame = request.sample_rate * FRAME_MS // 1000 * 2
        for start in range(0, len(audio), frame):
            yield audio[start : start + frame]
