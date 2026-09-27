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
from eval import runner
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
