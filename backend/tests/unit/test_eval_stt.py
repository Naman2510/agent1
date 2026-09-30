"""The `stt` suite's scoring (eval/suites/stt.py) and the faster-whisper adapter, without a model.

The model itself runs in CI tier T2, where its weights can be downloaded.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from app.core.config import Settings
from app.providers.registry import build_stt
from app.providers.stt import faster_whisper as fw
from app.providers.stt.base import FinalTranscript
from eval import harness, runner
from eval.recording import DATASETS
from eval.suites import stt

VOICE = DATASETS / "v1" / "voice"


def test_normalisation_ignores_case_and_punctuation_but_nothing_else() -> None:
    assert stt.normalise("What's  Kirchhoff's LAW?") == "whats kirchhoffs law"
    assert stt.normalise("किरचॉफ का नियम क्या है।") == "किरचॉफ का नियम क्या है"
    assert stt.normalise("Twelve volts.") != stt.normalise("12 volts.")


def test_edit_distance() -> None:
    assert stt._edits(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert stt._edits(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert stt._edits(["a", "b", "c"], ["a", "c"]) == 1
    assert stt._edits([], ["a", "b"]) == 2


def _case(reference: str, language: str = "en") -> stt.SttCase:
    return stt.SttCase(id="c", language=language, reference=reference, audio=np.zeros(1), voice="v")


def test_a_case_is_scored_in_words_and_characters() -> None:
    scored = stt.score(
        _case("What is Kirchhoff's voltage law?"), "what is kirchhoff voltage law", "en"
    )
    assert (scored.word_edits, scored.words) == (1, 5)
    assert scored.wer == pytest.approx(0.2)
    assert (scored.char_edits, scored.chars) == (1, 26)


def test_error_rates_are_pooled_over_words_not_averaged_over_cases() -> None:
    nine = "one two three four five six seven eight nine"
    long_right = stt.score(_case(nine), nine, "en")
    short_wrong = stt.score(_case("ten", "hi"), "tin", "en")
    summary = stt.summarise([long_right, short_wrong])
    assert summary["wer"] == pytest.approx(0.1)  # 1 edit in 10 words, not the mean of 0 and 1
    assert summary["exact"] == 1
    assert summary["by_language"]["hi"]["wer"] == 1.0
    assert summary["by_language"]["hi"]["language_detected_as_written"] == 0


def test_every_spoken_part_of_the_voice_dataset_is_a_case() -> None:
    cases = stt.load_cases(VOICE)
    assert len(cases) == 66
    assert {c.language for c in cases} == {"en", "hi", "hi-Latn"}
    assert all(c.audio.dtype == np.float32 and len(c.audio) > 1600 for c in cases)
    assert all(float(c.audio.min()) >= -1.0 and float(c.audio.max()) <= 1.0 for c in cases)


def test_a_config_runs_only_in_its_own_ci_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    push = tmp_path / "every-push.toml"
    push.write_text('suite = "lid"\n')
    nightly = tmp_path / "nightly.toml"
    nightly.write_text('suite = "lid"\ntier = "T2"\n')
    argv = ["runner", "--config", str(push), str(nightly), "--tier", "T2"]
    monkeypatch.setattr(sys, "argv", argv)

    assert runner.main() == 0
    out = capsys.readouterr().out
    assert "skipped          every-push (tier T1)" in out
    assert "config           nightly" in out
    assert "config           every-push" not in out


# --- the adapter ---------------------------------------------------------------------------


class _Model:
    """Stands in for faster_whisper.WhisperModel: records what it was asked, answers lazily."""

    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, dict[str, Any]]] = []

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append((audio, kwargs))
        segments = (SimpleNamespace(text=t) for t in (" What is", " KVL? "))
        return segments, SimpleNamespace(language="en", language_probability=0.93, duration=1.5)


async def _frames(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def test_the_adapter_transcribes_the_whole_utterance_once_it_ends() -> None:
    model = _Model()
    adapter = fw.FasterWhisperSTT("small", model=model)
    loud = (np.full(320, 16384, dtype="<i2")).tobytes()

    async def collect() -> list[Any]:
        return [e async for e in adapter.transcribe_stream(_frames(loud, loud))]

    [final] = asyncio.run(collect())
    assert isinstance(final, FinalTranscript)
    assert final.text == "What is KVL?"
    assert (final.language_hint, final.confidence, final.duration_ms) == ("en", 0.93, 1500)
    [(audio, kwargs)] = model.calls
    assert audio.dtype == np.float32 and len(audio) == 640 and audio.max() == pytest.approx(0.5)
    assert kwargs["language"] is None, "Whisper detects the language per utterance"
    assert kwargs["condition_on_previous_text"] is False
    assert kwargs["vad_filter"] is False, "the session's own VAD already found the speech"


def test_silence_that_reached_the_adapter_is_an_empty_transcript() -> None:
    adapter = fw.FasterWhisperSTT("small", model=_Model())

    async def collect() -> list[Any]:
        return [e async for e in adapter.transcribe_stream(_frames())]

    assert [e.text for e in asyncio.run(collect())] == [""]


def test_the_registry_builds_it_when_configured(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[tuple[str, str]] = []

    def fake_load(size: str, compute_type: str = "int8") -> _Model:
        loaded.append((size, compute_type))
        return _Model()

    monkeypatch.setattr(fw, "load_model", fake_load)
    provider = build_stt(settings.model_copy(update={"stt_provider": "faster-whisper"}))
    assert provider.info.name == "faster-whisper"
    assert loaded == [("small", "int8")]


def test_the_hint_is_the_routed_language_in_the_script_its_reference_is_written_in() -> None:
    assert stt.language_for(_case("x", "en"), "auto") is None
    assert stt.language_for(_case("x", "hi"), "hint") == "hi"
    assert stt.language_for(_case("x", "hi-Latn"), "hint") == "en", "romanized: Latin script"
    assert stt.language_for(_case("x", "hi"), "en") == "en", "a fixed language, for every case"


def test_the_run_passes_each_case_its_language() -> None:
    asked: list[str | None] = []

    def recognise(audio: np.ndarray, language: str | None) -> tuple[str, str | None]:
        asked.append(language)
        return "x", language

    stt.run([_case("x", "hi"), _case("x", "en")], recognise, language="hint")
    assert asked == ["hi", "en"]


def test_the_arithmetic_is_pinned_on_x86_and_the_summary_says_either_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (*stt.NUMERICS, *stt.STARTUP_PINS):
        monkeypatch.setenv(name, "left by the caller")  # and restored afterwards
    monkeypatch.setattr(stt.platform, "machine", lambda: "arm64")
    stt.pin_numerics()
    assert set(stt.numerics().values()) == {"left by the caller"}, "nothing to pin it to"

    monkeypatch.setattr(stt.platform, "machine", lambda: "x86_64")
    stt.pin_numerics()
    assert stt.numerics() == {
        **stt.NUMERICS,
        **dict.fromkeys(stt.STARTUP_PINS, "left by the caller"),
    }, "pinned over whatever the environment said, except what only takes effect at startup"


def test_what_takes_effect_only_at_startup_is_recorded_as_the_process_began(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """numpy and OpenBLAS read these when they load; set later, they would change nothing, and a
    baseline recording them would describe arithmetic that never ran (FC-006)."""
    for name in stt.STARTUP_PINS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stt.platform, "machine", lambda: "x86_64")
    stt.pin_numerics()
    assert {name: stt.numerics()[name] for name in stt.STARTUP_PINS} == dict.fromkeys(
        stt.STARTUP_PINS
    )

    # T2 starts the process with the pins the suite records.
    nightly = (Path(__file__).parents[3] / ".github" / "workflows" / "nightly.yml").read_text()
    for name, value in stt.STARTUP_PINS.items():
        assert f'{name}: "{value}"' in nightly, name


def test_a_run_names_the_cpu_model_it_was_computed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pins make one CPU model agree with itself, and nothing promises more (FC-006)."""
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(
        "processor\t: 0\nvendor_id\t: AuthenticAMD\n"
        "model name\t: AMD EPYC 7763 64-Core Processor                \n"
        "processor\t: 1\nmodel name\t: AMD EPYC 7763 64-Core Processor\n"
    )
    assert stt.machine(cpuinfo) == "AMD EPYC 7763 64-Core Processor"

    monkeypatch.setattr(stt.platform, "processor", lambda: "arm")
    assert stt.machine(tmp_path / "absent") == "arm", "no /proc/cpuinfo: the platform's name"
    cpuinfo.write_text("processor\t: 0\nCPU implementer\t: 0x41\n")
    assert stt.machine(cpuinfo) == "arm", "and no model name in it either"


def test_each_utterance_is_heard_by_a_model_of_its_own_seeded_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeds: list[int] = []
    made: list[tuple[str, dict[str, Any]]] = []
    models: list[_Model] = []

    def whisper_model(path: str, **kwargs: Any) -> _Model:
        made.append((path, kwargs))
        models.append(_Model())
        return models[-1]

    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(set_random_seed=seeds.append))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=whisper_model))
    utils = SimpleNamespace(download_model=lambda size: f"/models/{size}")
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    for name in stt.NUMERICS:
        monkeypatch.setenv(name, "")  # restored afterwards; pinning overwrites it
    config = {"recogniser": {"model": "small", "compute_type": "int8", "cpu_threads": 4, "seed": 7}}

    recognise = stt.faster_whisper_recogniser(config)
    assert recognise(np.zeros(160, np.float32), None) == ("What is KVL?", "en")
    assert recognise(np.zeros(160, np.float32), "hi") == ("What is KVL?", "en")

    assert seeds == [7], "seeded once, before any model has sampled"
    options = {"device": "cpu", "compute_type": "int8", "cpu_threads": 4}
    assert made == [("/models/small", options)] * 2, "a model of its own for each utterance"
    [(_, first)], [(_, second)] = (m.calls for m in models)
    assert (first["language"], second["language"]) == (None, "hi")
    assert first["beam_size"] == 5 and first["condition_on_previous_text"] is False


def test_the_suite_records_each_case_and_how_its_arithmetic_was_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    references = {c.audio.tobytes(): c.reference for c in stt.load_cases(VOICE)}

    def recogniser(config: dict[str, Any]) -> stt.Recognise:
        return lambda audio, language: (references[audio.tobytes()], language)

    monkeypatch.setattr(stt, "faster_whisper_recogniser", recogniser)
    monkeypatch.setattr(stt, "machine", lambda: "the CI runner's CPU")
    for name in (*stt.NUMERICS, *stt.STARTUP_PINS):
        monkeypatch.setenv(name, "as pinned")
    config = {"suite": "stt", "recogniser": {"language": "hint"}}

    outcome = asyncio.run(harness._evaluate_stt(config, DATASETS / "v1", False, None))

    assert outcome.summary["wer"] == 0.0 and outcome.summary["cases"] == 66
    pins = (*stt.NUMERICS, *stt.STARTUP_PINS)
    assert outcome.summary["numerics"] == dict.fromkeys(pins, "as pinned")
    assert outcome.summary["machine"] == "the CI runner's CPU"
    assert "machine     the CI runner's CPU" in outcome.report
    hindi = next(c for c in outcome.cases if c.language == "hi")
    assert hindi.actual["language"] == "hi", "told the routed language"
    assert hindi.metrics == {"wer": 0.0, "cer": 0.0, "wer_hi": 0.0}
