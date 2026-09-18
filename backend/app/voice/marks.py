"""Per-turn stage marks (ARCHITECTURE §9).

Latency is a contract in this design, so it is measured at named boundaries rather than inferred
from logs. The marks are recorded on a monotonic clock and stored in `messages.latency_ms`, which
is what the voice-latency suite aggregates.

The clock is injected so tests can assert exact durations without sleeping.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

# Stage boundaries, in the order they occur within a turn.
SPEECH_END = "speech_end"
TURN_END = "turn_end"
STT_FINAL = "stt_final"
LANGUAGE_DECIDED = "language_decided"
RETRIEVAL_DONE = "retrieval_done"
LLM_FIRST_TOKEN = "llm_first_token"  # noqa: S105 - a mark name, not a credential
FIRST_SENTENCE = "first_sentence"
TTS_FIRST_BYTE = "tts_first_byte"
FIRST_AUDIO_SENT = "first_audio_sent"
FIRST_AUDIO_PLAYED = "first_audio_played"
PLAYBACK_DRAINED = "playback_drained"
BARGE_IN_DETECTED = "barge_in_detected"
BARGE_IN_SILENCED = "barge_in_silenced"

# (name, from_mark, to_mark) — the durations reported for a turn.
_DERIVED: tuple[tuple[str, str, str], ...] = (
    ("turn_end_ms", SPEECH_END, TURN_END),
    ("stt_final_ms", TURN_END, STT_FINAL),
    ("language_ms", STT_FINAL, LANGUAGE_DECIDED),
    ("retrieval_ms", LANGUAGE_DECIDED, RETRIEVAL_DONE),
    ("llm_ttft_ms", LANGUAGE_DECIDED, LLM_FIRST_TOKEN),
    ("tts_ttfb_ms", FIRST_SENTENCE, TTS_FIRST_BYTE),
    ("transport_ms", FIRST_AUDIO_SENT, FIRST_AUDIO_PLAYED),
    # The number a student actually experiences: silence ends, sound begins.
    ("ttfa_ms", SPEECH_END, FIRST_AUDIO_PLAYED),
    ("turn_total_ms", SPEECH_END, PLAYBACK_DRAINED),
    ("barge_in_stop_ms", BARGE_IN_DETECTED, BARGE_IN_SILENCED),
)


@dataclass
class TurnMarks:
    clock: Callable[[], float] = time.perf_counter
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, name: str) -> None:
        """Record a boundary. The first occurrence wins.

        Deliberate: a turn's `llm_first_token` is the *first* token, and a retry or a second
        content block must not overwrite it and flatter the measurement.
        """
        self.marks.setdefault(name, self.clock())

    def has(self, name: str) -> bool:
        return name in self.marks

    def durations_ms(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for label, start, end in _DERIVED:
            if start in self.marks and end in self.marks:
                delta = self.marks[end] - self.marks[start]
                if delta >= 0:
                    out[label] = round(delta * 1000)
        return out
