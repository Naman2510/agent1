"""Romanized-language identification for Latin-script text.

This is the project's hardest component and the one most likely to stay weak (R-04). The approach
is deliberately simple and inspectable:

* Count tokens that are Hindi grammatical scaffolding, and tokens that are English scaffolding.
* Ignore tokens that carry no evidence — technical vocabulary (which a Hindi sentence keeps in
  English on purpose) and words valid in both languages.
* Decide from the ratio, and report a confidence that falls with the amount of evidence.

What it is not: a trained classifier. `fastText lid.176` and provider language hints both label
romanized Hindi as English, which is why neither is used as the decision. A lexicon at least fails
*legibly* — every decision can be traced to the tokens that caused it, which is what makes the
failure cases in EVALUATION.md actionable.

Accuracy is measured, not asserted: see `eval/suites/lid.py` and the baseline table in
EVALUATION.md. The bias in that measurement (cases authored by the same person who wrote this
lexicon) is recorded there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.lang.lexicon import (
    AMBIGUOUS_TOKENS,
    ENGLISH_ONLY,
    HINDI_ONLY,
    TAMIL_FUNCTION_WORDS,
    TECHNICAL_NEUTRAL,
)

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")

# Ratio of Hindi evidence to total evidence above which the utterance reads as Hindi.
HINDI_THRESHOLD = 0.45
# Both sides above this share, with enough evidence, reads as genuinely mixed.
MIXED_MIN_SHARE = 0.25
# Below this many evidence tokens the decision is reported as low-confidence, so the router falls
# back to the session's sticky prior rather than flapping on a two-word utterance.
MIN_EVIDENCE_TOKENS = 2


@dataclass(frozen=True)
class RomanizedGuess:
    language: str  # en | hi-Latn | ta-Latn | mixed | unknown
    confidence: float
    hindi_hits: tuple[str, ...] = field(default_factory=tuple)
    english_hits: tuple[str, ...] = field(default_factory=tuple)
    tamil_hits: tuple[str, ...] = field(default_factory=tuple)
    neutral_hits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def evidence_tokens(self) -> int:
        return len(self.hindi_hits) + len(self.english_hits) + len(self.tamil_hits)

    def explain(self) -> str:
        """Why this decision was made. Every failure case should be traceable to its tokens."""
        return (
            f"{self.language} (conf {self.confidence:.2f}) "
            f"hi={list(self.hindi_hits)} en={list(self.english_hits)} "
            f"ta={list(self.tamil_hits)} neutral={list(self.neutral_hits)}"
        )


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def classify(text: str) -> RomanizedGuess:
    tokens = tokenize(text)
    if not tokens:
        return RomanizedGuess(language="unknown", confidence=0.0)

    hindi = tuple(t for t in tokens if t in HINDI_ONLY)
    english = tuple(t for t in tokens if t in ENGLISH_ONLY)
    tamil = tuple(t for t in tokens if t in TAMIL_FUNCTION_WORDS)
    neutral = tuple(t for t in tokens if t in TECHNICAL_NEUTRAL or t in AMBIGUOUS_TOKENS)

    evidence = len(hindi) + len(english) + len(tamil)
    if evidence == 0:
        # No scaffolding at all. Common for a bare technical phrase ("displacement current") or a
        # single word. Explicitly uncertain rather than guessed as English.
        return RomanizedGuess(language="unknown", confidence=0.0, neutral_hits=neutral)

    # Confidence grows with evidence and saturates: four scaffolding tokens is as sure as this
    # method gets, and claiming more would be false precision.
    evidence_confidence = min(1.0, evidence / 4.0)

    if len(tamil) > len(hindi) and len(tamil) > len(english):
        # Recognised so it is not silently called English. Tamil is deferred past the MVP and
        # this path has had no evaluation (Gate 0 finding M-01), hence the capped confidence.
        return RomanizedGuess(
            language="ta-Latn",
            confidence=min(0.5, evidence_confidence),
            hindi_hits=hindi,
            english_hits=english,
            tamil_hits=tamil,
            neutral_hits=neutral,
        )

    hindi_share = len(hindi) / evidence
    english_share = len(english) / evidence

    if hindi_share >= MIXED_MIN_SHARE and english_share >= MIXED_MIN_SHARE and evidence >= 4:
        language = "mixed"
        confidence = evidence_confidence * (1 - abs(hindi_share - english_share))
    elif hindi_share >= HINDI_THRESHOLD:
        language = "hi-Latn"
        confidence = evidence_confidence * hindi_share
    else:
        language = "en"
        confidence = evidence_confidence * english_share

    if evidence < MIN_EVIDENCE_TOKENS:
        # Reported, but weakly: the router prefers its sticky prior over a one-token decision.
        confidence = min(confidence, 0.3)

    return RomanizedGuess(
        language=language,
        confidence=round(confidence, 3),
        hindi_hits=hindi,
        english_hits=english,
        tamil_hits=tamil,
        neutral_hits=neutral,
    )
