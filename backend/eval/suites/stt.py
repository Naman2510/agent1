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
import unicodedata
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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


Recognise = Callable[[np.ndarray], tuple[str, str | None]]


def faster_whisper_recogniser(config: dict[str, Any]) -> Recognise:
    """The configured faster-whisper model, as `audio -> (text, detected language)`."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SuiteUnavailableError(
            "the stt suite needs faster-whisper: pip install -e '.[voice-local]'"
        ) from exc

    settings = config.get("recogniser", {})
    size = str(settings.get("model", "small"))
    try:
        model = WhisperModel(
            size, device="cpu", compute_type=str(settings.get("compute_type", "int8"))
        )
    except Exception as exc:  # pragma: no cover - depends on the network
        raise SuiteUnavailableError(
            f"the stt suite could not load faster-whisper {size!r} ({type(exc).__name__}: "
            f"{exc}). Its weights come from huggingface.co on first use, which this network may "
            "block; CI tier T2 (.github/workflows/nightly.yml) runs it where it is reachable."
        ) from exc
    language = settings.get("language", "auto")
    beam_size = int(settings.get("beam_size", 5))

    def recognise(audio: np.ndarray) -> tuple[str, str | None]:
        segments, info = model.transcribe(
            audio,
            language=None if language == "auto" else language,
            beam_size=beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language

    return recognise


def run(cases: Sequence[SttCase], recognise: Recognise) -> list[Scored]:
    return [score(case, *recognise(case.audio)) for case in cases]


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
    lines = [
        f"recogniser  faster-whisper {settings.get('model', 'small')}"
        f" ({settings.get('compute_type', 'int8')}, beam {settings.get('beam_size', 5)},"
        f" language {settings.get('language', 'auto')})",
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
