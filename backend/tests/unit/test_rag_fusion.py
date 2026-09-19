"""Reciprocal Rank Fusion (ADR-0005)."""

from __future__ import annotations

import pytest

from app.rag.fusion import RankedItem, reciprocal_rank_fusion


def test_a_document_in_both_rankings_outranks_one_in_only_one() -> None:
    vector = [RankedItem("a", 0.9), RankedItem("b", 0.8), RankedItem("c", 0.7)]
    lexical = [RankedItem("b", 5.0), RankedItem("d", 4.0)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": lexical})
    assert fused[0].id == "b", "appearing in both rankings must win over appearing in just one"


def test_rrf_ignores_the_raw_score_scale() -> None:
    """The whole point of RRF: cosine similarity (bounded) and ts_rank_cd (unbounded) are not
    comparable scales, so only rank should matter, never the score magnitude."""
    vector = [RankedItem("a", 0.99999)]
    lexical = [RankedItem("b", 1_000_000.0)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": lexical})
    # Both are rank-1 in their own ranking, so they must score identically despite wildly
    # different raw scores.
    assert fused[0].rrf_score == pytest.approx(fused[1].rrf_score)


def test_source_ranks_are_recorded_for_explainability() -> None:
    vector = [RankedItem("a", 0.9), RankedItem("b", 0.8)]
    lexical = [RankedItem("b", 5.0)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": lexical})
    by_id = {item.id: item for item in fused}
    assert by_id["a"].source_ranks == {"vector": 1}
    assert by_id["b"].source_ranks == {"vector": 2, "lexical": 1}


def test_an_empty_ranking_is_tolerated() -> None:
    """An ablation with one arm disabled fuses an empty ranking with a real one."""
    vector = [RankedItem("a", 0.9)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": []})
    assert [item.id for item in fused] == ["a"]


def test_both_empty_returns_nothing() -> None:
    assert reciprocal_rank_fusion({"vector": [], "lexical": []}) == []


def test_limit_truncates_the_fused_list() -> None:
    vector = [RankedItem(str(i), 1.0 - i * 0.01) for i in range(10)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": []}, limit=3)
    assert len(fused) == 3


def test_results_are_sorted_best_first() -> None:
    vector = [RankedItem("c", 0.5), RankedItem("a", 0.9), RankedItem("b", 0.7)]
    fused = reciprocal_rank_fusion({"vector": vector, "lexical": []})
    scores = [item.rrf_score for item in fused]
    assert scores == sorted(scores, reverse=True)
    assert [item.id for item in fused] == ["c", "a", "b"], (
        "rank in the source list matters, not the score value — RRF fuses ranks"
    )


def test_three_rankings_fuse_the_same_way_as_two() -> None:
    """Nothing in RRF assumes exactly two arms; a third retrieval source needs no code change."""
    a = [RankedItem("x", 1.0)]
    b = [RankedItem("x", 1.0)]
    c = [RankedItem("y", 1.0)]
    fused = reciprocal_rank_fusion({"a": a, "b": b, "c": c})
    assert fused[0].id == "x", "appearing in two of three rankings must outrank appearing in one"


def test_k_is_a_smoothing_constant_not_a_hard_cutoff() -> None:
    """A very small k makes rank differences sharper; a large k flattens them. Either way, more
    rankings agreeing must still win."""
    vector = [RankedItem("a", 1.0), RankedItem("b", 0.9)]
    lexical = [RankedItem("b", 1.0), RankedItem("a", 0.9)]
    for k in (1, 60, 1000):
        fused = reciprocal_rank_fusion({"vector": vector, "lexical": lexical}, k=k)
        # a and b are symmetric (rank 1 in one list, rank 2 in the other), so they tie exactly.
        assert fused[0].rrf_score == pytest.approx(fused[1].rrf_score), k
