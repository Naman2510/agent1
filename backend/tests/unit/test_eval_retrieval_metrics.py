"""Retrieval metric arithmetic (recall@k, precision@5, MRR, nDCG@10).

An evaluation harness that silently miscounts is worse than none (established in Phase 4's LID
suite tests) — the same standard applies here.
"""

from __future__ import annotations

import pytest

from eval.metrics.retrieval import RetrievalReport, evaluate_query


def test_a_relevant_document_at_rank_one_scores_perfectly() -> None:
    m = evaluate_query(["a", "b", "c"], {"a"})
    assert m.mrr == 1.0
    assert m.ndcg_at_10 == 1.0
    assert m.recall_at_k[5] == 1.0


def test_a_relevant_document_missing_entirely_scores_zero() -> None:
    m = evaluate_query(["x", "y", "z"], {"a"})
    assert m.mrr == 0.0
    assert m.ndcg_at_10 == 0.0
    assert m.recall_at_k[10] == 0.0
    assert m.hit is False


def test_mrr_uses_the_first_relevant_rank_only() -> None:
    m = evaluate_query(["x", "a", "y", "a"], {"a"})
    assert m.mrr == pytest.approx(1 / 2)


def test_recall_at_k_is_the_fraction_of_relevant_docs_found() -> None:
    m = evaluate_query(["a", "x", "b", "y", "z"], {"a", "b", "c"})
    assert m.recall_at_k[5] == pytest.approx(2 / 3)  # found a, b; missed c
    assert m.recall_at_k[5] < 1.0


def test_precision_at_5_counts_relevant_among_the_top_5_only() -> None:
    m = evaluate_query(["a", "x", "y", "z", "w", "b"], {"a", "b"})
    # b is at rank 6, outside top 5.
    assert m.precision_at_5 == pytest.approx(1 / 5)


def test_ndcg_rewards_earlier_ranks_more_than_later_ones() -> None:
    early = evaluate_query(["a", "x", "y"], {"a"})
    late = evaluate_query(["x", "y", "a"], {"a"})
    assert early.ndcg_at_10 > late.ndcg_at_10


def test_ndcg_at_10_ignores_hits_beyond_rank_10() -> None:
    returned = [f"d{i}" for i in range(15)]
    returned[12] = "a"  # the only relevant doc, at rank 13 — outside nDCG@10's window
    m = evaluate_query(returned, {"a"})
    assert m.ndcg_at_10 == 0.0
    assert m.recall_at_k[20] == 1.0, "but recall@20 still finds it"


def test_a_query_with_no_labelled_relevant_documents_is_rejected() -> None:
    """A labelling bug (an empty relevance set) must be loud, not silently scored as a miss."""
    with pytest.raises(ValueError, match="no labelled relevant"):
        evaluate_query(["a", "b"], set())


def test_an_empty_returned_list_scores_as_a_complete_miss() -> None:
    m = evaluate_query([], {"a"})
    assert m.mrr == 0.0
    assert m.recall_at_k[10] == 0.0


def test_report_averages_across_queries() -> None:
    report = RetrievalReport()
    report.add("q1", evaluate_query(["a"], {"a"}))  # perfect
    report.add("q2", evaluate_query(["z"], {"a"}))  # complete miss
    assert report.mrr == pytest.approx(0.5)
    assert report.hit_rate == pytest.approx(0.5)


def test_an_empty_report_does_not_divide_by_zero() -> None:
    report = RetrievalReport()
    assert report.mrr == 0.0
    assert report.recall_at(10) == 0.0
    assert report.render()


def test_summary_rounds_and_includes_the_query_count() -> None:
    report = RetrievalReport()
    report.add("q1", evaluate_query(["a"], {"a"}))
    summary = report.summary()
    assert summary["queries"] == 1
    assert summary["mrr"] == 1.0
    assert isinstance(summary["recall@5"], float)
