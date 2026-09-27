"""The `stt` suite: word and character error rates, per language (EVALUATION.md §3).

The references are the synthetic voice dataset's own texts: every spoken part in
datasets/v1/voice/ was synthesised from a known sentence, so each is a recording with an exact
transcript. That makes this a measurement of how a recogniser hears *eSpeak*, a formant
synthesiser — useful for comparing recognisers and settings with each other, and for catching a
recogniser that has broken, but not a statement about any human's speech (M7-03). The romanized
Hindi parts are read by the English voice, and are scored against their romanized spelling; that
column mostly measures how far apart those two are.

Text is compared after the same normalisation for reference and hypothesis: case folded,
apostrophes dropped, other Unicode punctuation (the danda included) removed, whitespace collapsed.
Nothing else — numbers written as digits count against the recogniser, since a student's "twelve
volts" is what the reference says.
"""

from __future__ import annotations

import json
import os
import platform
import unicodedata
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.providers.stt.faster_whisper import FasterWhisperSTT
from app.voice.audio import SAMPLE_RATE
from eval.recording import SuiteUnavailableError


@dataclass(frozen=True)
class SttCase:
    id: str
    language: str
    reference: str
    audio: np.ndarray  # float32, 16 kHz mono
    voice: str


def load_cases(root: Path) -> list[SttCase]:
    """One case per spoken part of the voice dataset."""
    cases = []
    for line in (root / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for part in record["parts"]:
            with wave.open(str(root / part["file"]), "rb") as w:
                if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
                    raise ValueError(f"{part['file']} is not 16 kHz mono")
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            cases.append(
                SttCase(
                    id=Path(part["file"]).stem,
                    language=record["language"],
                    reference=part["text"],
                    audio=pcm.astype(np.float32) / 32768.0,
                    voice=part["voice"],
                )
            )
    return cases


def dataset_files(root: Path) -> list[Path]:
    return [root / "cases.jsonl", *sorted((root / "parts").glob("*.wav"))]


APOSTROPHES = "'\u2019"


def normalise(text: str) -> str:
    """Case folded; apostrophes dropped (so "Kirchhoffs" is one word wrong, not two); every other
    punctuation mark, the danda included, a word break."""
    folded = unicodedata.normalize("NFC", text).casefold()
    kept = "".join(
        "" if ch in APOSTROPHES else " " if unicodedata.category(ch).startswith("P") else ch
        for ch in folded
    )
    return " ".join(kept.split())


def _edits(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Levenshtein distance over tokens (words, or characters)."""
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, start=1):
        current = [i]
        for j, hyp in enumerate(hypothesis, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class Scored:
    case: SttCase
    hypothesis: str
    detected_language: str | None
    word_edits: int
    words: int
    char_edits: int
    chars: int

    @property
    def wer(self) -> float:
        return self.word_edits / self.words if self.words else 0.0

    @property
    def cer(self) -> float:
        return self.char_edits / self.chars if self.chars else 0.0


def score(case: SttCase, hypothesis: str, detected_language: str | None) -> Scored:
    ref, hyp = normalise(case.reference), normalise(hypothesis)
    ref_chars, hyp_chars = ref.replace(" ", ""), hyp.replace(" ", "")
    return Scored(
        case=case,
        hypothesis=hypothesis,
        detected_language=detected_language,
        word_edits=_edits(ref.split(), hyp.split()),
        words=len(ref.split()),
        char_edits=_edits(list(ref_chars), list(hyp_chars)),
        chars=len(ref_chars),
    )


# `audio, language to decode in (None: detect it) -> (text, detected language)`.
Recognise = Callable[[np.ndarray, str | None], tuple[str, str | None]]

# What `language = "hint"` tells the recogniser for each case: the language the session's router
# decides before the recogniser runs (ADR-0011) — here each case's own label, so the best such a
# hint can ever be (EXP-013). Romanized Hindi is written in Latin script, which is what Whisper
# writes when told "en"; told "hi", it writes Devanagari.
HINTS = {"en": "en", "hi": "hi", "hi-Latn": "en"}


def language_for(case: SttCase, setting: str) -> str | None:
    """The language to decode `case` in under the config's `language` setting: "auto" to let the
    recogniser detect it, "hint" for the routed language, or one fixed code."""
    if setting == "auto":
        return None
    if setting == "hint":
        return HINTS[case.language]
    return setting


# CTranslate2 picks its kernels, and Intel MKL its code path, from the CPU it finds, so two CI
# runners computed different transcripts from the same audio (PHASE_8_AUDIT D8-15). These pin one
# path for every x86-64 machine with AVX2: CTranslate2's own kernels, MKL for every matrix product
# (by default it is used only on Intel CPUs), and MKL's reproducible mode. They must be set before
# either library starts, so they are set here, over whatever the environment said.
NUMERICS = {"CT2_FORCE_CPU_ISA": "AVX2", "CT2_USE_MKL": "1", "MKL_CBWR": "AVX2"}


def pin_numerics() -> None:
    """Pin the arithmetic (NUMERICS) on x86-64; elsewhere there is nothing to pin it to, and the
    run's summary says so (`numerics`)."""
    if platform.machine().lower() in {"x86_64", "amd64"}:
        os.environ.update(NUMERICS)


def numerics() -> dict[str, str | None]:
    """The pins in effect, for the summary: a baseline says how its numbers were computed."""
    return {name: os.environ.get(name) for name in NUMERICS}


def faster_whisper_recogniser(config: dict[str, Any]) -> Recognise:
    """The configured faster-whisper model, decoding exactly as the app's adapter does
    (FasterWhisperSTT), as a `Recognise` whose answer depends only on the audio."""
    pin_numerics()
    try:
        import ctranslate2
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SuiteUnavailableError(
            "the stt suite needs faster-whisper: pip install -e '.[voice-local]'"
        ) from exc

    settings = config.get("recogniser", {})
    size = str(settings.get("model", "small"))
    try:
        path = download_model(size)
    except Exception as exc:  # pragma: no cover - depends on the network
        raise SuiteUnavailableError(
            f"the stt suite could not load faster-whisper {size!r} ({type(exc).__name__}: "
            f"{exc}). Its weights come from huggingface.co on first use, which this network may "
            "block; CI tier T2 (.github/workflows/nightly.yml) runs it where it is reachable."
        ) from exc
    compute_type = str(settings.get("compute_type", "int8"))
    # MKL promises the same numbers only at the same thread count, so it is fixed, not left to
    # the machine (0 would be "as many as this CPU has").
    cpu_threads = int(settings.get("cpu_threads", 0))
    beam_size = int(settings.get("beam_size", 5))
    # Whisper's fallback samples. CTranslate2 seeds its sampler once per model, when the model
    # first samples, and cannot be reseeded after — so every utterance gets a model of its own:
    # each is heard as if it came first, whatever the utterances before it did.
    ctranslate2.set_random_seed(int(settings.get("seed", 0)))

    def recognise(audio: np.ndarray, language: str | None) -> tuple[str, str | None]:
        model = WhisperModel(path, device="cpu", compute_type=compute_type, cpu_threads=cpu_threads)
        adapter = FasterWhisperSTT(size, beam_size=beam_size, language=language, model=model)
        heard = adapter.transcribe(audio)
        return heard.text, heard.language_hint

    return recognise


def run(cases: Sequence[SttCase], recognise: Recognise, *, language: str = "auto") -> list[Scored]:
    return [score(case, *recognise(case.audio, language_for(case, language))) for case in cases]


def summarise(results: Sequence[Scored]) -> dict[str, Any]:
    def pooled(rows: Sequence[Scored]) -> dict[str, Any]:
        words = sum(r.words for r in rows)
        chars = sum(r.chars for r in rows)
        return {
            "cases": len(rows),
            # Pooled over the words, not averaged over cases: a long sentence counts for more.
            "wer": round(sum(r.word_edits for r in rows) / words, 4) if words else None,
            "cer": round(sum(r.char_edits for r in rows) / chars, 4) if chars else None,
            "exact": sum(r.word_edits == 0 for r in rows),
            "language_detected_as_written": sum(
                (r.detected_language or "").split("-")[0] == r.case.language.split("-")[0]
                for r in rows
            ),
        }

    languages = sorted({r.case.language for r in results})
    return {
        **pooled(results),
        "by_language": {
            lang: pooled([r for r in results if r.case.language == lang]) for lang in languages
        },
    }


def render(summary: dict[str, Any], config: dict[str, Any]) -> str:
    settings = config.get("recogniser", {})
    pins = summary.get("numerics") or {}
    lines = [
        f"recogniser  faster-whisper {settings.get('model', 'small')}"
        f" ({settings.get('compute_type', 'int8')}, beam {settings.get('beam_size', 5)},"
        f" language {settings.get('language', 'auto')}, seed {settings.get('seed', 0)})",
        "numerics    "
        + (" ".join(f"{k}={v or 'unset'}" for k, v in pins.items()) or "not recorded"),
        "speech      eSpeak NG, synthetic — not a measurement of anyone's voice",
        "",
        "language   cases    WER    CER  exact  language detected as written",
    ]
    rows = [("all", summary), *summary["by_language"].items()]
    for name, row in rows:
        lines.append(
            f"{name:8s} {row['cases']:7d} {row['wer']:6.3f} {row['cer']:6.3f} {row['exact']:6d}"
            f"  {row['language_detected_as_written']}"
        )
    return "\n".join(lines)
