"""Voice activity detection (ADR-0004).

Silero v5 via ONNX Runtime is the production detector; a scripted detector drives the state-machine
tests, because a turn-detection or barge-in test should exercise *our* logic on a deterministic
timeline rather than depend on an acoustic model's judgement of a fixture.

Hysteresis, and why: entering speech at p>0.5 and leaving at p<0.35 stops a detector that hovers
near the threshold from emitting a burst of start/end events. `min_speech_ms` is the guard that
keeps a cough from cancelling a good explanation (R-08).
"""

from __future__ import annotations

import abc
import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import structlog

from app.providers.base import ProviderInfo
from app.voice.audio import VAD_WINDOW_SAMPLES

log = structlog.get_logger(__name__)

DEFAULT_MODEL_PATH = Path(os.environ.get("VAANIOS_SILERO_VAD_PATH", "models/silero_vad.onnx"))


class VadEvent(StrEnum):
    SPEECH_START = "speech_start"
    SPEECH_CONTINUE = "speech_continue"
    SPEECH_END = "speech_end"
    SILENCE = "silence"


@dataclass(frozen=True)
class VadDecision:
    event: VadEvent
    probability: float
    # Duration of the run that has just ended, for speech_end; of speech so far, otherwise.
    run_ms: int = 0


@dataclass(frozen=True)
class VadSettings:
    enter_threshold: float = 0.5
    exit_threshold: float = 0.35
    min_speech_ms: int = 250
    min_silence_ms: int = 500
    window_ms: int = 32


class VoiceDetector(abc.ABC):
    """Frame-level speech probability. Stateless across sessions, stateful within one."""

    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @abc.abstractmethod
    def probability(self, window: bytes) -> float:
        """Speech probability for one window of PCM."""

    def reset(self) -> None:  # pragma: no cover - overridden where state exists
        return None


class VadGate:
    """Turns a probability stream into speech_start / speech_end with hysteresis.

    Separate from the detector so the thresholds, the minimum-duration guards and the event logic
    are testable without any model at all — and so swapping the detector cannot change the event
    semantics the state machine depends on.
    """

    def __init__(self, detector: VoiceDetector, settings: VadSettings | None = None) -> None:
        self._detector = detector
        self._settings = settings or VadSettings()
        self._in_speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._announced = False

    @property
    def settings(self) -> VadSettings:
        return self._settings

    @property
    def in_speech(self) -> bool:
        """True only once speech has been *confirmed* (min_speech_ms satisfied)."""
        return self._in_speech and self._announced

    def reset(self) -> None:
        self._detector.reset()
        self._in_speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._announced = False

    def push(self, window: bytes) -> VadDecision:
        probability = self._detector.probability(window)
        window_ms = self._settings.window_ms

        if not self._in_speech:
            if probability >= self._settings.enter_threshold:
                self._in_speech = True
                self._speech_ms = window_ms
                self._silence_ms = 0
                # Not announced yet: a 32 ms blip is not a turn.
                return VadDecision(VadEvent.SILENCE, probability, self._speech_ms)
            return VadDecision(VadEvent.SILENCE, probability)

        # Inside a speech run.
        if probability >= self._settings.exit_threshold:
            self._speech_ms += window_ms
            self._silence_ms = 0
            if not self._announced and self._speech_ms >= self._settings.min_speech_ms:
                self._announced = True
                return VadDecision(VadEvent.SPEECH_START, probability, self._speech_ms)
            event = VadEvent.SPEECH_CONTINUE if self._announced else VadEvent.SILENCE
            return VadDecision(event, probability, self._speech_ms)

        self._silence_ms += window_ms
        if self._silence_ms < self._settings.min_silence_ms:
            # A pause inside speech, not the end of it.
            event = VadEvent.SPEECH_CONTINUE if self._announced else VadEvent.SILENCE
            return VadDecision(event, probability, self._speech_ms)

        spoken = self._speech_ms
        announced = self._announced
        self._in_speech = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._announced = False
        if not announced:
            # The run never qualified as speech: no start was emitted, so emit no end.
            return VadDecision(VadEvent.SILENCE, probability, spoken)
        return VadDecision(VadEvent.SPEECH_END, probability, spoken)


# The trailing samples of the previous window that Silero v5 prepends to each one, at 16 kHz.
SILERO_CONTEXT_SAMPLES = 64


class SileroVoiceDetector(VoiceDetector):
    """Silero VAD v5 through ONNX Runtime.

    Measured on this project's CPU-only target: ~3.9 ms per second of audio, i.e. about 0.4% of
    one core in real time — small enough to be irrelevant to the latency budget, which is the
    reason a learned detector is affordable here at all.

    Thresholds are the library defaults and are **not tuned against real speech**, because no
    human-speech fixture exists in the environment where this was written. Tuning them is an
    explicit task for the first real dataset (DATASET.md).
    """

    def __init__(self, model_path: Path | str = DEFAULT_MODEL_PATH) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Silero VAD weights not found at {path}. Run scripts/fetch_models.sh, or set "
                "VAANIOS_SILERO_VAD_PATH."
            )
        options = ort.SessionOptions()
        # One thread: the model is tiny and thread pools would contend with the event loop.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._sample_rate = np.array(16_000, dtype=np.int64)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(SILERO_CONTEXT_SAMPLES, dtype=np.float32)

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="vad", name="silero", model="silero_vad_v5.onnx")

    def reset(self) -> None:
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros(SILERO_CONTEXT_SAMPLES, dtype=self._np.float32)

    def probability(self, window: bytes) -> float:
        np = self._np
        samples = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) != VAD_WINDOW_SAMPLES:
            raise ValueError(
                f"Silero v5 requires exactly {VAD_WINDOW_SAMPLES} samples at 16 kHz, "
                f"got {len(samples)}"
            )
        # v5 scores each window together with the 64 samples before it. Given the bare window it
        # stays near zero even for clear speech (at most 0.13 across a whole spoken sentence, so
        # nothing ever crossed the threshold); tests/unit/test_vad.py pins this with a fixture.
        model_input = np.concatenate([self._context, samples]).reshape(1, -1)
        output, self._state = self._session.run(
            None,
            {"input": model_input, "state": self._state, "sr": self._sample_rate},
        )
        self._context = samples[-SILERO_CONTEXT_SAMPLES:]
        return float(output[0][0])


class ScriptedVoiceDetector(VoiceDetector):
    """Replays a fixed probability timeline.

    Used by every state-machine, turn-detection and barge-in test. A deterministic timeline tests
    our logic; an acoustic model tested through our logic tests neither well.
    """

    def __init__(self, probabilities: Sequence[float], *, default: float = 0.0) -> None:
        self._probabilities = list(probabilities)
        self._default = default
        self._index = 0
        self.calls = 0

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="vad", name="scripted", model="scripted")

    def reset(self) -> None:
        self._index = 0

    def probability(self, window: bytes) -> float:
        self.calls += 1
        if self._index < len(self._probabilities):
            value = self._probabilities[self._index]
            self._index += 1
            return value
        return self._default


def speech_timeline(
    *, silence_ms: int, speech_ms: int, trailing_silence_ms: int, window_ms: int = 32
) -> list[float]:
    """Build a probability timeline: silence, then speech, then silence.

    Keeps tests readable in milliseconds rather than in counts of 32 ms windows.
    """

    def windows(duration_ms: int) -> int:
        return max(0, duration_ms // window_ms)

    return (
        [0.01] * windows(silence_ms)
        + [0.95] * windows(speech_ms)
        + [0.01] * windows(trailing_silence_ms)
    )
