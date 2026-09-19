"""The retrieval eval suite's own logic — dataset loading, reference resolution, and ablation
wiring — as distinct from `eval/metrics/retrieval.py`'s arithmetic (already covered by
`test_eval_retrieval_metrics.py`) and from the retriever it drives (`test_hybrid_retriever.py`).

Unlike `lid`, which is a pure function over text and gets a unit-test equivalent
(`test_eval_lid_suite.py`), every one of this suite's own functions takes a database session —
resolving a dataset's (document, heading) references into real chunk UUIDs is the whole point of
`_resolve_relevant_ids`, so it cannot be tested without one.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.retrieve import HybridRetriever, RetrievalConfig
from eval.suites import retrieval as retrieval_suite
from eval.suites.retrieval import RelevanceRef

CASES = Path(__file__).resolve().parents[2].parent / "datasets" / "v1" / "retrieval" / "cases.jsonl"


@pytest.fixture(autouse=True)
async def _clean_rag_tables(engine):  # type: ignore[no-untyped-def]
    yield
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE document_chunks, documents RESTART IDENTITY CASCADE"))


async def _seed(db_session: AsyncSession) -> dict[str, uuid.UUID]:
    """One document, five chunks: KVL and KCL (near-identical wording, differing on the terms the
    tests key off), plus three unrelated distractors. The distractors matter beyond filling out the
    corpus: with only 2 near-duplicate documents, classic BM25's IDF term goes *negative* for any
    word appearing in both (`log((N-n+0.5)/(n+0.5))` with N=n=2) — a real, verified small-corpus
    pathology, not a bug — which would make even a genuinely relevant chunk score below zero. Five
    chunks, with the shared vocabulary a minority, keeps IDF sane."""
    document = Document(
        title="Kirchhoff's Laws",
        subject="EMT",
        source_path="kvl.md",
        source_hash=f"hash-{uuid.uuid4().hex}",
    )
    db_session.add(document)
    await db_session.flush()

    chunks = [
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="Kirchhoff's Voltage Law states the sum of voltages around a loop is zero.",
            heading_path="7.1 KVL",
        ),
        DocumentChunk(
            document_id=document.id,
            chunk_index=1,
            content="Kirchhoff's Current Law states the sum of currents at a node is zero.",
            heading_path="7.2 KCL",
        ),
        DocumentChunk(
            document_id=document.id,
            chunk_index=2,
            content="A waveguide is a hollow metal tube that confines electromagnetic waves.",
            heading_path="19.1 Waveguides",
        ),
        DocumentChunk(
            document_id=document.id,
            chunk_index=3,
            content="The Thevenin equivalent replaces a network with one source and one resistor.",
            heading_path="9.3 Thevenin",
        ),
        DocumentChunk(
            document_id=document.id,
            chunk_index=4,
            content="A capacitor charges through a resistor with an exponential time constant.",
            heading_path="11.2 RC circuits",
        ),
    ]
    db_session.add_all(chunks)
    await db_session.flush()
    await db_session.commit()
    return {"kvl": chunks[0].id, "kcl": chunks[1].id}


# --- dataset loading ---------------------------------------------------------


def test_the_dataset_loads_and_is_well_formed() -> None:
    cases = retrieval_suite.load_cases(CASES)
    assert len(cases) >= 20
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"
    for case in cases:
        assert case.query.strip()
        assert case.language in {"en", "hi", "hi-Latn", "ta", "mixed"}
        assert case.difficulty in {"easy", "medium", "hard"}
        assert case.relevant, f"{case.id} labels no relevant chunk at all"


def test_the_dataset_includes_cross_lingual_and_filter_cases() -> None:
    """A retrieval set with only same-language, unfiltered queries would never exercise the
    embedder's cross-lingual gap (FC-004) or the metadata-filter code path (Phase 5 audit D5-05)."""
    cases = retrieval_suite.load_cases(CASES)
    assert any(c.language == "hi" for c in cases), "cross-lingual coverage must be represented"
    assert any(c.filters for c in cases), "metadata-filter coverage must be represented"


def test_case_ids_are_stable_json() -> None:
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            assert "id" in row and "query" in row and "relevant" in row


# --- reference resolution ----------------------------------------------------


async def test_resolve_relevant_ids_finds_real_chunk_uuids(db_session: AsyncSession) -> None:
    ids = await _seed(db_session)
    resolved = await retrieval_suite._resolve_relevant_ids(
        db_session, [RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.1")]
    )
    assert resolved == {str(ids["kvl"])}


async def test_resolve_relevant_ids_unions_multiple_refs(db_session: AsyncSession) -> None:
    ids = await _seed(db_session)
    resolved = await retrieval_suite._resolve_relevant_ids(
        db_session,
        [
            RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.1"),
            RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.2"),
        ],
    )
    assert resolved == {str(ids["kvl"]), str(ids["kcl"])}


async def test_resolve_relevant_ids_raises_for_a_reference_the_corpus_does_not_match(
    db_session: AsyncSession,
) -> None:
    """A dataset reference that no longer matches the ingested corpus (e.g. the corpus was
    re-authored without updating the dataset) must fail loudly — silently resolving to an empty
    relevant set would make every recall number for that case a false zero, not a measurement."""
    await _seed(db_session)
    with pytest.raises(ValueError, match="no chunk found"):
        await retrieval_suite._resolve_relevant_ids(
            db_session, [RelevanceRef(document="Kirchhoff's Laws", heading_contains="99.9")]
        )


# --- ablation wiring ----------------------------------------------------------


async def test_run_config_lexical_only_actually_requires_lexical_overlap(
    db_session: AsyncSession,
) -> None:
    """`use_vector=False` must genuinely disable the vector arm, not just deprioritise it — proven
    by a query whose terms appear in only one of two chunks that are otherwise near-identical."""
    await _seed(db_session)
    embeddings = TfidfSvdEmbeddingProvider()
    await retrieval_suite.fit_embedder_on_corpus(db_session, embeddings)

    # "voltage" and "loop" appear only in the KVL chunk's content, never the KCL chunk's.
    query = "voltage loop"
    kvl_case = retrieval_suite.RetrievalCase(
        id="t-kvl",
        query=query,
        language="en",
        difficulty="easy",
        relevant=[RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.1")],
    )
    kcl_case = retrieval_suite.RetrievalCase(
        id="t-kcl",
        query=query,
        language="en",
        difficulty="easy",
        relevant=[RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.2")],
    )
    kvl_report = await retrieval_suite.run_config(
        db_session, [kvl_case], embeddings=embeddings, use_vector=False, use_lexical=True
    )
    kcl_report = await retrieval_suite.run_config(
        db_session, [kcl_case], embeddings=embeddings, use_vector=False, use_lexical=True
    )
    assert kvl_report.recall_at(10) == 1.0, "the chunk sharing the query's lexemes must be found"
    assert kcl_report.recall_at(10) == 0.0, "a chunk with zero lexical overlap must not be"


async def test_run_config_with_both_arms_disabled_scores_zero_not_an_error(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session)
    embeddings = TfidfSvdEmbeddingProvider()
    await retrieval_suite.fit_embedder_on_corpus(db_session, embeddings)
    case = retrieval_suite.RetrievalCase(
        id="t-1",
        query="Kirchhoff voltage",
        language="en",
        difficulty="easy",
        relevant=[RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.1")],
    )
    report = await retrieval_suite.run_config(
        db_session, [case], embeddings=embeddings, use_vector=False, use_lexical=False
    )
    assert report.summary()["recall@10"] == 0.0


async def test_run_bm25_offline_returns_a_real_score_based_ranking(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session)
    case = retrieval_suite.RetrievalCase(
        id="t-1",
        query="Kirchhoff voltage law loop",
        language="en",
        difficulty="easy",
        relevant=[RelevanceRef(document="Kirchhoff's Laws", heading_contains="7.1")],
    )
    report = await retrieval_suite.run_bm25_offline(db_session, [case])
    assert report.summary()["queries"] == 1
    assert report.recall_at(10) == 1.0, "the only chunk sharing real vocabulary must be found"


async def test_fit_embedder_on_corpus_produces_a_usable_embedder(
    db_session: AsyncSession,
) -> None:
    """`fit_embedder_on_corpus` only fits — it deliberately does not write embeddings, because in
    the real eval CLI the corpus was already embedded by the ingestion pipeline beforehand, and
    re-embedding it would risk a fit that silently drifts from what is actually stored. This test
    reproduces that real precondition explicitly: embed and persist with one embedder (standing in
    for ingestion), then verify a *second*, freshly-constructed embedder — the eval process, which
    starts with no fit at all — reproduces a fit good enough to query against those chunks."""
    ids = await _seed(db_session)

    ingest_time_embeddings = TfidfSvdEmbeddingProvider()
    chunks = (await db_session.execute(select(DocumentChunk))).scalars().all()
    texts = [retrieval_suite.embed_text_from_row(c) for c in chunks]
    ingest_time_embeddings.fit_corpus(texts)
    vectors = await ingest_time_embeddings.embed_documents(texts)
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
    await db_session.commit()

    eval_time_embeddings = TfidfSvdEmbeddingProvider()
    assert not eval_time_embeddings.is_fit
    await retrieval_suite.fit_embedder_on_corpus(db_session, eval_time_embeddings)
    assert eval_time_embeddings.is_fit

    retriever = HybridRetriever(
        db_session, embeddings=eval_time_embeddings, reranker=NoopReranker()
    )
    results = await retriever.vector_search("Kirchhoff voltage law", RetrievalConfig())
    assert {r.id for r in results[:2]} == {str(ids["kvl"]), str(ids["kcl"])}
