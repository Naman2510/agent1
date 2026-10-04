"""Reciprocal Rank Fusion (ADR-0005).

RRF rather than score normalisation: cosine similarity and Postgres's `ts_rank_cd` are not
comparable scales — one is bounded [-1, 1] by construction, the other is an unbounded
cover-density score — and there is no principled way to average them. RRF sidesteps the problem
entirely by fusing *ranks*, not scores, which needs no per-corpus tuning and no scale assumption.

    RRF(d) = sum over each ranking r that contains d of  1 / (k + rank_r(d))

`k` (60, the standard choice from the original RRF paper) discounts the exact rank so a document
ranked 1st and one ranked 3rd don't differ as sharply as their raw ranks would suggest — it is a
smoothing constant, not a scale, so no retuning is implied by using it.
"""

from __future__ import annotations

from dataclasses import dataclass

RRF_K = 60


@dataclass(frozen=True)
class RankedItem:
    id: str
    score: float


@dataclass(frozen=True)
class FusedResult:
    id: str
    rrf_score: float
    # Which rankings this id appeared in, and at what rank (1-indexed) — kept so a retrieval log
    # can show *why* a result was chosen, not just that it was (RETRIEVAL_LOGS.retriever_config).
    source_ranks: dict[str, int]


def reciprocal_rank_fusion(
    rankings: dict[str, list[RankedItem]], *, k: int = RRF_K, limit: int | None = None
) -> list[FusedResult]:
    """Fuse any number of named rankings (already sorted best-first) into one.

    Works for two rankings (vector + lexical, the current use) or more — nothing here assumes
    exactly two, so adding a third retrieval arm later needs no change here.
    """
    scores: dict[str, float] = {}
    source_ranks: dict[str, dict[str, int]] = {}

    for source, items in rankings.items():
        for rank, item in enumerate(items, start=1):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank)
            source_ranks.setdefault(item.id, {})[source] = rank

    fused = [
        FusedResult(id=doc_id, rrf_score=score, source_ranks=source_ranks[doc_id])
        for doc_id, score in scores.items()
    ]
    fused.sort(key=lambda item: item.rrf_score, reverse=True)
    return fused[:limit] if limit is not None else fused
