"""The playback ledger (ARCHITECTURE §5.3).

This is the mechanism behind the barge-in invariant: *what gets stored is what the student
actually heard.*

The model generates further ahead than the speaker plays. When a student interrupts, three
quantities are all different — the text generated, the audio sent, and the audio played. Only the
third is what they heard, and only the third may go into conversation history. Storing the first
means the mentor later refers to explanations that were never spoken, which presents to the
student as the AI being confusing rather than as an error (Gate 0 finding C-03).

The ledger maps each synthesised chunk to its text span and its audio duration, so a cumulative
`played_ms` from the client resolves to a character count in the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.voice.audio import bytes_to_ms


@dataclass
class LedgerEntry:
    index: int
    text: str
    # Character offset of this chunk's text within the full answer.
    char_start: int
    char_end: int
    audio_bytes: int
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class PlaybackLedger:
    """Chunk-to-audio accounting for one turn."""

    entries: list[LedgerEntry] = field(default_factory=list)
    _text_length: int = 0
    _audio_ms: int = 0
    played_ms: int = 0

    @property
    def total_audio_ms(self) -> int:
        return self._audio_ms

    @property
    def text(self) -> str:
        return "".join(entry.text for entry in self.entries)

    def begin_chunk(self, text: str) -> LedgerEntry:
        """Record a chunk's text *before* its audio exists.

        Registered up front rather than on completion, because a chunk that is still being
        synthesised when the student interrupts would otherwise have its text recorded nowhere —
        neither as heard nor as unheard. That is the same defect class as storing the full
        generation: the record stops matching reality.
        """
        entry = LedgerEntry(
            index=len(self.entries),
            text=text,
            char_start=self._text_length,
            char_end=self._text_length + len(text),
            audio_bytes=0,
            start_ms=self._audio_ms,
            end_ms=self._audio_ms,
        )
        self.entries.append(entry)
        self._text_length = entry.char_end
        return entry

    def extend_chunk(self, audio_bytes: int) -> None:
        """Grow the open chunk as its audio arrives."""
        if not self.entries or audio_bytes <= 0:
            return
        entry = self.entries[-1]
        entry.audio_bytes += audio_bytes
        entry.end_ms = entry.start_ms + bytes_to_ms(entry.audio_bytes)
        self._audio_ms = entry.end_ms

    def add_chunk(self, text: str, audio_bytes: int) -> LedgerEntry:
        """Register a chunk and its finished audio in one step.

        Convenience for callers that synthesise a chunk atomically; the streaming path uses
        `begin_chunk` plus `extend_chunk` so a cancelled chunk is still accounted for.
        """
        entry = self.begin_chunk(text)
        self.extend_chunk(audio_bytes)
        return entry

    def acknowledge(self, played_ms: int) -> None:
        """Record the client's cumulative playback position.

        Monotonic by construction: an ACK that goes backwards is a reordered message, and taking
        the maximum is safer than trusting arrival order.
        """
        self.played_ms = max(self.played_ms, min(played_ms, self._audio_ms))

    def spoken_prefix(self, played_ms: int | None = None) -> str:
        """The text the student actually heard, given a playback position.

        Within a partially played chunk the boundary is interpolated by proportion of duration.
        That is an approximation — audio is not uniformly paced across characters — and it is the
        best available without per-word timings from the synthesiser. It is deliberately
        *conservative*: it rounds down, so history never claims more was heard than was.
        """
        position = self.played_ms if played_ms is None else min(played_ms, self._audio_ms)
        if position <= 0 or not self.entries:
            return ""

        spoken: list[str] = []
        for entry in self.entries:
            if position >= entry.end_ms:
                spoken.append(entry.text)
                continue
            if position <= entry.start_ms:
                break
            if entry.duration_ms <= 0:  # pragma: no cover - a chunk with no audio
                break
            fraction = (position - entry.start_ms) / entry.duration_ms
            # Round down: never over-claim.
            characters = int(len(entry.text) * fraction)
            spoken.append(entry.text[:characters])
            break
        return "".join(spoken)

    def unspoken_remainder(self, played_ms: int | None = None) -> str:
        """The generated tail the student never heard.

        Kept for debugging and failure analysis only. It is never replayed into model context —
        that is the whole point of the split.
        """
        spoken = self.spoken_prefix(played_ms)
        return self.text[len(spoken) :]

    def fully_played(self) -> bool:
        return self._audio_ms > 0 and self.played_ms >= self._audio_ms
