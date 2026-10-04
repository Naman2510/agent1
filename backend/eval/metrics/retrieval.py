"""Retrieval metrics: recall@k, precision@k, MRR, nDCG@k (EVALUATION.md §4).

All four are computed from the same two inputs — a ranked list of returned IDs and a set of
relevant IDs — so one function does the accounting and the suite just calls it per query and
averages. Relevance here is binary (relevant / not), which matches how the labelled dataset is
built; nDCG degrades gracefully to a binary-gain form in that case rather than needing graded
judgments the dataset does not have.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryMetrics:
    query_id: str
    recall_at_k: dict[int, float]
    precision_at_5: float
    mrr: float
    ndcg_at_10: float
    returned: list[str] = field(default_factory=list)
    relevant: set[str] = field(default_factory=set)

    @property
    def hit(self) -> bool:
        """At least one relevant document was returned at all."""
        return bool(set(self.returned) & self.relevant)


def evaluate_query(
    returned: list[str], relevant: set[str], *, k_values: tuple[int, ...] = (5, 10, 20)
) -> QueryMetrics:
    if not relevant:
        raise ValueError("a query with no labelled relevant documents cannot be scored")

    recall_at_k = {}
    for k in k_values:
        top_k = set(returned[:k])
        recall_at_k[k] = len(top_k & relevant) / len(relevant)

    top_5 = returned[:5]
    precision_at_5 = sum(1 for doc_id in top_5 if doc_id in relevant) / len(top_5) if top_5 else 0.0

    mrr = 0.0
    for rank, doc_id in enumerate(returned, start=1):
        if doc_id in relevant:
            mrr = 1.0 / rank
            break

    ndcg = _ndcg_at_k(returned, relevant, k=10)

    return QueryMetrics(
        query_id="",
        recall_at_k=recall_at_k,
        precision_at_5=precision_at_5,
        mrr=mrr,
        ndcg_at_10=ndcg,
        returned=returned,
        relevant=relevant,
    )


def _ndcg_at_k(returned: list[str], relevant: set[str], *, k: int) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, doc_id in enumerate(returned[:k], start=1)
        if doc_id in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


@dataclass
class RetrievalReport:
    per_query: list[QueryMetrics] = field(default_factory=list)

    def add(self, query_id: str, metrics: QueryMetrics) -> None:
        self.per_query.append(
            QueryMetrics(
                query_id=query_id,
                recall_at_k=metrics.recall_at_k,
                precision_at_5=metrics.precision_at_5,
                mrr=metrics.mrr,
                ndcg_at_10=metrics.ndcg_at_10,
                returned=metrics.returned,
                relevant=metrics.relevant,
            )
        )

    def _mean(self, extract) -> float:  # type: ignore[no-untyped-def]
        values = [extract(m) for m in self.per_query]
        return sum(values) / len(values) if values else 0.0

    def recall_at(self, k: int) -> float:
        return self._mean(lambda m: m.recall_at_k.get(k, 0.0))

    @property
    def precision_at_5(self) -> float:
        return self._mean(lambda m: m.precision_at_5)

    @property
    def mrr(self) -> float:
        return self._mean(lambda m: m.mrr)

    @property
    def ndcg_at_10(self) -> float:
        return self._mean(lambda m: m.ndcg_at_10)

    @property
    def hit_rate(self) -> float:
        return self._mean(lambda m: float(m.hit))

    def summary(self) -> dict[str, float]:
        return {
            "recall@5": round(self.recall_at(5), 4),
            "recall@10": round(self.recall_at(10), 4),
            "precision@5": round(self.precision_at_5, 4),
            "mrr": round(self.mrr, 4),
            "ndcg@10": round(self.ndcg_at_10, 4),
            "hit_rate": round(self.hit_rate, 4),
            "queries": len(self.per_query),
        }

    def render(self) -> str:
        lines = [
            f"{'metric':14s} {'value':>7s}",
            "-" * 22,
        ]
        for label, value in self.summary().items():
            if label == "queries":
                continue
            lines.append(f"{label:14s} {value:7.3f}")
        lines.append(f"{'queries':14s} {self.summary()['queries']:7d}")
        return "\n".join(lines)
