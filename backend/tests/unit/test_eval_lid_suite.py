"""The LID eval suite itself.

An evaluation harness that silently miscounts is worse than none, so the metric arithmetic and the
signal/routed distinction are tested directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.metrics.classification import ClassificationReport
from eval.suites import lid

CASES = Path(__file__).resolve().parents[2].parent / "datasets" / "v1" / "lid" / "cases.jsonl"


# --- metrics ---------------------------------------------------------------


def test_perfect_classification() -> None:
    report = ClassificationReport()
    for label in ("en", "hi", "en"):
        report.record(expected=label, predicted=label, difficulty="easy")
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0


def test_recall_and_precision_are_not_the_same_thing() -> None:
    """Two English cases, one caught; one Hindi case wrongly called English."""
    report = ClassificationReport()
    report.record(expected="en", predicted="en")
    report.record(expected="en", predicted="unknown")
    report.record(expected="hi", predicted="en")

    english = report.per_class["en"]
    assert english.support == 2
    assert english.recall == pytest.approx(0.5)
    assert english.predicted == 2
    assert english.precision == pytest.approx(0.5)
    assert report.accuracy == pytest.approx(1 / 3)


def test_macro_f1_is_unweighted_so_small_classes_still_count() -> None:
    """The point of reporting it: 20 easy cases must not drown out 2 hard ones."""
    report = ClassificationReport()
    for _ in range(20):
        report.record(expected="en", predicted="en")
    for _ in range(2):
        report.record(expected="mixed", predicted="en")

    assert report.accuracy == pytest.approx(20 / 22)
    # `mixed` scores zero, and macro F1 refuses to hide that.
    assert report.macro_f1 < 0.6


def test_confusions_are_recorded_directionally() -> None:
    report = ClassificationReport()
    report.record(expected="mixed", predicted="hi-Latn")
    report.record(expected="mixed", predicted="hi-Latn")
    assert report.confusion[("mixed", "hi-Latn")] == 2
    assert ("hi-Latn", "mixed") not in report.confusion


def test_difficulty_breakdown_shows_whether_easy_cases_carry_the_score() -> None:
    report = ClassificationReport()
    for _ in range(5):
        report.record(expected="en", predicted="en", difficulty="easy")
    for _ in range(5):
        report.record(expected="mixed", predicted="en", difficulty="hard")
    assert report.difficulty_accuracy() == {"easy": 1.0, "hard": 0.0}


def test_an_empty_report_does_not_divide_by_zero() -> None:
    report = ClassificationReport()
    assert report.accuracy == 0.0
    assert report.macro_f1 == 0.0
    assert report.render()


# --- the suite -------------------------------------------------------------


def test_the_dataset_loads_and_is_well_formed() -> None:
    cases = lid.load_cases(CASES)
    assert len(cases) >= 80
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"
    for case in cases:
        assert case.text.strip()
        assert case.language in {"en", "hi", "hi-Latn", "mixed", "ta", "unknown"}
        assert case.difficulty in {"easy", "medium", "hard", "unspecified"}


def test_the_dataset_includes_cases_the_system_is_expected_to_fail() -> None:
    """A set of only easy cases produces a flattering number and no information."""
    cases = lid.load_cases(CASES)
    hard = [c for c in cases if c.difficulty == "hard"]
    assert len(hard) >= 10
    assert any(c.language == "mixed" for c in cases), "code-switching must be represented"


def test_the_suite_reports_signal_and_routed_separately() -> None:
    """They answer different questions and must not be conflated."""
    cases = lid.load_cases(CASES)
    result = lid.run(cases)

    assert result.signal.total == result.routed.total == len(cases)
    # The router always picks a concrete language, so it never predicts `unknown`; the signal
    # report does, wherever the utterance carried no evidence.
    assert result.signal.per_class["unknown"].predicted > 0
    assert result.routed.per_class.get("unknown", None) is not None
    assert result.routed.per_class["unknown"].predicted == 0


def test_script_based_languages_are_identified_perfectly() -> None:
    """Devanagari and Tamil are settled by codepoints; anything less is a bug, not a limitation."""
    cases = lid.load_cases(CASES)
    result = lid.run(cases)
    for label in ("hi", "ta"):
        assert result.signal.per_class[label].recall == 1.0, label


def test_the_recorded_baseline_has_not_regressed() -> None:
    """Guards the number published in EVALUATION.md.

    A floor rather than an equality: the assertion should fail on a regression, not on an
    improvement. The baseline is deliberately NOT the maximum achievable — thresholds were not
    tuned against this self-authored set (see docs/failure_cases/002).
    """
    result = lid.run(lid.load_cases(CASES))
    assert result.signal.accuracy >= 0.90, result.signal.render()
    assert result.signal.macro_f1 >= 0.88
    assert result.routed.accuracy >= 0.85


def test_every_failure_can_be_explained_by_its_tokens() -> None:
    """Legibility is the reason a lexicon was chosen; an inexplicable failure is not actionable."""
    result = lid.run(lid.load_cases(CASES))
    for outcome in result.outcomes:
        if not outcome.passed:
            assert "hi=" in outcome.explanation or "script" in outcome.explanation


def test_the_manifest_records_the_bias() -> None:
    """The dataset's central caveat must be in the dataset, not only in a commit message."""
    manifest = (CASES.parent.parent / "MANIFEST.yaml").read_text(encoding="utf-8")
    assert "bias:" in manifest
    assert "severity: high" in manifest
    assert "authored by the same person" in manifest


def test_case_ids_are_stable_json() -> None:
    """Rows are append-only records; malformed JSON would silently drop cases."""
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            assert "id" in row and "text" in row and "language" in row
