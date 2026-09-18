"""Audio framing and the pre-roll buffer (ARCHITECTURE §5.5).

The pre-roll is the non-obvious part. Barge-in only fires after ~250 ms of sustained speech, and
upstream audio is VAD-gated, so a naive pipeline hands the recogniser an utterance that starts a
quarter of a second late: "Wait, stop" arrives as "stop", and the mentor answers a different
question. A rolling buffer of *all* recent frames is flushed ahead of the live ones once speech is
confirmed, so the recogniser sees the onset.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

SAMPLE_RATE = 16_000
SAMPLE_WIDTH_BYTES = 2
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH_BYTES  # 640

# Silero v5 requires exactly 512 samples per call at 16 kHz (32 ms).
VAD_WINDOW_SAMPLES = 512
VAD_WINDOW_BYTES = VAD_WINDOW_SAMPLES * SAMPLE_WIDTH_BYTES


class FrameSizeError(ValueError):
    """A frame that is not the agreed size. Rejected rather than padded: silently reframing
    mismatched audio produces clicks and shifts every timing measurement."""


@dataclass(frozen=True)
class AudioFrame:
    turn_id: int
    seq: int
    pcm: bytes

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) * 1000 // (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)


def bytes_to_ms(size: int) -> int:
    return size * 1000 // (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)


def ms_to_bytes(milliseconds: int) -> int:
    return milliseconds * SAMPLE_RATE * SAMPLE_WIDTH_BYTES // 1000


class PreRollBuffer:
    """A fixed-duration ring of the most recent audio.

    Holds whole frames rather than a byte window so a flush never starts mid-sample.
    """

    def __init__(self, milliseconds: int = 500) -> None:
        self._capacity = max(1, milliseconds // FRAME_MS)
        self._frames: deque[bytes] = deque(maxlen=self._capacity)

    @property
    def capacity_ms(self) -> int:
        return self._capacity * FRAME_MS

    def push(self, pcm: bytes) -> None:
        self._frames.append(pcm)

    def drain(self) -> bytes:
        """Return the buffered audio and clear it.

        Cleared on drain so the same pre-roll cannot be prepended to two utterances, which would
        duplicate the onset and confuse the recogniser.
        """
        data = b"".join(self._frames)
        self._frames.clear()
        return data

    def clear(self) -> None:
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)


class WindowAssembler:
    """Re-blocks a 20 ms frame stream into the fixed window size the VAD requires.

    The client's framing (20 ms, chosen for transport) and Silero's (32 ms, fixed by the model)
    do not divide evenly, so something has to hold the remainder. Doing it here keeps that detail
    out of the VAD and out of the session loop.
    """

    def __init__(self, window_bytes: int = VAD_WINDOW_BYTES) -> None:
        self._window_bytes = window_bytes
        self._pending = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        self._pending.extend(pcm)
        windows: list[bytes] = []
        while len(self._pending) >= self._window_bytes:
            windows.append(bytes(self._pending[: self._window_bytes]))
            del self._pending[: self._window_bytes]
        return windows

    def reset(self) -> None:
        self._pending.clear()

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)
