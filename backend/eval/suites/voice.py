"""The `voice` suite: the voice front end, in audio time (EVALUATION.md §5.4).

The question: when does the session hear a question begin, when does it decide the question is
over, does it decide that while the student is still mid-sentence, and does it take noise or an
acknowledgement for a question? The session under test is the production `VoiceSession`, with the
Silero VAD and the production turn detector, fed its audio 20 ms at a time as a socket would.

What it does not measure: recognition (the `stt` suite's job) or anything after a turn ends. Two
stand-ins make that possible, and both are named in every report:

* the **recogniser** has perfect words and releases each one as stable `stable_lag_ms` after it
  was spoken — the one property of a streaming recogniser the turn detector depends on;
* the **conversation** ends each turn the moment it begins.

Every time is audio time — 20 ms per frame delivered — so no number depends on the machine or its
load. The dataset (datasets/v1/voice/) is synthetic speech with its timings known by construction.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import uuid
import wave
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from app.providers.base import ProviderInfo
from app.providers.stt.base import (
    AudioFormat,
    FinalTranscript,
    PartialTranscript,
    STTProvider,
    TranscriptEvent,
    TranscriptionContext,
)
from app.providers.tts.fake import FakeTTSProvider
from app.services.conversation import TurnResult
from app.voice.audio import FRAME_BYTES, FRAME_MS, SAMPLE_RATE, AudioFrame, bytes_to_ms
from app.voice.session import VoiceSession, VoiceSessionConfig
from app.voice.vad import SileroVoiceDetector, VadGate, VadSettings, VoiceDetector

if TYPE_CHECKING:
    from app.services.conversation import ConversationService

SPEECH_KINDS = ("single", "hesitation", "multi_sentence")
NOT_QUESTIONS = ("backchannel", "noise")


# --- the dataset ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: float
    end_ms: float


@dataclass(frozen=True)
class VoiceCase:
    id: str
    kind: str
    language: str
    pcm: bytes
    # Where the speech is: one span per spoken part, in order. Empty for noise.
    speech: tuple[tuple[int, int], ...]
    words: tuple[Word, ...]
    pauses_ms: tuple[int, ...]

    @property
    def start_ms(self) -> int:
        return self.speech[0][0]

    @property
    def end_ms(self) -> int:
        return self.speech[-1][1]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path} is not 16 kHz mono 16-bit PCM")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)


def _words(text: str, start_ms: int, end_ms: int) -> list[Word]:
    """Spread a part's words over its span by length: only a part's *end* matters to the turn
    detector (it is where the part's closing punctuation becomes stable), and that is exact."""
    tokens = text.split()
    total = sum(len(t) for t in tokens)
    words, done = [], 0
    for token in tokens:
        begin = start_ms + (end_ms - start_ms) * done / total
        done += len(token)
        words.append(Word(token, begin, start_ms + (end_ms - start_ms) * done / total))
    return words


def compose(record: dict[str, Any], root: Path) -> VoiceCase:
    """Assemble a case's audio from its parts, in integer samples, so the result is identical on
    every machine."""
    ms = SAMPLE_RATE // 1000
    pieces: list[np.ndarray] = [np.zeros(record["lead_ms"] * ms)]
    speech, words = [], []
    cursor = record["lead_ms"]
    for index, part in enumerate(record["parts"]):
        if index:
            pause = record["pauses_ms"][index - 1]
            pieces.append(np.zeros(pause * ms))
            cursor += pause
        audio = _read_wav(root / part["file"])
        pieces.append(audio)
        span = (cursor, cursor + len(audio) // ms)
        speech.append(span)
        words += _words(part["text"], *span)
        cursor = span[1]
    if record["parts"]:
        pieces.append(np.zeros(record["trail_ms"] * ms))
    else:
        pieces.append(np.zeros(record["duration_ms"] * ms))
    signal = np.concatenate(pieces)

    if record["noise"] is not None:
        bed = _read_wav(root / record["noise"]["file"])
        bed = np.tile(bed, len(signal) // len(bed) + 1)[: len(signal)]
        # Beds are stored at -20 dBFS RMS; scale to the case's level.
        signal = signal + bed * 10 ** ((record["noise"]["dbfs"] + 20) / 20)

    pcm = np.clip(np.round(signal), -32768, 32767).astype("<i2").tobytes()
    return VoiceCase(
        id=record["id"],
        kind=record["kind"],
        language=record["language"],
        pcm=pcm,
        speech=tuple(speech),
        words=tuple(words),
        pauses_ms=tuple(record["pauses_ms"]),
    )


def load_cases(root: Path) -> list[VoiceCase]:
    lines = (root / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    return [compose(json.loads(line), root) for line in lines if line.strip()]


def dataset_files(root: Path) -> list[Path]:
    return [
        root / "cases.jsonl",
        *sorted((root / "parts").glob("*.wav")),
        *sorted((root / "noise").glob("*.wav")),
    ]


# --- the stand-ins -------------------------------------------------------------------------


class AudioClock:
    """Seconds of audio delivered so far: the session's clock, and the recogniser's."""

    def __init__(self) -> None:
        self.ms = 0

    def __call__(self) -> float:
        return self.ms / 1000


class TimedRecogniser(STTProvider):
    """Perfect words, each released as stable `lag_ms` after it was spoken.

    It hears only what the session sends it — from the pre-roll on — so an utterance cut in two is
    transcribed in two pieces, as a real recogniser would do.
    """

    def __init__(self, words: Sequence[Word], clock: AudioClock, *, lag_ms: int) -> None:
        self._words = words
        self._clock = clock
        self._lag_ms = lag_ms

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="stt", name="timed", model=f"perfect-words-lag-{self._lag_ms}ms")

    @property
    def audio_format(self) -> AudioFormat:
        return AudioFormat()

    async def transcribe_stream(
        self, frames: AsyncIterator[bytes], context: TranscriptionContext | None = None
    ) -> AsyncIterator[TranscriptEvent]:
        heard_from: float | None = None
        shown = ""
        async for chunk in frames:
            now = self._clock.ms
            if heard_from is None:
                heard_from = now - bytes_to_ms(len(chunk))
            stable = [
                w.text
                for w in self._words
                if w.start_ms >= heard_from and w.end_ms + self._lag_ms <= now
            ]
            text = " ".join(stable)
            if text != shown:
                shown = text
                yield PartialTranscript(text=text, stable_prefix_chars=len(text))
        until = self._clock.ms
        start = heard_from if heard_from is not None else until
        heard = [w.text for w in self._words if start <= w.start_ms < until]
        yield FinalTranscript(text=" ".join(heard), confidence=1.0)


class _EndsAtOnce:
    """The conversation, reduced to ending each turn the moment it begins."""

    async def stream_turn(self, **_: Any) -> AsyncIterator[tuple[str, TurnResult | None]]:
        yield "", TurnResult(turn_index=0)

    async def recover_after_cancel(self) -> None:
        return None


@dataclass
class _Recorder:
    """The session's transport: every control message, stamped with the audio time it was sent."""

    clock: AudioClock
    events: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)

    async def send_control(self, message_type: Any, **payload: Any) -> None:
        self.events.append((self.clock.ms, str(message_type), payload))

    async def send_audio(self, turn_id: int, seq: int, pcm: bytes) -> None:
        return None

    def states(self, name: str) -> list[int]:
        return [t for t, kind, p in self.events if kind == "state" and p["state"] == name]


# --- running a case ------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    case: VoiceCase
    captures_ms: tuple[int, ...]  # when the session began capturing an utterance
    turns_ms: tuple[int, ...]  # when it ended one and began a turn
    end_reasons: tuple[str, ...]

    @property
    def is_question(self) -> bool:
        return self.case.kind in SPEECH_KINDS

    @property
    def cut_offs(self) -> int:
        """Turns begun while the student was still speaking."""
        if not self.is_question:
            return 0
        return sum(self.case.start_ms < t < self.case.end_ms for t in self.turns_ms)

    @property
    def endpoint_ms(self) -> int | None:
        """Speech end → the turn that followed it. None when no turn did (a miss)."""
        if not self.is_question:
            return None
        after = [t - self.case.end_ms for t in self.turns_ms if t >= self.case.end_ms]
        return after[0] if after else None

    @property
    def detect_ms(self) -> int | None:
        """Speech start → the session capturing it."""
        if not self.is_question:
            return None
        after = [t - self.case.start_ms for t in self.captures_ms if t >= self.case.start_ms]
        return after[0] if after else None

    @property
    def false_turns(self) -> int:
        return 0 if self.is_question else len(self.turns_ms)

    @property
    def passed(self) -> bool:
        if self.is_question:
            return self.endpoint_ms is not None and self.cut_offs == 0
        return self.false_turns == 0

    def metrics(self, *, miss_penalty_ms: int) -> dict[str, float]:
        if not self.is_question:
            return {"false_turn": float(self.false_turns > 0)}
        endpoint = self.endpoint_ms
        return {
            # A miss is scored as the longest wait the case could show, so it cannot look fast.
            "endpoint_ms": float(endpoint if endpoint is not None else miss_penalty_ms),
            "cut_off": float(self.cut_offs > 0),
            "missed": float(endpoint is None),
            "detect_ms": float(self.detect_ms if self.detect_ms is not None else miss_penalty_ms),
        }


def session_config(config: dict[str, Any]) -> VoiceSessionConfig:
    session = config.get("session", {})
    return VoiceSessionConfig(
        pre_roll_ms=int(session.get("pre_roll_ms", 500)),
        min_utterance_ms=int(session.get("min_utterance_ms", 400)),
        merge_window_ms=int(session.get("merge_window_ms", 1200)),
        semantic_endpointing=bool(session.get("semantic_endpointing", False)),
        semantic_silence_ms=int(session.get("semantic_silence_ms", 250)),
        ack_grace_ms=0,
    )


def vad_settings(config: dict[str, Any]) -> VadSettings:
    vad = config.get("vad", {})
    return VadSettings(
        enter_threshold=float(vad.get("enter_threshold", 0.5)),
        exit_threshold=float(vad.get("exit_threshold", 0.35)),
        min_speech_ms=int(vad.get("min_speech_ms", 250)),
        min_silence_ms=int(vad.get("min_silence_ms", 500)),
    )


async def run_case(case: VoiceCase, config: dict[str, Any], detector: VoiceDetector) -> CaseResult:
    clock = AudioClock()
    recorder = _Recorder(clock)
    lag_ms = int(config.get("recogniser", {}).get("stable_lag_ms", 300))
    detector.reset()
    session = VoiceSession(
        student_id=uuid.UUID(int=0),
        session_id=uuid.UUID(int=0),
        transport=recorder,
        vad=VadGate(detector, vad_settings(config)),
        stt=TimedRecogniser(case.words, clock, lag_ms=lag_ms),
        tts=FakeTTSProvider(),
        conversation=cast("ConversationService", _EndsAtOnce()),
        config=session_config(config),
        clock=clock,
    )
    reasons: list[str] = []
    await session.start()
    for seq, offset in enumerate(range(0, len(case.pcm) - FRAME_BYTES + 1, FRAME_BYTES)):
        clock.ms = (seq + 1) * FRAME_MS
        await session.handle_audio(
            AudioFrame(
                turn_id=session.machine.turn_id,
                seq=seq,
                pcm=case.pcm[offset : offset + FRAME_BYTES],
            )
        )
        if session.last_end_reason is not None:
            reasons.append(session.last_end_reason)
            session.last_end_reason = None
        # As a socket would: the event loop runs between frames, so the recogniser hears each
        # frame as it arrives and a finished turn winds down before the next one.
        for _ in range(4):
            await asyncio.sleep(0)
    await session.wait_for_turn()
    await session.close()
    return CaseResult(
        case=case,
        captures_ms=tuple(recorder.states("user_speaking")),
        turns_ms=tuple(recorder.states("thinking")),
        end_reasons=tuple(reasons),
    )


async def run(
    cases: Sequence[VoiceCase],
    config: dict[str, Any],
    *,
    detector_factory: Callable[[], VoiceDetector] | None = None,
) -> list[CaseResult]:
    detector = (detector_factory or SileroVoiceDetector)()
    return [await run_case(case, config, detector) for case in cases]


# --- the summary ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    # Nearest rank: always a value that occurred, never an interpolation between two.
    return ordered[max(0, int(np.ceil(q * len(ordered))) - 1)]


def summarise(results: Sequence[CaseResult], *, miss_penalty_ms: int) -> dict[str, Any]:
    questions = [r for r in results if r.is_question]
    others = [r for r in results if not r.is_question]
    endpoints = [float(r.endpoint_ms) for r in questions if r.endpoint_ms is not None]
    detects = [float(r.detect_ms) for r in questions if r.detect_ms is not None]

    def per_kind(kind: str) -> dict[str, Any]:
        rows = [r for r in results if r.case.kind == kind]
        if kind in SPEECH_KINDS:
            ends = [float(r.endpoint_ms) for r in rows if r.endpoint_ms is not None]
            return {
                "cases": len(rows),
                "cut_off_cases": sum(r.cut_offs > 0 for r in rows),
                "missed": sum(r.endpoint_ms is None for r in rows),
                "endpoint_ms_mean": round(statistics.fmean(ends), 1) if ends else None,
            }
        return {"cases": len(rows), "false_turns": sum(r.false_turns for r in rows)}

    return {
        "cases": len(results),
        "questions": len(questions),
        "endpoint_ms_mean": round(statistics.fmean(endpoints), 1) if endpoints else None,
        "endpoint_ms_p50": _percentile(endpoints, 0.5) if endpoints else None,
        "endpoint_ms_p90": _percentile(endpoints, 0.9) if endpoints else None,
        "detect_ms_mean": round(statistics.fmean(detects), 1) if detects else None,
        "detect_ms_p50": _percentile(detects, 0.5) if detects else None,
        "cut_off_rate": round(sum(r.cut_offs > 0 for r in questions) / len(questions), 4)
        if questions
        else None,
        "missed": sum(r.endpoint_ms is None for r in questions),
        "false_turns": sum(r.false_turns for r in others),
        "false_captures": sum(len(r.captures_ms) for r in others),
        "by_kind": {kind: per_kind(kind) for kind in (*SPEECH_KINDS, *NOT_QUESTIONS)},
        "miss_penalty_ms": miss_penalty_ms,
    }


def render(summary: dict[str, Any], config: dict[str, Any]) -> str:
    session = session_config(config)
    lag = int(config.get("recogniser", {}).get("stable_lag_ms", 300))
    lines = [
        f"semantic endpointing  {'on' if session.semantic_endpointing else 'off'}"
        + (f" ({session.semantic_silence_ms} ms)" if session.semantic_endpointing else ""),
        f"recogniser            perfect words, stable {lag} ms after spoken (a stand-in)",
        "conversation          ends each turn at once (a stand-in)",
        "",
        "all times are audio time",
        f"turn end    mean {summary['endpoint_ms_mean']} ms   p50 {summary['endpoint_ms_p50']} ms"
        f"   p90 {summary['endpoint_ms_p90']} ms   (speech end → turn)",
        f"detection   mean {summary['detect_ms_mean']} ms   p50 {summary['detect_ms_p50']} ms"
        "   (speech start → capturing)",
        f"cut off     {summary['cut_off_rate']} of {summary['questions']} questions"
        " (a turn begun mid-question)",
        f"missed      {summary['missed']}",
        f"false turns {summary['false_turns']} from noise and acknowledgements"
        f" ({summary['false_captures']} captures)",
        "",
        "kind              cases  cut off  missed  turn end mean",
    ]
    for kind, row in summary["by_kind"].items():
        if kind in SPEECH_KINDS:
            lines.append(
                f"{kind:16s} {row['cases']:6d} {row['cut_off_cases']:8d} {row['missed']:7d}"
                f"  {row['endpoint_ms_mean']} ms"
            )
        else:
            lines.append(f"{kind:16s} {row['cases']:6d}   false turns {row['false_turns']}")
    return "\n".join(lines)
