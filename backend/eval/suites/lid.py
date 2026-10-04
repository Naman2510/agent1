"""Language-identification suite.

Answers one question with a number: how often does the router pick the right language, broken
down by language and by difficulty?

**Read the bias note before quoting any figure from this.** The cases were authored by the same
person who wrote the lexicon under test. That is the strongest possible bias, it is recorded in
`datasets/v1/MANIFEST.yaml`, and it means these numbers measure *internal consistency* rather than
real-world accuracy. They are a baseline to improve against and a regression guard — not evidence
that the system works on real student speech.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.agent.lang.router import LanguageState, route
from eval.metrics.classification import ClassificationReport


@dataclass(frozen=True)
class LidCase:
    id: str
    text: str
    language: str
    difficulty: str = "unspecified"
    explicit: bool = False


def load_cases(path: Path) -> list[LidCase]:
    cases: list[LidCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            LidCase(
                id=row["id"],
                text=row["text"],
                language=row["language"],
                difficulty=row.get("difficulty", "unspecified"),
                explicit=bool(row.get("explicit", False)),
            )
        )
    return cases


@dataclass
class CaseOutcome:
    case: LidCase
    predicted: str
    passed: bool
    explanation: str


@dataclass
class LidResult:
    """Two reports, because there are two different questions.

    **signal** — did the utterance itself carry enough evidence to identify its language? A case
    with no usable signal counts as `unknown`, even where the router went on to answer correctly
    from its sticky prior. This is the number that says how good the *classifier* is.

    **routed** — what language did the router actually choose? A fresh session defaults to
    English, so an English utterance with no signal is still answered in English. This is closer
    to what a student experiences.

    Reporting only the first understates the system; reporting only the second hides that the
    signal is weak. Both, always.
    """

    signal: ClassificationReport
    routed: ClassificationReport
    outcomes: list[CaseOutcome]


def run(cases: list[LidCase]) -> LidResult:
    """Score each case independently.

    Each case starts from a fresh `LanguageState`, so this measures the utterance rather than the
    conversation. Stickiness and hysteresis are conversation properties, tested as sequences in
    the unit suite — averaging them into a per-utterance accuracy would conflate two things.
    """
    signal = ClassificationReport()
    routed = ClassificationReport()
    outcomes: list[CaseOutcome] = []

    for case in cases:
        decision = route(case.text, LanguageState())
        had_signal = decision.source != "sticky"
        signal_prediction = decision.language if had_signal else "unknown"

        signal.record(
            expected=case.language, predicted=signal_prediction, difficulty=case.difficulty
        )
        routed.record(
            expected=case.language, predicted=decision.language, difficulty=case.difficulty
        )
        outcomes.append(
            CaseOutcome(
                case=case,
                predicted=signal_prediction,
                passed=signal_prediction == case.language,
                explanation=decision.explain(),
            )
        )

    return LidResult(signal=signal, routed=routed, outcomes=outcomes)
