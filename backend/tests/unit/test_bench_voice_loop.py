"""scripts/bench_voice_loop.py, the voice loop's latency bench (EVALUATION.md §5.4).

It runs for real only in tier T2, where faster-whisper's weights can be downloaded, and a failure
there costs a half-hour cycle: T2 #9 found it could not import the harness, and T2 #10 that its
stand-in model lacked a method a barge-in calls. So its plumbing runs here, on every push: the
production session, Silero and eSpeak NG, with only Whisper's model stood in for.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest

from app.providers.stt.faster_whisper import FasterWhisperSTT
from eval.recording import DATASETS
from eval.suites import voice as voice_suite

BENCH = Path(__file__).resolve().parents[2] / "scripts" / "bench_voice_loop.py"
needs_silero = pytest.mark.skipif(
    not Path("models/silero_vad.onnx").exists() and not os.environ.get("CI"),
    reason="Silero weights absent; run scripts/fetch_models.sh",
)
requires_espeak = pytest.mark.skipif(
    shutil.which("espeak-ng") is None and not os.environ.get("CI"),
    reason="needs espeak-ng (apt install espeak-ng); CI installs it",
)


@pytest.fixture(scope="module")
def bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_voice_loop", BENCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: dataclasses look their module up while the class is being made.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _SlowWhisper:
    """Whisper's model, reduced to taking a second over each utterance, as `small` might on CPU."""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio: np.ndarray, **_: Any) -> tuple[Any, Any]:
        time.sleep(1.0)
        info = SimpleNamespace(
            language="en", language_probability=0.99, duration=audio.size / 16_000
        )
        return iter([SimpleNamespace(text=f" {self.text}")]), info


def _case(case_id: str, kind: str = "multi_sentence") -> Any:
    return SimpleNamespace(id=case_id, kind=kind, language="en")


# --- the counting ------------------------------------------------------------------------


def test_percentiles_are_values_that_occurred(bench: ModuleType) -> None:
    assert bench.percentiles([30.0, 10.0, 20.0]) == {"n": 3, "p50": 20.0, "p95": 30.0, "max": 30.0}
    # Twenty values: the 95th by nearest rank is the 19th, not a blend of the 19th and 20th.
    assert bench.percentiles([float(v) for v in range(1, 21)])["p95"] == 19.0
    assert bench.percentiles([]) == {"n": 0, "p50": None, "p95": None, "max": None}


def test_the_summary_says_how_many_turns_were_not_one_question_asked_once(
    bench: ModuleType,
) -> None:
    stages = {"turn_end_ms": 510, "stt_final_ms": 900, "tts_ttfb_ms": 20, "ttfa_ms": 1450}
    merged_model = bench._ScriptedModel()
    merged_model.continued.add("Let me see. Is it twelve volts?")
    outcomes = [
        # Asked once, answered once.
        (
            _case("single", "single"),
            _client(bench, {1: "Is it twelve volts?"}, stages),
            _model(bench),
        ),
        # Ended at its pause, interrupted by its second sentence, answered merged.
        (
            _case("merged"),
            _client(bench, {2: "Let me see. Is it twelve volts?"}, stages, interrupted=1),
            merged_model,
        ),
        # The first answer was over before the student went on: two turns.
        (
            _case("parts"),
            _client(bench, {1: "Let me see.", 2: "Is it twelve volts?"}, stages),
            _model(bench),
        ),
        # Never answered: the recogniser gave up, twice.
        (_case("silent"), bench._PlayingClient(errors={"stt_failed": 2}), _model(bench)),
    ]
    summary = bench.summarise(outcomes)

    assert summary["cases"] == 4
    assert [t["case"] for t in summary["turns"]] == ["single", "merged", "parts", "parts"]
    assert [t["merged"] for t in summary["turns"]] == [False, True, False, False]
    assert summary["interrupted"] == 1
    assert summary["merged"] == 1
    assert summary["answered_in_parts"] == ["parts"]
    assert summary["unanswered"] == ["silent"]
    assert summary["errors"] == {"stt_failed": 2}
    assert summary["stages"]["ttfa_ms"] == {"n": 4, "p50": 1450.0, "p95": 1450.0, "max": 1450.0}


def _client(
    bench: ModuleType, heard: dict[int, str], stages: dict[str, int], *, interrupted: int = 0
) -> Any:
    return bench._PlayingClient(
        latencies={turn_id: dict(stages) for turn_id in heard},
        heard=dict(heard),
        interrupted=interrupted,
    )


def _model(bench: ModuleType) -> Any:
    return bench._ScriptedModel()


async def test_the_scripted_model_answers_in_the_routed_language_and_notes_continuations(
    bench: ModuleType,
) -> None:
    model = bench._ScriptedModel()
    words = [
        fragment
        async for fragment, result in model.stream_turn(
            utterance="Let me see. Is it twelve volts?", language="mixed", continues="Let me see."
        )
        if result is None
    ]
    assert "".join(words).strip() == bench.REPLIES["hi-Latn"], "code-switched: the romanized reply"
    assert model.continued == {"Let me see. Is it twelve volts?"}
    await model.recover()  # what a barge-in calls (T2 #10)


# --- the loop, in real time ----------------------------------------------------------------


@needs_silero
@requires_espeak
async def test_a_question_ended_at_its_pause_is_answered_once_merged(bench: ModuleType) -> None:
    """multi-en-08 is one of the voice suite's five two-sentence cut-offs: its turn ends at the
    pause between its sentences. The second sentence starts while the first is still being
    transcribed, so it interrupts the turn before anything is heard, and the two are answered as
    one question (ARCHITECTURE §5.6). The case plays in real time, about six seconds."""
    from app.providers.tts.espeak import EspeakTTSProvider

    [case] = [c for c in voice_suite.load_cases(DATASETS / "v1" / "voice") if c.id == "multi-en-08"]
    stt = FasterWhisperSTT(model=_SlowWhisper("Is the answer twelve volts?"))

    client, model = await bench.run_case(case, stt=stt, tts=EspeakTTSProvider())

    assert client.interrupted == 1, "the second sentence interrupted the first turn"
    [(turn_id, latency)] = client.latencies.items()
    assert client.heard[turn_id] == "Is the answer twelve volts? Is the answer twelve volts?"
    assert client.heard[turn_id] in model.continued, "answered as one question"
    assert set(bench.STAGES) <= set(latency), "every stage EVALUATION.md §5.4 reports"
    assert latency["stt_final_ms"] >= 1000, "the recogniser's second is in the transcript's time"
    assert latency["ttfa_ms"] >= latency["turn_end_ms"] + latency["stt_final_ms"]
    assert client.received[turn_id] > 0, "the answer was spoken"
