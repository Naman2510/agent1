"""Turn-end detection (ARCHITECTURE §4.3).

Fixed silence thresholds are the usual reason a voice agent feels slow, and the usual reason it
cuts people off mid-thought. Two layers:

* **Baseline:** VAD silence of `min_silence_ms`. Deterministic and easy to reason about.
* **Semantic endpointing (experiment EXP-003):** when the stable transcript prefix already reads
  as a complete question, shorten the wait. Off by default — it ships only if the voice suite
  shows a turn-end latency win *without* more premature cutoffs.

The second layer is a hypothesis with a switch, not a feature. That distinction is the whole point
of having an experiment register.
"""

from __future__ import annotations

from dataclasses import dataclass

# Terminal punctuation across the languages in scope. The Devanagari danda is a sentence end;
# Tamil uses the Latin full stop.
TERMINALS = ".?!।॥…"


@dataclass(frozen=True)
class TurnDecision:
    ended: bool
    reason: str
    waited_ms: int


class TurnDetector:
    def __init__(
        self,
        *,
        min_silence_ms: int = 500,
        semantic_endpointing: bool = False,
        semantic_silence_ms: int = 250,
    ) -> None:
        self._min_silence_ms = min_silence_ms
        self._semantic = semantic_endpointing
        self._semantic_silence_ms = semantic_silence_ms
        self._silence_ms = 0

    @property
    def min_silence_ms(self) -> int:
        return self._min_silence_ms

    def reset(self) -> None:
        self._silence_ms = 0

    def on_speech(self) -> None:
        """Speech resumed: the pause was a pause, not the end of a turn."""
        self._silence_ms = 0

    def on_silence(self, window_ms: int, *, stable_prefix: str = "") -> TurnDecision:
        self._silence_ms += window_ms

        if self._semantic and self._looks_complete(stable_prefix):
            if self._silence_ms >= self._semantic_silence_ms:
                return TurnDecision(True, "semantic", self._silence_ms)
            return TurnDecision(False, "waiting_semantic", self._silence_ms)

        if self._silence_ms >= self._min_silence_ms:
            return TurnDecision(True, "silence", self._silence_ms)
        return TurnDecision(False, "waiting_silence", self._silence_ms)

    @staticmethod
    def _looks_complete(stable_prefix: str) -> bool:
        """A deliberately shallow completeness test.

        Terminal punctuation on a prefix of reasonable length. It is shallow because anything
        cleverer is a model, and adding a model to the critical path needs its own justification —
        this exists to be measured against the baseline, not to be clever.
        """
        text = stable_prefix.strip()
        if len(text) < 8:
            return False
        return text[-1] in TERMINALS
