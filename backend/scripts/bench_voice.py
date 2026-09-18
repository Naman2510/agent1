"""Measure the voice pipeline's own overhead.

**What this measures and what it does not.** Every model provider here is a deterministic fake,
so these numbers are the cost of *our* code — VAD inference, framing, turn detection, chunking,
the state machine, the playback ledger, persistence — and nothing else. They are not TTFA. Real
TTFA is dominated by three things this script deliberately excludes: the ASR round trip, the LLM
time-to-first-token, and TTS time-to-first-byte (ARCHITECTURE §9 stages 3, 6 and 7).

That makes it useful for exactly one question: is our own pipeline a meaningful contributor to
latency, or is it noise next to the network? Answering that before the providers are chosen is
the point.

    python scripts/bench_voice.py [--turns 20]
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from pathlib import Path
from typing import Any

from app.voice.audio import FRAME_BYTES, VAD_WINDOW_BYTES, AudioFrame
from app.voice.chunker import SentenceChunker
from app.voice.playback import PlaybackLedger
from app.voice.protocol import decode_audio, encode_audio
from app.voice.state import Trigger, TurnStateMachine
from app.voice.vad import (
    ScriptedVoiceDetector,
    SileroVoiceDetector,
    VadGate,
    VadSettings,
    speech_timeline,
)

SILERO = Path("models/silero_vad.onnx")
ANSWER = (
    "Kirchhoff ka voltage law kehta hai ki kisi bhi closed loop mein saare potential "
    "differences ka sum zero hota hai. Yeh energy conservation se aata hai. Samajh aaya?"
)


def _percentiles(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50_ms": statistics.median(ordered) * 1000,
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000,
        "max_ms": ordered[-1] * 1000,
    }


def bench_vad_inference(iterations: int = 400) -> dict[str, Any] | None:
    """Silero cost per 32 ms window — it runs on every window of every session."""
    if not SILERO.exists():
        return None
    detector = SileroVoiceDetector(SILERO)
    window = b"\x00" * VAD_WINDOW_BYTES
    detector.probability(window)  # warm up the session

    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        detector.probability(window)
        samples.append(time.perf_counter() - start)

    stats = _percentiles(samples)
    # The number that actually matters: share of real time consumed.
    stats["realtime_fraction_pct"] = stats["p50_ms"] / 32.0 * 100
    return stats


def bench_frame_path(iterations: int = 2000) -> dict[str, Any]:
    """Encode + decode one 20 ms audio frame."""
    frame = AudioFrame(turn_id=3, seq=1, pcm=b"\x11" * FRAME_BYTES)
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        decode_audio(encode_audio(frame))
        samples.append(time.perf_counter() - start)
    return _percentiles(samples)


def bench_chunker(iterations: int = 500) -> dict[str, Any]:
    """Chunking a full answer, fed in token-sized deltas."""
    samples = []
    for _ in range(iterations):
        chunker = SentenceChunker()
        start = time.perf_counter()
        for i in range(0, len(ANSWER), 6):
            chunker.push(ANSWER[i : i + 6])
        chunker.flush()
        samples.append(time.perf_counter() - start)
    return _percentiles(samples)


def bench_ledger(iterations: int = 2000) -> dict[str, Any]:
    """Resolving a playback position into the text actually heard — the barge-in hot path."""
    ledger = PlaybackLedger()
    for part in ANSWER.split(". "):
        ledger.add_chunk(part + ". ", 48_000)
    position = ledger.total_audio_ms // 2

    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        ledger.spoken_prefix(position)
        samples.append(time.perf_counter() - start)
    return _percentiles(samples)


def bench_state_machine(iterations: int = 5000) -> dict[str, Any]:
    """A full turn's transitions."""
    samples = []
    for _ in range(iterations):
        machine = TurnStateMachine()
        start = time.perf_counter()
        for trigger in (
            Trigger.SESSION_START,
            Trigger.SPEECH_START,
            Trigger.TURN_END,
            Trigger.FIRST_AUDIO_QUEUED,
            Trigger.PLAYBACK_DRAINED,
        ):
            machine.fire(trigger)
        samples.append(time.perf_counter() - start)
    return _percentiles(samples)


async def bench_turn_detection(iterations: int = 200) -> dict[str, Any]:
    """Speech end to the turn-end decision, with the scripted VAD.

    This is stage 2 of the latency budget minus the configured silence wait, i.e. the *compute*
    cost of deciding a turn ended. The wait itself is a UX choice, not a cost.
    """
    timeline = speech_timeline(silence_ms=64, speech_ms=600, trailing_silence_ms=640)
    samples = []
    for _ in range(iterations):
        gate = VadGate(ScriptedVoiceDetector(timeline), VadSettings())
        window = b"\x00" * VAD_WINDOW_BYTES
        start = time.perf_counter()
        for _ in range(len(timeline)):
            gate.push(window)
        samples.append(time.perf_counter() - start)
    return _percentiles(samples)


def print_block(title: str, stats: dict[str, Any] | None, note: str = "") -> None:
    print(f"\n{title}")
    if stats is None:
        print("  skipped (weights absent — run scripts/fetch_models.sh)")
        return
    for key, value in stats.items():
        if key == "n":
            print(f"  samples            {int(value)}")
        elif key.endswith("_pct"):
            print(f"  {key:18s} {value:.3f}")
        else:
            print(f"  {key:18s} {value:.4f}")
    if note:
        print(f"  note: {note}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=20)
    parser.parse_args()

    print("VaaniOS voice pipeline overhead")
    print("=" * 62)
    print("All model providers are deterministic fakes. These are OUR costs only:")
    print("they exclude the ASR round trip, LLM time-to-first-token and TTS")
    print("time-to-first-byte, which dominate real TTFA. NOT a TTFA measurement.")

    print_block(
        "Silero VAD — one 32 ms window",
        bench_vad_inference(),
        "runs on every window of every session; realtime_fraction_pct is the share of one core",
    )
    print_block("Audio frame encode + decode (20 ms frame)", bench_frame_path())
    print_block("Sentence chunking — a full answer in 6-char deltas", bench_chunker())
    print_block("Playback ledger — resolve spoken prefix", bench_ledger())
    print_block("Turn state machine — five transitions", bench_state_machine())
    print_block(
        "VAD gate — 1.3 s of audio through hysteresis",
        await bench_turn_detection(),
        "compute only; the configured silence wait is a UX choice, not a cost",
    )

    print(
        "\nInterpretation: if these are all far below the stage budgets in ARCHITECTURE §9,"
        "\nour pipeline is not the latency problem — the providers are. Record the numbers"
        "\nwith the git SHA before drawing that conclusion."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
