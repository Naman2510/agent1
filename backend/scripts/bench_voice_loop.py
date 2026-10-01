"""Time a voice turn with real, local speech in and out (EVALUATION.md §5, full-stack latency).

The production `VoiceSession`, with the Silero VAD and the production turn detector, hears each of
the voice dataset's one-question cases in real time: 20 ms a frame, on the wall clock, as a
microphone would deliver it. faster-whisper, the local recogniser (ADR-0002), transcribes what it
heard. A scripted model answers at once, two sentences in the routed language. eSpeak NG, the local
voice (ADR-0018), speaks the answer, and a client that plays audio the moment it arrives
acknowledges it. The session's own stage marks give each turn's latencies.

**What it measures:** our pipeline with two real, local providers on this machine. That is the
turn detector's wait, the recogniser's time to a final transcript, the synthesiser's time to its
first audio byte, and time to first audio.

**What it does not:**
- A model's time to its first token. The scripted model answers at once, so a real model's TTFT
  adds to every TTFA here.
- Any network round trip, or a managed recogniser or voice.
- Playback: the client "plays" each frame on arrival, so a turn's total is not measured.
- Real speech: the questions are eSpeak's synthetic speech.
No number here is a claim about what a student would wait for with the providers ADR-0002 and
ADR-0003 plan.

    python scripts/bench_voice_loop.py [--model small] [--json out.json]

Needs the voice-local extra, faster-whisper's weights (downloaded on first use), espeak-ng, and the
Silero weights (scripts/fetch_models.sh). CI tier T2 runs it, where all four are available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from app.providers.tts.base import SynthesisRequest
from app.services.conversation import TurnResult
from app.voice.audio import FRAME_BYTES, FRAME_MS, AudioFrame, bytes_to_ms
from app.voice.session import VoiceSession, VoiceSessionConfig
from app.voice.vad import SileroVoiceDetector, VadGate, VadSettings
from eval.recording import DATASETS
from eval.suites import voice as voice_suite

if TYPE_CHECKING:
    from app.providers.stt.base import STTProvider
    from app.providers.tts.base import TTSProvider
    from app.services.conversation import ConversationService

SILERO = Path("models/silero_vad.onnx")
KINDS = ("single", "multi_sentence")
REPLIES = {
    "en": "Kirchhoff's voltage law says the voltages around any closed loop add up to zero. "
    "It follows from conservation of energy.",
    "hi": "किरचॉफ का वोल्टेज नियम कहता है कि किसी भी बंद लूप में वोल्टेज का योग शून्य होता है। "
    "यह ऊर्जा संरक्षण से आता है।",
    "hi-Latn": "Kirchhoff ka voltage law kehta hai ki kisi bhi closed loop mein voltages ka sum "
    "zero hota hai. Yeh energy conservation se aata hai.",
}
# The stages EVALUATION.md §5 reports, as the session names them (app/voice/marks.py).
STAGES = ("turn_end_ms", "stt_final_ms", "tts_ttfb_ms", "ttfa_ms")


class _ScriptedModel:
    """The model, answering at once and a word at a time, in the language the session routed, as
    a real model is told to (code-switched questions get the romanized reply)."""

    async def stream_turn(
        self, *, language: str | None = None, **_: Any
    ) -> AsyncIterator[tuple[str, TurnResult | None]]:
        reply = REPLIES.get("hi-Latn" if language == "mixed" else language or "en", REPLIES["en"])
        for word in reply.split(" "):
            yield word + " ", None
        yield "", TurnResult(text=reply, turn_index=0)

    async def recover_after_cancel(self) -> None:
        return None


@dataclass
class _PlayingClient:
    """The client: plays every frame the moment it arrives, and says so."""

    session: VoiceSession | None = None
    latencies: dict[int, dict[str, int]] = field(default_factory=dict)
    heard: dict[int, str] = field(default_factory=dict)
    received: dict[int, int] = field(default_factory=dict)

    async def send_control(self, message_type: Any, **payload: Any) -> None:
        if str(message_type) == "metrics":
            self.latencies[payload["turn_id"]] = dict(payload["latency_ms"])
        elif str(message_type) == "stt.final":
            self.heard[payload["turn_id"]] = str(payload["text"])

    async def send_audio(self, turn_id: int, seq: int, pcm: bytes) -> None:
        self.received[turn_id] = self.received.get(turn_id, 0) + len(pcm)
        assert self.session is not None
        played = bytes_to_ms(self.received[turn_id], self.session.config.tts_sample_rate)
        await self.session.handle_playback_ack(turn_id=turn_id, played_ms=played)


async def run_case(
    case: voice_suite.VoiceCase, *, stt: STTProvider, tts: TTSProvider
) -> _PlayingClient:
    client = _PlayingClient()
    detector = SileroVoiceDetector(SILERO)
    session = VoiceSession(
        student_id=uuid.UUID(int=0),
        session_id=uuid.UUID(int=0),
        transport=client,
        vad=VadGate(detector, VadSettings()),
        stt=stt,
        tts=tts,
        conversation=cast("ConversationService", _ScriptedModel()),
        config=VoiceSessionConfig(),
    )
    client.session = session
    await session.start()
    loop = asyncio.get_running_loop()
    started = loop.time()
    for seq, offset in enumerate(range(0, len(case.pcm) - FRAME_BYTES + 1, FRAME_BYTES)):
        # Each frame is delivered when it would have finished arriving from a microphone.
        delay = started + (seq + 1) * FRAME_MS / 1000 - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        frame = case.pcm[offset : offset + FRAME_BYTES]
        await session.handle_audio(AudioFrame(turn_id=session.machine.turn_id, seq=seq, pcm=frame))
    await session.wait_for_turn()
    await session.close()
    return client


def percentiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    # Nearest rank: a value that occurred, never an interpolation between two.
    p95 = ordered[max(0, int(np.ceil(0.95 * len(ordered))) - 1)]
    return {"n": len(ordered), "p50": statistics.median(ordered), "p95": p95, "max": ordered[-1]}


async def measure(model: str) -> dict[str, Any]:
    from app.providers.stt.faster_whisper import FasterWhisperSTT
    from app.providers.tts.espeak import EspeakTTSProvider
    from eval.suites.stt import machine

    stt = FasterWhisperSTT(model)
    tts = EspeakTTSProvider()
    # Warm both once, so the first case does not carry a cold start nobody would see twice.
    await asyncio.to_thread(stt.transcribe, np.zeros(16_000, dtype=np.float32))
    async for _ in tts.synthesize_stream(SynthesisRequest(text="Ready.", voice=tts.voices()[0])):
        pass

    cases = [
        case for case in voice_suite.load_cases(DATASETS / "v1" / "voice") if case.kind in KINDS
    ]
    turns: list[dict[str, Any]] = []
    for case in cases:
        client = await run_case(case, stt=stt, tts=tts)
        for turn_id, latency in sorted(client.latencies.items()):
            heard = client.heard.get(turn_id, "")
            turns.append({"case": case.id, "language": case.language, "heard": heard, **latency})
    return {
        "machine": machine(),
        "python": platform.python_version(),
        "recogniser": f"faster-whisper {model} (int8)",
        "voice": tts.info.model,
        "cases": len(cases),
        "turns": turns,
        "stages": {
            stage: percentiles([float(t[stage]) for t in turns if stage in t]) for stage in STAGES
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", default="small", help="faster-whisper model size")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args()
    if not SILERO.exists():
        raise SystemExit("needs the Silero weights: bash scripts/fetch_models.sh")

    result = asyncio.run(measure(args.model))
    print("Voice loop latency, local recogniser and voice, scripted model (no TTFT)")
    print("=" * 72)
    print(f"machine     {result['machine']}")
    print(f"recogniser  {result['recogniser']}")
    print(f"voice       {result['voice']}")
    print(f"cases       {result['cases']} ({', '.join(KINDS)}), turns {len(result['turns'])}")
    print()
    print(f"{'stage':16s} {'n':>4s} {'p50 ms':>8s} {'p95 ms':>8s} {'max ms':>8s}")
    for stage, row in result["stages"].items():
        print(f"{stage:16s} {row['n']:4d} {row['p50']:8.0f} {row['p95']:8.0f} {row['max']:8.0f}")
    print()
    print("Not measured here: a model's TTFT (add it to TTFA), any network, playback.")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
