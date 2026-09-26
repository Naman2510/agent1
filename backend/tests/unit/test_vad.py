"""VAD gate logic, and the real Silero detector.

The gate's event semantics are tested with a scripted detector, because turn detection and
barge-in depend on *our* hysteresis rather than on a model's opinion of a fixture. The Silero
tests check that it loads, runs within budget, and rejects silence and noise — and, since Phase 7,
that it hears speech at all, against a synthetic (espeak-ng) sentence. Synthetic speech is not a
substitute for tuning on human voices (DATASET.md); it is enough to prove the detector works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.voice.audio import VAD_WINDOW_BYTES, VAD_WINDOW_SAMPLES
from app.voice.vad import (
    ScriptedVoiceDetector,
    VadEvent,
    VadGate,
    VadSettings,
    speech_timeline,
)

SILERO_PATH = Path("models/silero_vad.onnx")
SPEECH_FIXTURE = (
    Path(__file__).resolve().parents[3] / "datasets/v1/voice/fixtures/espeak-en-kvl-question.wav"
)
WINDOW = b"\x00" * VAD_WINDOW_BYTES


def _gate(probabilities: list[float], **overrides: float | int) -> VadGate:
    settings = VadSettings(**overrides)  # type: ignore[arg-type]
    return VadGate(ScriptedVoiceDetector(probabilities), settings)


def _run(gate: VadGate, count: int) -> list[VadEvent]:
    return [gate.push(WINDOW).event for _ in range(count)]


# --- gate semantics ---------------------------------------------------------


def test_silence_produces_no_events() -> None:
    gate = _gate([0.01] * 20)
    assert set(_run(gate, 20)) == {VadEvent.SILENCE}
    assert gate.in_speech is False


def test_a_short_blip_never_becomes_speech() -> None:
    """The guard that stops a cough from cancelling a good explanation (R-08)."""
    # 250 ms minimum at 32 ms per window needs 8 windows; give it 3.
    gate = _gate([0.9, 0.9, 0.9] + [0.01] * 30, min_speech_ms=250)
    events = _run(gate, 33)
    assert VadEvent.SPEECH_START not in events
    assert VadEvent.SPEECH_END not in events, "no start was emitted, so no end may be either"


def test_sustained_speech_emits_exactly_one_start() -> None:
    gate = _gate(speech_timeline(silence_ms=100, speech_ms=1000, trailing_silence_ms=1000))
    events = _run(gate, 70)
    assert events.count(VadEvent.SPEECH_START) == 1
    assert events.count(VadEvent.SPEECH_END) == 1
    assert events.index(VadEvent.SPEECH_START) < events.index(VadEvent.SPEECH_END)


def test_speech_start_is_delayed_until_the_minimum_duration() -> None:
    gate = _gate([0.9] * 30, min_speech_ms=250)
    events = _run(gate, 10)
    # 250 ms / 32 ms = 7.8 -> the 8th window confirms it.
    assert events[:7] == [VadEvent.SILENCE] * 7
    assert events[7] is VadEvent.SPEECH_START
    assert events[8] is VadEvent.SPEECH_CONTINUE


def test_hysteresis_tolerates_a_dip_below_the_enter_threshold() -> None:
    """A detector hovering near 0.5 must not emit a burst of start/end pairs."""
    gate = _gate([0.9] * 8 + [0.42] * 5 + [0.9] * 8, enter_threshold=0.5, exit_threshold=0.35)
    events = _run(gate, 21)
    assert events.count(VadEvent.SPEECH_START) == 1
    assert VadEvent.SPEECH_END not in events


def test_a_pause_shorter_than_min_silence_does_not_end_speech() -> None:
    gate = _gate([0.9] * 8 + [0.01] * 10 + [0.9] * 5, min_silence_ms=500)
    events = _run(gate, 23)
    assert VadEvent.SPEECH_END not in events
    assert gate.in_speech is True


def test_speech_end_reports_how_long_the_run_was() -> None:
    gate = _gate(speech_timeline(silence_ms=0, speech_ms=640, trailing_silence_ms=640))
    decision = None
    for _ in range(40):
        current = gate.push(WINDOW)
        if current.event is VadEvent.SPEECH_END:
            decision = current
            break
    assert decision is not None
    assert decision.run_ms >= 640


def test_reset_clears_the_run_state() -> None:
    gate = _gate([0.9] * 20)
    _run(gate, 10)
    assert gate.in_speech is True
    gate.reset()
    assert gate.in_speech is False


def test_multiple_utterances_in_one_session() -> None:
    timeline = speech_timeline(
        silence_ms=64, speech_ms=400, trailing_silence_ms=640
    ) + speech_timeline(silence_ms=64, speech_ms=400, trailing_silence_ms=640)
    gate = _gate(timeline)
    events = _run(gate, len(timeline))
    assert events.count(VadEvent.SPEECH_START) == 2
    assert events.count(VadEvent.SPEECH_END) == 2


# --- the real detector ------------------------------------------------------


needs_silero = pytest.mark.skipif(
    not SILERO_PATH.exists(),
    reason="Silero weights absent; run scripts/fetch_models.sh",
)


@needs_silero
def test_silero_loads_and_reports_its_identity() -> None:
    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    assert detector.info.name == "silero"
    assert detector.info.kind == "vad"


@needs_silero
def test_silero_rejects_silence_and_white_noise() -> None:
    """What can be honestly asserted without human speech.

    Rejecting noise is the entire reason for preferring a learned detector over an energy
    threshold, which would call a hostel fan "speech".
    """
    import numpy as np

    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    rng = np.random.default_rng(1234)

    silence = (np.zeros(VAD_WINDOW_SAMPLES, dtype=np.int16)).tobytes()
    for _ in range(30):
        assert detector.probability(silence) < 0.2

    detector.reset()
    for _ in range(30):
        noise = (rng.standard_normal(VAD_WINDOW_SAMPLES) * 600).astype(np.int16).tobytes()
        assert detector.probability(noise) < 0.5, "white noise must not read as speech"


def _fixture_windows() -> list[bytes]:
    """The fixture as the gate sees it: 0.5 s quiet | 2.65 s of speech | 0.8 s quiet, 16 kHz."""
    import wave

    with wave.open(str(SPEECH_FIXTURE), "rb") as fixture:
        assert (fixture.getframerate(), fixture.getnchannels(), fixture.getsampwidth()) == (
            16_000,
            1,
            2,
        )
        pcm = fixture.readframes(fixture.getnframes())
    return [
        pcm[i : i + VAD_WINDOW_BYTES]
        for i in range(0, len(pcm) - VAD_WINDOW_BYTES + 1, VAD_WINDOW_BYTES)
    ]


@needs_silero
def test_silero_hears_a_spoken_sentence() -> None:
    """Silero v5 conditions each window on the 64 samples before it. Fed bare windows — as it was
    until Phase 7 — it scored this sentence at most 0.13, under the 0.5 threshold throughout, so no
    spoken turn could ever begin. Only a test with speech in it could have noticed.
    """
    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    probabilities = [detector.probability(window) for window in _fixture_windows()]

    leading_quiet, speech = probabilities[:12], probabilities[17:-27]
    assert max(leading_quiet) < 0.2
    assert sum(p > 0.5 for p in speech) / len(speech) > 0.6, [round(p, 2) for p in speech]


@needs_silero
def test_a_spoken_sentence_is_one_utterance_through_the_gate() -> None:
    from app.voice.vad import SileroVoiceDetector

    gate = VadGate(SileroVoiceDetector(SILERO_PATH), VadSettings())
    events = [gate.push(window).event for window in _fixture_windows()]
    assert events.count(VadEvent.SPEECH_START) == 1
    assert events.count(VadEvent.SPEECH_END) == 1, "the pauses between words must not split it"


@needs_silero
def test_reset_forgets_the_previous_audio() -> None:
    """The context is stream state like the recurrent state: a new session must not inherit it."""
    import numpy as np

    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    silence = np.zeros(VAD_WINDOW_SAMPLES, dtype=np.int16).tobytes()
    fresh = detector.probability(silence)
    for window in _fixture_windows()[20:40]:
        detector.probability(window)
    detector.reset()
    assert detector.probability(silence) == pytest.approx(fresh, abs=1e-6)


@needs_silero
def test_silero_requires_its_exact_window_size() -> None:
    """Silero v5 is fixed at 512 samples for 16 kHz; padding a short window would shift timings."""
    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    with pytest.raises(ValueError, match="512 samples"):
        detector.probability(b"\x00" * 100)


@needs_silero
def test_silero_stays_well_inside_the_latency_budget() -> None:
    """It runs on every 32 ms of every session, so its cost has to be negligible.

    Measured while writing this: ~3.9 ms per second of audio on the CPU-only target, about 0.4%
    of one core in real time. The assertion is loose so it fails only on a real regression.
    """
    import time

    import numpy as np

    from app.voice.vad import SileroVoiceDetector

    detector = SileroVoiceDetector(SILERO_PATH)
    window = (np.zeros(VAD_WINDOW_SAMPLES, dtype=np.int16)).tobytes()
    windows = 313  # ~10 seconds of audio

    start = time.perf_counter()
    for _ in range(windows):
        detector.probability(window)
    elapsed = time.perf_counter() - start

    per_second_of_audio_ms = elapsed / (windows * 32 / 1000) * 1000
    assert per_second_of_audio_ms < 100, (
        f"{per_second_of_audio_ms:.1f} ms of CPU per second of audio — "
        "the VAD has become a latency contributor"
    )


@needs_silero
def test_a_missing_model_file_fails_loudly() -> None:
    """A silent downgrade to something that cannot tell speech from a fan is the worse failure."""
    from app.voice.vad import SileroVoiceDetector

    with pytest.raises(FileNotFoundError, match="fetch_models"):
        SileroVoiceDetector(Path("models/definitely-not-here.onnx"))
