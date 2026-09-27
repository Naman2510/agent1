"""The `voice` suite (eval/suites/voice.py): its dataset, its stand-ins, and its scoring.

The suite measures the production voice front end, so the first thing pinned here is that its
baseline config *is* the production configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings
from app.providers.stt.base import FinalTranscript, PartialTranscript
from app.voice.session import VoiceSessionConfig
from app.voice.vad import VadSettings
from eval.recording import CONFIGS, DATASETS, config_diff, load_config
from eval.suites import voice

VOICE = DATASETS / "v1" / "voice"
SILERO_PATH = Path("models/silero_vad.onnx")
needs_silero = pytest.mark.skipif(
    not SILERO_PATH.exists() and not os.environ.get("CI"),
    reason="Silero weights absent; run scripts/fetch_models.sh",
)


# --- the configs -------------------------------------------------------------------------


def test_the_baseline_config_is_the_production_configuration() -> None:
    _, config = load_config(CONFIGS / "voice.toml")
    fields = Settings.model_fields
    assert voice.vad_settings(config) == VadSettings(
        enter_threshold=fields["vad_enter_threshold"].default,
        exit_threshold=fields["vad_exit_threshold"].default,
        min_speech_ms=fields["vad_min_speech_ms"].default,
        min_silence_ms=fields["vad_min_silence_ms"].default,
    )
    assert voice.session_config(config) == VoiceSessionConfig(
        pre_roll_ms=fields["voice_pre_roll_ms"].default, ack_grace_ms=0
    )


def test_exp_003s_candidate_changes_one_knob() -> None:
    _, baseline = load_config(CONFIGS / "voice.toml")
    _, candidate = load_config(CONFIGS / "voice-semantic-endpointing.toml")
    assert config_diff(baseline, candidate) == ["session.semantic_endpointing"]


# --- the dataset -------------------------------------------------------------------------


def _wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(samples.astype("<i2").tobytes())


def test_a_case_is_assembled_where_its_record_says(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    tone = (np.sin(np.arange(1600) / 5) * 8000).astype(np.int16)  # 100 ms
    _wav(tmp_path / "parts" / "a.wav", tone)
    _wav(tmp_path / "parts" / "b.wav", tone)
    record = {
        "id": "t",
        "kind": "hesitation",
        "language": "en",
        "lead_ms": 500,
        "parts": [
            {"file": "parts/a.wav", "text": "What is"},
            {"file": "parts/b.wav", "text": "this?"},
        ],
        "pauses_ms": [300],
        "trail_ms": 1500,
        "noise": None,
    }
    case = voice.compose(record, tmp_path)

    assert case.speech == ((500, 600), (900, 1000))
    assert len(case.pcm) == (500 + 100 + 300 + 100 + 1500) * 32
    pause = np.frombuffer(case.pcm, dtype="<i2")[600 * 16 : 900 * 16]
    assert not pause.any(), "the pause is silence"
    assert [w.text for w in case.words] == ["What", "is", "this?"]
    assert case.words[-1].end_ms == 1000, "a part's last word ends where the part does"


def test_the_committed_dataset_assembles_identically_every_time() -> None:
    first = voice.load_cases(VOICE)
    second = voice.load_cases(VOICE)
    assert [hashlib.sha256(c.pcm).hexdigest() for c in first] == [
        hashlib.sha256(c.pcm).hexdigest() for c in second
    ]
    kinds = [c.kind for c in first]
    assert {k: kinds.count(k) for k in set(kinds)} == {
        "single": 12,
        "hesitation": 12,
        "multi_sentence": 12,
        "backchannel": 6,
        "noise": 6,
    }
    for case in first:
        if case.kind == "noise":
            assert case.speech == ()
        else:
            assert case.start_ms == 500, case.id
            assert len(case.speech) == 1 + len(case.pauses_ms), case.id


def test_the_dataset_says_it_is_synthetic() -> None:
    readme = (VOICE / "README.md").read_text(encoding="utf-8")
    assert "Synthetic, not human" in readme
    records = [json.loads(line) for line in (VOICE / "cases.jsonl").read_text().splitlines()]
    assert all(p["voice"] for r in records for p in r["parts"]), "every part says how it was made"


# --- the recogniser stand-in -------------------------------------------------------------


async def _listen(
    recogniser: voice.TimedRecogniser, clock: voice.AudioClock, chunks: list[tuple[int, int]]
) -> list[PartialTranscript | FinalTranscript]:
    """Deliver `(audio time, bytes)` chunks and collect what the recogniser says."""

    async def frames() -> AsyncIterator[bytes]:
        for at_ms, size in chunks:
            clock.ms = at_ms
            yield b"\x00" * size

    return [event async for event in recogniser.transcribe_stream(frames())]


def test_the_recogniser_releases_each_word_its_lag_after_it_was_spoken() -> None:
    words = [voice.Word("What", 0, 200), voice.Word("is", 200, 300), voice.Word("KVL?", 300, 600)]
    clock = voice.AudioClock()
    recogniser = voice.TimedRecogniser(words, clock, lag_ms=300)
    # The first chunk is the pre-roll: 500 ms of audio arriving at once, 500 ms in.
    events = asyncio.run(
        _listen(recogniser, clock, [(500, 500 * 32), (600, 640), (900, 640), (1000, 640)])
    )

    partials = [e.text for e in events if isinstance(e, PartialTranscript)]
    assert partials == ["What", "What is", "What is KVL?"]
    final = events[-1]
    assert isinstance(final, FinalTranscript)
    assert final.text == "What is KVL?"


def test_the_recogniser_hears_only_what_it_was_sent() -> None:
    """A question cut in two is transcribed in two pieces, as a real recogniser would."""
    words = [voice.Word("What", 0, 400), voice.Word("is", 400, 600), voice.Word("KVL?", 1500, 2000)]
    clock = voice.AudioClock()
    recogniser = voice.TimedRecogniser(words, clock, lag_ms=300)
    events = asyncio.run(_listen(recogniser, clock, [(1600, 300 * 32), (2400, 640)]))
    final = events[-1]
    assert isinstance(final, FinalTranscript)
    assert final.text == "KVL?"


# --- scoring -----------------------------------------------------------------------------


def _case(kind: str, speech: tuple[tuple[int, int], ...]) -> voice.VoiceCase:
    return voice.VoiceCase(
        id=kind, kind=kind, language="en", pcm=b"", speech=speech, words=(), pauses_ms=()
    )


def test_a_turn_begun_mid_question_is_a_cut_off() -> None:
    result = voice.CaseResult(
        _case("hesitation", ((500, 1500), (2000, 3000))),
        captures_ms=(800, 2300),
        turns_ms=(1700, 3500),
        end_reasons=("speech_end", "speech_end"),
    )
    assert result.cut_offs == 1
    assert result.endpoint_ms == 500
    assert result.detect_ms == 300
    assert not result.passed
    assert result.metrics(miss_penalty_ms=1500) == {
        "endpoint_ms": 500.0,
        "cut_off": 1.0,
        "missed": 0.0,
        "detect_ms": 300.0,
    }


def test_a_question_no_turn_followed_is_a_miss_scored_as_the_longest_wait() -> None:
    result = voice.CaseResult(
        _case("single", ((500, 1500),)), captures_ms=(), turns_ms=(), end_reasons=()
    )
    assert result.endpoint_ms is None
    assert result.metrics(miss_penalty_ms=1500)["endpoint_ms"] == 1500.0
    assert result.metrics(miss_penalty_ms=1500)["missed"] == 1.0


def test_a_turn_from_noise_or_an_acknowledgement_is_a_false_turn() -> None:
    noise = voice.CaseResult(_case("noise", ()), (900,), turns_ms=(1400,), end_reasons=())
    assert noise.false_turns == 1
    assert not noise.passed
    assert noise.metrics(miss_penalty_ms=1500) == {"false_turn": 1.0}
    quiet = voice.CaseResult(_case("backchannel", ((500, 800),)), (600,), (), ("speech_end",))
    assert quiet.passed


# --- through the real VAD ----------------------------------------------------------------


def _committed(case_id: str) -> voice.VoiceCase:
    return next(c for c in voice.load_cases(VOICE) if c.id == case_id)


@needs_silero
def test_a_spoken_question_becomes_one_turn_after_it_ends() -> None:
    _, config = load_config(CONFIGS / "voice.toml")
    [result] = asyncio.run(voice.run([_committed("single-en-01")], config))
    assert len(result.turns_ms) == 1
    assert result.cut_offs == 0
    endpoint = result.endpoint_ms
    assert endpoint is not None
    # The gate waits 500 ms of quiet; more than that is Silero taking a few windows to fall.
    assert 500 <= endpoint <= 800


@needs_silero
def test_keyboard_clatter_is_not_a_question() -> None:
    _, config = load_config(CONFIGS / "voice.toml")
    [result] = asyncio.run(voice.run([_committed("noise-keyboard-loud")], config))
    assert result.turns_ms == ()
