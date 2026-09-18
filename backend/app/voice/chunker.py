"""Sentence chunking for streaming synthesis (ARCHITECTURE §6).

Buffering a whole response before synthesis adds its entire generation time to time-to-first-audio,
so text is emitted in speakable pieces as it arrives. The rules below exist because each one is
audible when it goes wrong:

* Splitting inside "3.5 kΩ" makes the mentor say "three point" … "five kilohms".
* Splitting after "Dr." or "e.g." produces a wrong pause and a wrong intonation.
* The Devanagari danda (।) and the ellipsis are sentence ends; a chunker that only knows ".?!"
  will read a whole Hindi paragraph as one breath.
* The **first** chunk is deliberately short, because it alone determines TTFA. Later chunks are
  longer, because prosody improves with context. That trade is EXP-005, not a constant to tune by
  taste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TERMINALS = ".?!।॥…"
CLAUSE_BREAKS = ",;:—"

# Abbreviations whose full stop is not a sentence end.
_ABBREVIATIONS = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "jr",
        "st",
        "e.g",
        "i.e",
        "etc",
        "vs",
        "approx",
        "fig",
        "eq",
        "no",
        "vol",
        "ch",
        "sec",
        "min",
        "max",
        "avg",
    }
)

# A full stop between digits ("3.5"), or before a unit, is not a sentence end.
_DECIMAL = re.compile(r"\d[.,]$")
_TRAILING_INITIAL = re.compile(r"(?:^|\s)[A-Z]\.$")


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    reason: str  # terminal | clause | max_wait | flush


class SentenceChunker:
    """Accumulates text deltas and emits speakable chunks.

    Not a general sentence splitter: it is tuned for *speech*, which is why a clause boundary is
    an acceptable break and why the first chunk is allowed to be very short.
    """

    def __init__(
        self,
        *,
        first_chunk_max_words: int = 12,
        min_chunk_chars: int = 24,
        max_chunk_chars: int = 240,
    ) -> None:
        self._first_chunk_max_words = first_chunk_max_words
        self._min_chunk_chars = min_chunk_chars
        self._max_chunk_chars = max_chunk_chars
        self._buffer = ""
        self._emitted = 0

    @property
    def pending(self) -> str:
        return self._buffer

    @property
    def emitted(self) -> int:
        return self._emitted

    def push(self, text: str) -> list[Chunk]:
        """Add a delta and return whatever is now speakable."""
        self._buffer += text
        chunks: list[Chunk] = []
        while True:
            chunk = self._try_emit()
            if chunk is None:
                break
            chunks.append(chunk)
        return chunks

    def flush(self, reason: str = "flush") -> Chunk | None:
        """Emit whatever remains. Called when generation ends."""
        text = self._buffer.strip()
        if not text:
            return None
        self._buffer = ""
        chunk = Chunk(text=text, index=self._emitted, reason=reason)
        self._emitted += 1
        return chunk

    def reset(self) -> None:
        self._buffer = ""
        self._emitted = 0

    # --- internals ---------------------------------------------------------

    def _try_emit(self) -> Chunk | None:
        cut = self._find_cut()
        if cut is None:
            return None
        text, reason = cut
        self._buffer = self._buffer[len(text) :].lstrip()
        chunk = Chunk(text=text.strip(), index=self._emitted, reason=reason)
        self._emitted += 1
        return chunk

    def _find_cut(self) -> tuple[str, str] | None:
        buffer = self._buffer
        if not buffer.strip():
            return None

        is_first = self._emitted == 0
        minimum = 1 if is_first else self._min_chunk_chars

        for index, char in enumerate(buffer):
            if char not in TERMINALS:
                continue
            candidate = buffer[: index + 1]
            if len(candidate.strip()) < minimum:
                continue
            if self._is_false_terminal(candidate, buffer, index):
                continue
            return candidate, "terminal"

        # The first chunk may break at a clause boundary so audio starts sooner.
        if is_first:
            words = buffer.split()
            if len(words) >= self._first_chunk_max_words:
                for index, char in enumerate(buffer):
                    if char in CLAUSE_BREAKS and len(buffer[:index].split()) >= 4:
                        return buffer[: index + 1], "clause"
            # Nothing to break on yet, and no terminal: wait for more text.

        if len(buffer) >= self._max_chunk_chars:
            # A long clause must not stall audio indefinitely. Break at the last space so the
            # cut never lands inside a word.
            window = buffer[: self._max_chunk_chars]
            space = window.rfind(" ")
            cut_at = space if space > self._min_chunk_chars else self._max_chunk_chars
            return buffer[:cut_at], "max_wait"

        return None

    @staticmethod
    def _is_false_terminal(candidate: str, buffer: str, index: int) -> bool:
        char = buffer[index]
        if char != ".":
            return False

        # "3.5" / "1,000" — a decimal separator, not a sentence end.
        if _DECIMAL.search(candidate) and index + 1 < len(buffer) and buffer[index + 1].isdigit():
            return True

        # A known abbreviation: look at the token before the stop.
        tail = candidate[:-1].split()
        if tail:
            token = tail[-1].lower().strip("([{\"'")
            if token in _ABBREVIATIONS:
                return True
            # "e.g." arrives as "e.g" plus a stop only after the second dot; also treat a single
            # capital initial ("J. C. Maxwell") as non-terminal.
            if _TRAILING_INITIAL.search(candidate):
                return True

        # A stop immediately followed by a unit or a lowercase letter is mid-sentence.
        if index + 1 < len(buffer):
            nxt = buffer[index + 1]
            if nxt.islower():
                return True
        return False
