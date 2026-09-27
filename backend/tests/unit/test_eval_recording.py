"""Run provenance, configs, and the experiment decision rule (eval/recording.py, eval/decision.py).

The recording itself, against a real database, is in tests/integration/test_eval_recording.py.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from eval import runner
from eval.decision import DecisionRule, Guard, bootstrap_interval, decide
from eval.harness import RETRIEVAL_MODES, SUITES
from eval.recording import (
    CONFIGS,
    CaseRecord,
    ConfigError,
    RunSpec,
    SuiteOutcome,
    config_diff,
    dataset_digest,
    load_config,
    log_to_mlflow,
    metric_name,
    numeric_metrics,
)

# --- provenance --------------------------------------------------------------


def test_a_dataset_digest_covers_names_and_content_but_not_listing_order(tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("one")
    b.write_text("two")
    digest = dataset_digest([a, b], root=tmp_path)
    assert digest == dataset_digest([b, a], root=tmp_path)

    b.write_text("two!")
    assert dataset_digest([a, b], root=tmp_path) != digest, "content changed"
    b.write_text("two")
    renamed = b.rename(tmp_path / "c.jsonl")
    assert dataset_digest([a, renamed], root=tmp_path) != digest, "a file was renamed"


# --- configs -----------------------------------------------------------------


def test_config_diff_names_each_changed_knob() -> None:
    base = {"suite": "retrieval", "retrieval": {"mode": "hybrid"}, "embedding": {"on": True}}
    assert config_diff(base, base) == []
    assert config_diff(base, {**base, "embedding": {"on": False}}) == ["embedding.on"]
    assert config_diff(base, {**base, "retrieval": {"mode": "vector_only", "k": 5}}) == [
        "retrieval.k",
        "retrieval.mode",
    ]


def test_a_config_must_name_its_suite(tmp_path: Path) -> None:
    path = tmp_path / "nameless.toml"
    path.write_text('[retrieval]\nmode = "hybrid"\n')
    with pytest.raises(ConfigError, match="suite"):
        load_config(path)


def test_every_committed_config_loads_and_names_a_known_suite() -> None:
    paths = sorted(CONFIGS.glob("*.toml"))
    assert paths
    for path in paths:
        name, config = load_config(path)
        assert name == path.stem
        assert config["suite"] in SUITES, path
        if config["suite"] == "retrieval":
            assert config["retrieval"]["mode"] in {*RETRIEVAL_MODES, "bm25_reference"}, path


def test_an_experiment_that_changes_two_knobs_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """EVALUATION.md §7: an experiment changes one variable, or its result cannot be attributed."""
    base = tmp_path / "base.toml"
    base.write_text('suite = "lid"\n[a]\nx = 1\ny = 1\n')
    candidate = tmp_path / "candidate.toml"
    candidate.write_text('suite = "lid"\n[a]\nx = 2\ny = 2\n')
    experiment = {
        "slug": "EXP-TEST",
        "title": "two knobs",
        "hypothesis": "h",
        "baseline": str(base),
        "candidate": str(candidate),
        "decision_rule": {"metric": "m", "higher_is_better": True, "min_effect": 0.1},
    }
    assert asyncio.run(runner.run_experiment(experiment, "v1", None, record=False)) == 2
    assert "a.x, a.y" in capsys.readouterr().out


# --- MLflow --------------------------------------------------------------------


def test_metric_names_are_ones_mlflow_accepts() -> None:
    assert metric_name("by_language.hi.recall@5") == "by_language.hi.recall_at_5"
    assert metric_name("p(95)") == "p_95_"


def test_only_numbers_become_metrics() -> None:
    summary = {"a": 1, "b": {"c": 0.5}, "flag": True, "label": "x"}
    assert numeric_metrics(summary) == {"a": 1.0, "b.c": 0.5}


def test_a_run_is_logged_to_mlflow_with_its_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlflow

    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setenv("MLFLOW_ARTIFACT_ROOT", (tmp_path / "artifacts").as_uri())
    spec = RunSpec(
        suite="retrieval",
        config_name="retrieval",
        config={"suite": "retrieval", "retrieval": {"mode": "hybrid"}},
        dataset_version="v1",
        dataset_digest="d" * 64,
        git_sha="abc1234",
        git_dirty=False,
    )
    outcome = SuiteOutcome(
        summary={"recall@5": 0.9, "by_language": {"en": {"mrr": 0.8}}, "label": "x"},
        cases=[CaseRecord(case_id="c1", passed=True)],
        report="",
        ok=True,
    )
    recorded = uuid.uuid4()
    run = mlflow.get_run(log_to_mlflow(spec, outcome, run_id=recorded))
    assert run.data.params["git_sha"] == "abc1234"
    assert run.data.params["dataset_digest"] == "d" * 64
    assert run.data.params["config.retrieval.mode"] == '"hybrid"'
    assert run.data.metrics == {"recall_at_5": 0.9, "by_language.en.mrr": 0.8}
    assert run.data.tags["evaluation_run_id"] == str(recorded)


# --- the decision rule ---------------------------------------------------------

RULE = DecisionRule(metric="ndcg@10", higher_is_better=True, min_effect=0.02)


def _cases(values: list[float], metric: str = "ndcg@10") -> dict[str, dict[str, float]]:
    return {f"c{i}": {metric: v} for i, v in enumerate(values)}


def test_a_consistent_gain_is_adopted() -> None:
    decision, comparison = decide(RULE, _cases([0.5] * 20), _cases([0.6] * 20))
    assert decision == "adopt"
    assert comparison["cases_better"] == 20
    assert comparison["gain_95ci"][0] > 0


def test_a_consistent_loss_is_rejected() -> None:
    decision, _ = decide(RULE, _cases([0.6] * 20), _cases([0.5] * 20))
    assert decision == "reject"


def test_a_gain_carried_by_one_case_is_inconclusive() -> None:
    """The mean clears the threshold, but one case of twenty carries it: the interval reaches
    zero, and on a dataset this small that is the honest answer."""
    decision, comparison = decide(RULE, _cases([0.5] * 20), _cases([0.5] * 19 + [1.0]))
    assert comparison["mean_gain"] >= RULE.min_effect
    assert comparison["gain_95ci"][0] <= 0
    assert decision == "inconclusive"


def test_a_failed_guard_rejects_even_a_winner() -> None:
    rule = DecisionRule(
        "ndcg@10", True, 0.02, guards=(Guard("recall@10", higher_is_better=True, max_loss=0.0),)
    )
    baseline = {f"c{i}": {"ndcg@10": 0.5, "recall@10": 1.0} for i in range(20)}
    candidate = {f"c{i}": {"ndcg@10": 0.7, "recall@10": 0.0 if i == 0 else 1.0} for i in range(20)}
    decision, comparison = decide(rule, baseline, candidate)
    assert decision == "reject"
    assert comparison["guards"]["recall@10"]["failed"]


def test_a_lower_is_better_metric_is_compared_the_right_way_round() -> None:
    rule = DecisionRule("endpoint_ms", higher_is_better=False, min_effect=50.0)
    decision, comparison = decide(
        rule, _cases([500.0] * 10, "endpoint_ms"), _cases([250.0] * 10, "endpoint_ms")
    )
    assert decision == "adopt"
    assert comparison["mean_gain"] == 250.0


def test_runs_with_no_cases_in_common_decide_nothing() -> None:
    decision, comparison = decide(RULE, _cases([0.5]), {"other": {"ndcg@10": 0.9}})
    assert decision == "inconclusive"
    assert comparison["cases"] == 0


def test_the_bootstrap_is_seeded_so_a_decision_reproduces() -> None:
    gains = [0.1, -0.2, 0.3, 0.05, 0.0, 0.2]
    assert bootstrap_interval(gains) == bootstrap_interval(gains)


# --- baselines ---------------------------------------------------------------


def _baseline_run(summary: dict[str, float]) -> tuple[RunSpec, SuiteOutcome]:
    spec = RunSpec(
        suite="lid",
        config_name="lid",
        config={"suite": "lid"},
        dataset_version="v1",
        dataset_digest="d" * 64,
        git_sha="abc1234",
        git_dirty=False,
    )
    return spec, SuiteOutcome(summary=summary, cases=[], report="", ok=True)


def test_a_run_reproduces_its_committed_baseline_or_names_what_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval import recording

    monkeypatch.setattr(recording, "BASELINES", tmp_path)
    spec, outcome = _baseline_run({"accuracy": 0.92, "by": {"en": 0.9}})
    recording.write_baseline(spec, outcome, run_id=None)

    assert recording.check_baseline(spec, outcome)[0] == 0

    _, moved = _baseline_run({"accuracy": 0.92, "by": {"en": 0.8}})
    code, lines = recording.check_baseline(spec, moved)
    assert code == 1
    assert "by.en" in lines[0]


def test_a_baseline_is_not_compared_across_changed_data_or_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from eval import recording

    monkeypatch.setattr(recording, "BASELINES", tmp_path)
    spec, outcome = _baseline_run({"accuracy": 0.92})
    recording.write_baseline(spec, outcome, run_id=None)

    assert recording.check_baseline(replace(spec, dataset_digest="e" * 64), outcome)[0] == 2
    other = replace(spec, config={"suite": "lid", "x": 1})
    assert recording.check_baseline(other, outcome)[0] == 2
    assert recording.check_baseline(replace(spec, config_name="nameless"), outcome)[0] == 2


def test_a_metric_is_compared_only_over_the_cases_that_have_it() -> None:
    """A noise clip has no turn-end latency; it must neither break the comparison nor count."""
    rule = DecisionRule(
        "endpoint_ms",
        higher_is_better=False,
        min_effect=50.0,
        guards=(Guard("cut_off", higher_is_better=False, max_loss=0.0),),
    )
    baseline = {f"q{i}": {"endpoint_ms": 500.0, "cut_off": 0.0} for i in range(10)}
    candidate = {f"q{i}": {"endpoint_ms": 300.0, "cut_off": 0.0} for i in range(10)}
    baseline["noise"] = candidate["noise"] = {"false_turn": 0.0}
    decision, comparison = decide(rule, baseline, candidate)
    assert decision == "adopt"
    assert comparison["cases"] == 10
