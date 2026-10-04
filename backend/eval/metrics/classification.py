"""Classification metrics with per-class breakdown.

Per-class, always, and the aggregate reported last — because an aggregate over an unbalanced set
hides the case that matters. For this project the interesting row is romanized Hinglish, and it is
also the smallest and hardest, so a single accuracy figure would flatter the system exactly where
it is weakest (EVALUATION.md §3.2).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class ClassMetrics:
    label: str
    support: int = 0
    correct: int = 0
    predicted: int = 0

    @property
    def recall(self) -> float:
        return self.correct / self.support if self.support else 0.0

    @property
    def precision(self) -> float:
        return self.correct / self.predicted if self.predicted else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class ClassificationReport:
    per_class: dict[str, ClassMetrics] = field(default_factory=dict)
    confusion: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    total: int = 0
    correct: int = 0
    by_difficulty: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def record(self, *, expected: str, predicted: str, difficulty: str = "unspecified") -> None:
        self.total += 1
        hit = expected == predicted
        self.correct += int(hit)

        self.per_class.setdefault(expected, ClassMetrics(expected)).support += 1
        self.per_class.setdefault(predicted, ClassMetrics(predicted)).predicted += 1
        if hit:
            self.per_class[expected].correct += 1
        self.confusion[(expected, predicted)] += 1
        self.by_difficulty[difficulty]["total"] += 1
        self.by_difficulty[difficulty]["correct"] += int(hit)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def macro_f1(self) -> float:
        """Unweighted mean F1 across classes with support.

        Unweighted on purpose: it refuses to let the large easy classes drown out the small hard
        ones, which is the whole reason for reporting it alongside accuracy.
        """
        scored = [m for m in self.per_class.values() if m.support]
        return sum(m.f1 for m in scored) / len(scored) if scored else 0.0

    def difficulty_accuracy(self) -> dict[str, float]:
        return {
            name: (counts["correct"] / counts["total"] if counts["total"] else 0.0)
            for name, counts in sorted(self.by_difficulty.items())
        }

    def summary(self) -> dict[str, float]:
        return {
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "cases": self.total,
        }

    def render(self) -> str:
        labels = sorted(self.per_class)
        lines = [
            f"{'label':10s} {'support':>7s} {'recall':>7s} {'precision':>9s} {'f1':>6s}",
            "-" * 44,
        ]
        for label in labels:
            m = self.per_class[label]
            if not m.support and not m.predicted:
                continue
            lines.append(
                f"{label:10s} {m.support:7d} {m.recall:7.3f} {m.precision:9.3f} {m.f1:6.3f}"
            )
        lines.append("-" * 44)
        lines.append(f"{'overall':10s} {self.total:7d} {self.accuracy:7.3f}")
        lines.append(f"macro F1: {self.macro_f1:.3f}")

        lines.append("")
        lines.append("accuracy by difficulty")
        for name, value in self.difficulty_accuracy().items():
            counts = self.by_difficulty[name]
            lines.append(f"  {name:12s} {value:.3f}  (n={counts['total']})")

        confusions = sorted(
            ((c, e, p) for (e, p), c in self.confusion.items() if e != p),
            reverse=True,
        )
        if confusions:
            lines.append("")
            lines.append("confusions (expected -> predicted)")
            for count, expected, predicted in confusions:
                lines.append(f"  {expected:10s} -> {predicted:10s} {count}")
        return "\n".join(lines)
