"""The local synthesiser (app/providers/tts/espeak.py, ADR-0018).

What needs speech uses the real espeak-ng, which CI installs; elsewhere those tests skip. What
needs a synthesiser to hang or fail uses a stand-in program, so it happens every time.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.registry import build_tts
from app.providers.tts import espeak
from app.providers.tts.base import SynthesisRequest
from app.providers.tts.espeak import (
    ESPEAK_RATE,
    EspeakNotInstalledError,
    EspeakTTSProvider,
    pcm_from_wav,
    resample,
)

requires_espeak = pytest.mark.skipif(
    shutil.which("espeak-ng") is None and not os.environ.get("CI"),
    reason="needs espeak-ng (apt install espeak-ng); CI installs it",
)


def _header(*, rate: int = ESPEAK_RATE, channels: int = 1, bits: int = 16) -> bytes:
    """A WAV header as eSpeak NG streams it: the sizes are placeholders it cannot go back to fill
    in, since it writes to a pipe."""
    block = channels * bits // 8
    fmt = (
        (1).to_bytes(2, "little")
        + channels.to_bytes(2, "little")
        + rate.to_bytes(4, "little")
        + (rate * block).to_bytes(4, "little")
        + block.to_bytes(2, "little")
        + bits.to_bytes(2, "little")
    )
    placeholder = 0x7FFFF000
    return (
        b"RIFF"
        + (placeholder + 36).to_bytes(4, "little")
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little")
        + fmt
        + b"data"
        + placeholder.to_bytes(4, "little")
    )


def _stand_in(tmp_path: Path, behaviour: str) -> str:
    """An executable that answers `--version` as espeak-ng does, then hangs, fails or speaks a
    tenth of a second of a tone."""
    script = tmp_path / f"espeak-{behaviour}"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        "if '--version' in sys.argv:\n"
        "    print('eSpeak NG text-to-speech: 9.99  Data at: /nowhere'); sys.exit(0)\n"
        "sys.stdin.read()\n"
        f"behaviour = {behaviour!r}\n"
        "if behaviour == 'hang':\n"
        "    time.sleep(60)\n"
        "if behaviour == 'fail':\n"
        "    sys.stderr.write('Error: The specified espeak-ng voice does not exist.\\n')\n"
        "    sys.exit(1)\n"
        "if behaviour == 'garbage':\n"
        "    sys.stdout.buffer.write(b'not audio'); sys.exit(0)\n"
    )
    script.chmod(0o755)
    return str(script)


async def _speak(provider: EspeakTTSProvider, text: str, *, language: str = "en") -> list[bytes]:
    voice = next(v for v in provider.voices() if v.language == language)
    return [
        frame
        async for frame in provider.synthesize_stream(SynthesisRequest(text=text, voice=voice))
    ]


# --- reading and resampling eSpeak NG's output --------------------------------------------------


def test_the_streamed_header_s_placeholder_sizes_are_ignored() -> None:
    samples = np.array([0, 1000, -1000, 32767, -32768], dtype="<i2")
    assert pcm_from_wav(_header() + samples.tobytes()).tolist() == samples.tolist()
    # A trailing odd byte is not half a sample.
    assert pcm_from_wav(_header() + samples.tobytes() + b"\x01").tolist() == samples.tolist()


@pytest.mark.parametrize(
    ("data", "complaint"),
    [
        (b"not a wav at all", "not a WAV"),
        (_header(rate=16_000), "unexpected format"),
        (_header(channels=2), "unexpected format"),
        (_header(bits=8), "unexpected format"),
        (_header()[:36], "no audio"),
    ],
)
def test_anything_but_espeak_s_own_format_is_refused(data: bytes, complaint: str) -> None:
    with pytest.raises(ValueError, match=complaint):
        pcm_from_wav(data)


def test_resampling_keeps_the_duration_and_the_sound() -> None:
    second = np.arange(ESPEAK_RATE) / ESPEAK_RATE
    tone = (np.sin(2 * np.pi * 440 * second) * 10_000).astype("<i2")

    at_24k = np.frombuffer(resample(tone, 24_000), dtype="<i2")
    assert at_24k.size == 24_000, "one second stays one second"
    spectrum = np.abs(np.fft.rfft(at_24k))
    assert np.argmax(spectrum) == 440, "and a 440 Hz tone stays 440 Hz"

    assert resample(tone, ESPEAK_RATE) == tone.tobytes(), "nothing to do at eSpeak's own rate"
    loud = np.full(ESPEAK_RATE // 10, 32767, dtype="<i2")
    clipped = np.frombuffer(resample(loud, 24_000), dtype="<i2")
    assert clipped.max() == 32767, "the filter's overshoot is clipped, not wrapped around"


# --- the provider -------------------------------------------------------------------------------


def test_a_missing_program_fails_when_the_provider_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At startup (app/main.py builds the voice once), not at a student's first answer."""
    monkeypatch.setattr(espeak.shutil, "which", lambda _name: None)
    with pytest.raises(EspeakNotInstalledError, match="apt install espeak-ng"):
        EspeakTTSProvider()


def test_the_registry_builds_it_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = _stand_in(tmp_path, "speak")
    monkeypatch.setattr(espeak.shutil, "which", lambda _name: stand_in)
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        jwt_secret="x" * 32,
        tts_provider="espeak",
    )
    provider = build_tts(settings)
    assert provider.info.name == "espeak"
    assert provider.info.model == "espeak-ng 9.99", "the exact program, as it reports itself"


def test_a_failed_synthesis_is_a_provider_error_the_session_can_degrade_on(
    tmp_path: Path,
) -> None:
    """The voice session turns a ProviderError into "the rest of this answer is in text"
    (docs/DEGRADATION.md); a crash would end the turn instead."""
    failing = EspeakTTSProvider(binary=_stand_in(tmp_path, "fail"))
    with pytest.raises(ProviderError, match="voice does not exist"):
        asyncio.run(_speak(failing, "Hello."))

    unreadable = EspeakTTSProvider(binary=_stand_in(tmp_path, "garbage"))
    with pytest.raises(ProviderError, match="unreadable"):
        asyncio.run(_speak(unreadable, "Hello."))


def test_a_cancelled_synthesis_leaves_nothing_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Barge-in cancels the answer's task mid-synthesis (ARCHITECTURE §5.2)."""
    provider = EspeakTTSProvider(binary=_stand_in(tmp_path, "hang"))
    started: list[asyncio.subprocess.Process] = []
    create = asyncio.create_subprocess_exec

    async def recording(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await create(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording)

    async def interrupted() -> None:
        task = asyncio.create_task(_speak(provider, "A long answer the student talks over."))
        async with asyncio.timeout(10):
            while not started:  # noqa: ASYNC110 - the process is created inside the provider
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(interrupted())
    [process] = started
    assert process.returncode is not None, "the synthesiser was stopped, not left to finish"


@requires_espeak
def test_each_routed_language_has_a_voice_and_the_exact_program_is_recorded() -> None:
    provider = EspeakTTSProvider()
    program = shutil.which("espeak-ng")
    assert program is not None
    reported = subprocess.run(  # noqa: S603 - the resolved espeak-ng, fixed arguments
        [program, "--version"], capture_output=True, text=True, check=True
    )
    version = reported.stdout.split(":", 1)[1].split()[0]
    assert {(v.language, v.id) for v in provider.voices()} == {
        ("en", "en-us"),
        ("hi", "hi"),
        ("ta", "ta"),
    }
    assert {v.provider_model for v in provider.voices()} == {f"espeak-ng {version}"}
    assert provider.voices()[0].language == "en", "the fallback for a language with no voice"


@requires_espeak
@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Kirchhoff's current law says the currents into a node sum to zero."),
        ("hi", "किरचॉफ का धारा नियम कहता है कि नोड में धाराओं का योग शून्य होता है।"),
        ("ta", "ஒரு முனையில் நுழையும் மின்னோட்டங்களின் கூட்டுத்தொகை பூஜ்ஜியம்."),
    ],
)
def test_a_sentence_is_spoken_in_20_ms_frames_at_the_session_s_rate(
    language: str, text: str
) -> None:
    frames = asyncio.run(_speak(EspeakTTSProvider(), text, language=language))
    assert {len(frame) for frame in frames[:-1]} == {960}, "20 ms of 16-bit audio at 24 kHz"
    audio = np.frombuffer(b"".join(frames), dtype="<i2").astype(np.float64)
    seconds = audio.size / 24_000
    assert 2.0 < seconds < 10.0, "a sentence, said at 160 words a minute"
    loudness = 20 * np.log10(np.sqrt(np.mean(audio**2)) / 32768)
    assert loudness > -35, "speech, not the fake's silence"


@requires_espeak
def test_the_text_is_spoken_never_read_as_an_option(tmp_path: Path) -> None:
    """An answer is model output. One that begins with a dash must not reach espeak-ng's options."""
    target = tmp_path / "written.wav"
    frames = asyncio.run(_speak(EspeakTTSProvider(), f"--version -w {target}"))
    assert sum(len(frame) for frame in frames) > 24_000, "about a second of speech, not a version"
    assert not target.exists()
