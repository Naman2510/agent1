"""Load: many students talking to one server at once (Phase 9).

Starts the real application in a process of its own — the real WebSocket endpoint, Silero VAD,
PostgreSQL and Redis — and drives N students at once. Each streams a real spoken question in real
time (20 ms frames, as a microphone does), hears the answer back at real speed, and acknowledges
playback as the browser client does. Reported per level of concurrency: how long students waited,
what failed, and what the server spent doing it.

**What this measures and what it does not.** The recogniser, the model and the synthesiser are
fakes. The model is paced like a real one — silence until the first token, then text at a steady
rate — but it never slows down under load, as a real API may, and the recogniser answers at once.
So these numbers are *our server* under load: its event loop, the VAD on every 32 ms window of
every session, the database and Redis. Not a provider's latency, and not TTFA.

    python scripts/load_voice.py --levels 1,10,25,50 --questions 3

It needs PostgreSQL and Redis running, and a database of its own (migrated), named by
VAANIOS_LOAD_DATABASE_URL (default: the local `vaanios_load`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUESTION = ROOT.parent / "datasets" / "v1" / "voice" / "parts" / "single-en-01-a.wav"
DATABASE = os.environ.get(
    "VAANIOS_LOAD_DATABASE_URL", "postgresql+asyncpg://vaanios:vaanios@localhost:5432/vaanios_load"
)
ANSWER = (
    "Kirchhoff's voltage law says the voltages around any closed loop add up to zero. "
    "Walk once around the loop and every rise is balanced by drops. "
    "Try it on a circuit with two resistors."
)
FRAME_S = 0.020


# --- the server ---------------------------------------------------------------------------


def serve(port: int, lag_file: Path, ttft_s: float, chars_per_s: float) -> None:
    """The application as `uvicorn app.asgi:app` runs it, with the model replaced by a paced fake
    and a probe that samples the event loop's lag every 50 ms."""
    import uvicorn

    from app.core.config import get_settings
    from app.main import create_app
    from app.providers.llm.base import TextDelta
    from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn

    class PacedLLM(FakeLLMProvider):
        async def stream(self, request: Any) -> AsyncIterator[Any]:
            first = True
            async for event in super().stream(request):
                if isinstance(event, TextDelta):
                    await asyncio.sleep(ttft_s if first else len(event.text) / chars_per_s)
                    first = False
                yield event

    async def probe(lags: list[float]) -> None:
        while True:
            start = time.perf_counter()
            await asyncio.sleep(0.05)
            lags.append((time.perf_counter() - start - 0.05) * 1000)

    app = create_app(get_settings())
    original = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(application: Any) -> AsyncIterator[None]:
        async with original(application):
            application.state.llm = PacedLLM([ScriptedTurn(text=ANSWER)], chunk_size=6)
            lags: list[float] = []
            task = asyncio.create_task(probe(lags))
            try:
                yield
            finally:
                task.cancel()
                await asyncio.to_thread(lag_file.write_text, json.dumps(lags))

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# --- one student --------------------------------------------------------------------------


@dataclass
class Turn:
    speech_end: float = 0.0
    final: float | None = None
    first_delta: float | None = None
    first_audio: float | None = None
    done: float | None = None
    thinking_seen: bool = False
    errors: list[str] = field(default_factory=list)
    server: dict[str, int] = field(default_factory=dict)


@dataclass
class Student:
    turns: list[Turn] = field(default_factory=list)
    connected: bool = False
    failure: str | None = None
    late_ms: float = 0.0  # how far behind real time this client fell sending audio


def _frames(path: Path) -> list[bytes]:
    with wave.open(str(path), "rb") as w:
        pcm = w.readframes(w.getnframes())
    size = 640  # 20 ms at 16 kHz, 16-bit
    return [pcm[i : i + size].ljust(size, b"\0") for i in range(0, len(pcm), size)]


async def student(
    url: str, token: str, speech: list[bytes], questions: int, offset: float, tts_rate: int
) -> Student:
    import websockets
    from websockets.typing import Subprotocol

    from app.voice.audio import AudioFrame
    from app.voice.protocol import decode_audio, encode_audio

    result = Student()
    silence = b"\0" * 640
    await asyncio.sleep(offset)
    try:
        async with websockets.connect(
            url, subprotocols=[Subprotocol("bearer"), Subprotocol(token)], max_size=None
        ) as ws:
            result.connected = True
            state: dict[str, Any] = {"state": "", "turn_id": 0}
            playback: dict[str, Any] = {"turn": -1, "received_ms": 0.0, "started": 0.0, "acked": 0}
            current: list[Turn] = []

            async def read() -> None:
                async for message in ws:
                    now = time.perf_counter()
                    turn = current[-1] if current else None
                    if isinstance(message, bytes):
                        frame = decode_audio(message)
                        if frame.turn_id != playback["turn"]:
                            playback.update(
                                turn=frame.turn_id, received_ms=0.0, started=now, acked=0
                            )
                        playback["received_ms"] += len(frame.pcm) / 2 / tts_rate * 1000
                        if turn is not None and turn.first_audio is None:
                            turn.first_audio = now
                        continue
                    data = json.loads(message)
                    kind = data["type"]
                    if kind == "state":
                        state.update(state=data["state"], turn_id=data["turn_id"])
                        if turn is not None:
                            if data["state"] == "thinking":
                                turn.thinking_seen = True
                            elif data["state"] == "listening" and turn.thinking_seen:
                                turn.done = turn.done or now
                    elif turn is None:
                        continue
                    elif kind == "stt.final" and turn.final is None:
                        turn.final = now
                    elif kind == "llm.delta" and turn.first_delta is None:
                        turn.first_delta = now
                    elif kind == "metrics":
                        turn.server = data.get("latency_ms", {})
                    elif kind == "error":
                        turn.errors.append(data.get("code", "?"))

            async def acknowledge() -> None:
                # A browser plays audio in real time and says how much it has played.
                while True:
                    await asyncio.sleep(0.2)
                    if playback["turn"] < 0:
                        continue
                    elapsed = (time.perf_counter() - playback["started"]) * 1000
                    played = int(min(playback["received_ms"], elapsed))
                    if played > playback["acked"]:
                        playback["acked"] = played
                        ack = {"type": "playback.ack", "turn_id": playback["turn"]}
                        await ws.send(json.dumps({**ack, "played_ms": played}))

            reader = asyncio.create_task(read())
            acker = asyncio.create_task(acknowledge())
            seq = 0
            clock = time.perf_counter()

            async def send(pcm: bytes) -> None:
                nonlocal seq, clock
                busy = state["state"] in ("thinking", "speaking")
                tag = state["turn_id"] + 1 if busy else state["turn_id"]
                await ws.send(encode_audio(AudioFrame(turn_id=tag, seq=seq, pcm=pcm)))
                seq += 1
                clock += FRAME_S
                delay = clock - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    result.late_ms = max(result.late_ms, -delay * 1000)

            for _ in range(questions):
                turn = Turn()
                current.append(turn)
                for pcm in [silence] * 15 + speech:
                    await send(pcm)
                turn.speech_end = time.perf_counter()
                deadline = turn.speech_end + 30
                while turn.done is None and time.perf_counter() < deadline:
                    await send(silence)
                # A short breath before the next question.
                for _ in range(25):
                    await send(silence)
                result.turns.append(turn)
            await ws.send(json.dumps({"type": "session.end"}))
            acker.cancel()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(reader, timeout=5)
    except Exception as exc:  # a failed connection is a result, not a crash
        result.failure = f"{type(exc).__name__}: {exc}"[:200]
    return result


# --- one level ----------------------------------------------------------------------------


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _proc_sample(pid: int) -> tuple[float, float]:
    """(CPU seconds used so far, resident memory in MB) of a process, from /proc."""
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    ticks = os.sysconf("SC_CLK_TCK")
    cpu = (int(stat[11]) + int(stat[12])) / ticks
    rss = next(
        int(line.split()[1]) / 1024
        for line in Path(f"/proc/{pid}/status").read_text().splitlines()
        if line.startswith("VmRSS:")
    )
    return cpu, rss


def _start_server(
    env: dict[str, str], port: int, lag_file: Path, ttft_s: float, rate: float
) -> Any:
    command = [sys.executable, str(Path(__file__)), "serve", "--port", str(port)]
    command += ["--lag-file", str(lag_file), "--ttft", str(ttft_s), "--rate", str(rate)]
    return subprocess.Popen(command, cwd=ROOT, env=env)  # noqa: S603 - our own script


def _read_lags(lag_file: Path) -> list[float]:
    lags: list[float] = json.loads(lag_file.read_text() or "[]") if lag_file.exists() else []
    lag_file.unlink(missing_ok=True)
    return lags


async def level(
    n: int, questions: int, port: int, ttft_s: float, chars_per_s: float
) -> dict[str, Any]:
    import httpx

    env = {
        **os.environ,
        "VAANIOS_DATABASE_URL": DATABASE,
        "VAANIOS_REDIS_URL": "redis://localhost:6379/14",
        "VAANIOS_JWT_SECRET": "load-test-secret-that-is-long-enough-to-pass-validation",
        "VAANIOS_LLM_PROVIDER": "fake",
        "VAANIOS_RATE_LIMIT_ENABLED": "false",
        "VAANIOS_LOG_LEVEL": "WARNING",
        "VAANIOS_LOG_JSON": "false",
    }
    lag_file = Path(tempfile.mkstemp(suffix=".json")[1])
    server = await asyncio.to_thread(_start_server, env, port, lag_file, ttft_s, chars_per_s)
    base = f"http://127.0.0.1:{port}/v1"
    try:
        async with httpx.AsyncClient(base_url=base, timeout=60) as http:
            for _ in range(100):
                with contextlib.suppress(httpx.HTTPError):
                    if (await http.get("/health")).status_code == 200:
                        break
                await asyncio.sleep(0.2)
            gate = asyncio.Semaphore(4)

            async def enrol() -> tuple[str, str]:
                async with gate:
                    email = f"load-{uuid.uuid4().hex[:12]}@example.com"
                    body = {
                        "email": email,
                        "password": "correct-horse-battery-staple",
                        "display_name": "Load",
                    }
                    token = (await http.post("/auth/register", json=body)).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    made = await http.post(
                        "/sessions", headers=headers, json={"transport": "websocket"}
                    )
                    return token, made.json()["id"]

            students = await asyncio.gather(*(enrol() for _ in range(n)))

        speech = _frames(QUESTION)
        samples: list[tuple[float, float, float]] = []

        async def sample() -> None:
            while True:
                cpu, rss = _proc_sample(server.pid)
                samples.append((time.perf_counter(), cpu, rss))
                await asyncio.sleep(0.5)

        sampler = asyncio.create_task(sample())
        rng = random.Random(n)  # noqa: S311 - start offsets, not secrets
        results = await asyncio.gather(
            *(
                student(
                    f"ws://127.0.0.1:{port}/v1/voice/ws?session_id={session_id}",
                    token,
                    speech,
                    questions,
                    rng.uniform(0, 2),
                    24_000,
                )
                for token, session_id in students
            )
        )
        sampler.cancel()
    finally:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
    lags = await asyncio.to_thread(_read_lags, lag_file)

    turns = [t for r in results for t in r.turns]
    complete = [t for t in turns if t.done is not None and t.first_audio is not None]
    wall = samples[-1][0] - samples[0][0] if len(samples) > 1 else 0.0
    cpu = (samples[-1][1] - samples[0][1]) / wall * 100 if wall else float("nan")
    errors: dict[str, int] = {}
    for t in turns:
        for code in t.errors:
            errors[code] = errors.get(code, 0) + 1
    failures: dict[str, int] = {}
    for r in results:
        if r.failure:
            failures[r.failure] = failures.get(r.failure, 0) + 1
    return {
        "sessions": n,
        "turns_expected": n * questions,
        "turns_complete": len(complete),
        "connected": sum(r.connected for r in results),
        "connection_failures": failures,
        "errors": errors,
        "final_ms": [(t.final - t.speech_end) * 1000 for t in complete if t.final],
        "first_audio_ms": [
            (t.first_audio - t.speech_end) * 1000 for t in complete if t.first_audio
        ],
        "server_ttfa_ms": [t.server["ttfa_ms"] for t in complete if "ttfa_ms" in t.server],
        "cpu_percent": cpu,
        "rss_peak_mb": max((s[2] for s in samples), default=float("nan")),
        "loop_lag_ms": lags,
        "client_late_ms": max((r.late_ms for r in results), default=0.0),
    }


def report(r: dict[str, Any]) -> str:
    def line(name: str, values: list[float]) -> str:
        return (
            f"  {name:26s} p50 {_pct(values, 0.5):7.0f}   p95 {_pct(values, 0.95):7.0f}"
            f"   max {max(values) if values else float('nan'):7.0f} ms"
        )

    lags = r["loop_lag_ms"]
    out = [
        f"{r['sessions']} sessions: {r['connected']} connected, {r['turns_complete']} of"
        f" {r['turns_expected']} turns complete",
        line("speech end → stt.final", r["final_ms"]),
        line("speech end → first audio", r["first_audio_ms"]),
        line("server ttfa_ms", r["server_ttfa_ms"]),
        f"  event-loop lag             p50 {_pct(lags, 0.5):7.1f}   p99 {_pct(lags, 0.99):7.1f}"
        f"   max {max(lags) if lags else float('nan'):7.1f} ms   ({len(lags)} samples)",
        f"  server CPU {r['cpu_percent']:5.0f}% of one core   RSS peak {r['rss_peak_mb']:6.0f} MB"
        f"   client fell behind by up to {r['client_late_ms']:.0f} ms",
    ]
    if r["errors"]:
        out.append(f"  errors {r['errors']}")
    if r["connection_failures"]:
        out.append(f"  failures {r['connection_failures']}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, required=True)
    server.add_argument("--lag-file", type=Path, required=True)
    server.add_argument("--ttft", type=float, required=True)
    server.add_argument("--rate", type=float, required=True)
    parser.add_argument("--levels", default="1,10,25,50")
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ttft", type=float, default=0.8, help="model's first token, seconds")
    parser.add_argument("--rate", type=float, default=150.0, help="model's characters per second")
    parser.add_argument("--json", type=Path, help="also write every level's raw numbers here")
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.port, args.lag_file, args.ttft, args.rate)
        return 0

    print(
        f"cpu {os.cpu_count()} · model paced at {args.ttft:g} s to first token, {args.rate:g}"
        f" chars/s · recogniser and synthesiser fakes · {args.questions} questions each"
    )
    everything = []
    for n in (int(x) for x in args.levels.split(",")):
        result = asyncio.run(level(n, args.questions, args.port, args.ttft, args.rate))
        everything.append(result)
        print(report(result), flush=True)
    if args.json:
        args.json.write_text(json.dumps(everything, indent=1))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
