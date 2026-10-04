"""Deciding an experiment from its two runs (EVALUATION.md §7).

The rule is registered with the experiment, before either run, so a threshold cannot be chosen
after the numbers are known. It compares the two runs *per case* — the same cases, once under each
config — because on a few dozen cases a difference in the averages is mostly noise:

* **adopt** — the candidate is better by at least `min_effect`, and the 95% interval of the paired
  difference (bootstrap over cases) lies wholly on the side of better, and no guard metric got
  worse by more than it allows;
* **reject** — the candidate is worse by at least `min_effect` with the interval wholly on the side
  of worse, or a guard failed;
* **inconclusive** — anything else: too small a difference, or too few cases to tell. On small
  self-authored datasets this is the expected outcome, and saying so is the point.

The bootstrap is seeded, so the same two runs always give the same decision.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RESAMPLES = 10_000
SEED = 20260926


@dataclass(frozen=True)
class Guard:
    """A metric the candidate must not make worse by more than `max_loss` on average."""

    metric: str
    higher_is_better: bool
    max_loss: float


@dataclass(frozen=True)
class DecisionRule:
    metric: str
    higher_is_better: bool
    min_effect: float
    guards: tuple[Guard, ...] = ()

    @classmethod
    def from_config(cls, rule: Mapping[str, Any]) -> DecisionRule:
        return cls(
            metric=str(rule["metric"]),
            higher_is_better=bool(rule["higher_is_better"]),
            min_effect=float(rule["min_effect"]),
            guards=tuple(
                Guard(
                    metric=str(g["metric"]),
                    higher_is_better=bool(g["higher_is_better"]),
                    max_loss=float(g["max_loss"]),
                )
                for g in rule.get("guards", [])
            ),
        )


def _gain(baseline: float, candidate: float, higher_is_better: bool) -> float:
    """How much better the candidate is, in the metric's own units: positive means better."""
    return candidate - baseline if higher_is_better else baseline - candidate


def bootstrap_interval(gains: Sequence[float], *, seed: int = SEED) -> tuple[float, float]:
    """95% percentile interval of the mean per-case gain."""
    if not gains:
        return (0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311 - a seeded resampler, not a secret
    n = len(gains)
    means = sorted(sum(rng.choice(gains) for _ in range(n)) / n for _ in range(RESAMPLES))
    return means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]


def decide(
    rule: DecisionRule,
    baseline_cases: Mapping[str, Mapping[str, float]],
    candidate_cases: Mapping[str, Mapping[str, float]],
) -> tuple[str, dict[str, Any]]:
    """The decision and the comparison behind it. Cases are keyed by id; each maps metric name
    to value. A metric is compared over the cases that have it in both runs — a noise clip has
    no turn-end latency — and only those."""

    def having(metric: str) -> list[str]:
        return sorted(
            c
            for c in baseline_cases.keys() & candidate_cases.keys()
            if metric in baseline_cases[c] and metric in candidate_cases[c]
        )

    shared = having(rule.metric)
    if not shared:
        return "inconclusive", {"reason": "the runs share no cases with the metric", "cases": 0}

    def paired(metric: str, higher_is_better: bool) -> list[float]:
        return [
            _gain(
                float(baseline_cases[c][metric]),
                float(candidate_cases[c][metric]),
                higher_is_better,
            )
            for c in having(metric)
        ]

    gains = paired(rule.metric, rule.higher_is_better)
    mean_gain = sum(gains) / len(gains)
    low, high = bootstrap_interval(gains)
    comparison: dict[str, Any] = {
        "metric": rule.metric,
        "cases": len(shared),
        "baseline_mean": sum(float(baseline_cases[c][rule.metric]) for c in shared) / len(shared),
        "candidate_mean": sum(float(candidate_cases[c][rule.metric]) for c in shared) / len(shared),
        "mean_gain": mean_gain,
        "gain_95ci": [low, high],
        "cases_better": sum(g > 0 for g in gains),
        "cases_worse": sum(g < 0 for g in gains),
        "cases_same": sum(g == 0 for g in gains),
        "guards": {},
    }

    guard_failed = False
    for guard in rule.guards:
        guard_gains = paired(guard.metric, guard.higher_is_better)
        loss = -sum(guard_gains) / len(guard_gains) if guard_gains else 0.0
        failed = loss > guard.max_loss
        guard_failed = guard_failed or failed
        comparison["guards"][guard.metric] = {
            "mean_loss": loss,
            "max_loss": guard.max_loss,
            "failed": failed,
        }

    if guard_failed:
        return "reject", comparison
    if mean_gain >= rule.min_effect and low > 0:
        return "adopt", comparison
    if mean_gain <= -rule.min_effect and high < 0:
        return "reject", comparison
    return "inconclusive", comparison
