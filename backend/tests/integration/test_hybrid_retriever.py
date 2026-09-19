"""The hybrid retriever end to end: real pgvector, real Postgres FTS, real RRF fusion.

Uses a small fitted corpus rather than the full sample corpus, so each test's assertions are about
one specific behaviour rather than incidental facts about five lecture documents.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.retrieve import HybridRetriever, RetrievalConfig, or_tsquery


@pytest.fixture(autouse=True)
async def _clean_rag_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE document_chunks, documents RESTART IDENTITY CASCADE"))


CORPUS = [
    (
        "Kirchhoff's Laws",
        "7.1 KVL",
        "Kirchhoff's voltage law says the sum of voltages around a closed loop is zero.",
    ),
    (
        "Kirchhoff's Laws",
        "7.2 KCL",
        "Kirchhoff's current law says the sum of currents at a node is zero.",
    ),
    (
        "Maxwell's Equations",
        "12.2 Displacement current",
        "Maxwell added displacement current so Ampere's law holds for a charging capacitor gap.",
    ),
    (
        "Waveguides",
        "19.2 TE modes",
        "A rectangular waveguide's TE10 mode has the lowest cutoff frequency of any mode.",
    ),
    (
        "Transient Response",
        "11.1 Transients",
        "A transient is the temporary response before a circuit reaches steady state.",
    ),
]


async def _seed_and_fit(db_session: AsyncSession) -> TfidfSvdEmbeddingProvider:
    from sqlalchemy import select

    docs: dict[str, uuid.UUID] = {}
    next_index: dict[str, int] = {}
    for title, heading, content in CORPUS:
        if title not in docs:
            document = Document(
                title=title,
                subject="Testing",
                source_path=f"/{title}",
                source_hash=f"hash-{uuid.uuid4().hex}",
            )
            db_session.add(document)
            await db_session.flush()
            docs[title] = document.id
            next_index[title] = 0
        db_session.add(
            DocumentChunk(
                document_id=docs[title],
                chunk_index=next_index[title],
                content=content,
                heading_path=heading,
                section=heading,
            )
        )
        next_index[title] += 1
    await db_session.flush()

    rows = (await db_session.execute(select(DocumentChunk))).scalars().all()
    # The schema column is a fixed vector(256) (migration 0002); the embedder must target that
    # width so its (possibly padded) output actually fits the column.
    embeddings = TfidfSvdEmbeddingProvider(dimensions=256)
    embeddings.fit_corpus([c.content for c in rows])
    vectors = await embeddings.embed_documents([c.content for c in rows])
    for chunk, vector in zip(rows, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = embeddings.info.model
    await db_session.flush()
    await db_session.commit()
    return embeddings


async def test_a_query_matching_content_finds_the_right_chunk(db_session: AsyncSession) -> None:
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    results = await retriever.retrieve("displacement current capacitor")
    assert results
    assert results[0].document_title == "Maxwell's Equations"


async def test_results_carry_which_arms_found_them(db_session: AsyncSession) -> None:
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    results = await retriever.retrieve("Kirchhoff voltage law loop")
    top = results[0]
    assert "vector" in top.source_ranks or "lexical" in top.source_ranks


async def test_vector_arm_alone_still_returns_results(db_session: AsyncSession) -> None:
    """Ablation: each arm must be independently callable, per Gate 5's requirement."""
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    vector_only = await retriever.vector_search("waveguide cutoff frequency", RetrievalConfig())
    assert vector_only
    assert all(item.score <= 1.0 for item in vector_only)


async def test_lexical_arm_alone_finds_an_exact_term_match(db_session: AsyncSession) -> None:
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    lexical_only = await retriever.lexical_search("TE10", RetrievalConfig())
    assert lexical_only, "an exact technical term must be found by the lexical arm"


async def test_a_query_with_no_matching_terms_at_all_returns_nothing_from_the_lexical_arm(
    db_session: AsyncSession,
) -> None:
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    results = await retriever.lexical_search("zebra giraffe elephant", RetrievalConfig())
    assert results == []


async def test_a_language_filter_is_applied_to_both_arms(db_session: AsyncSession) -> None:
    embeddings = await _seed_and_fit(db_session)
    # Tag one chunk as Hindi so the filter has something to exclude.
    from sqlalchemy import select

    chunk = (await db_session.execute(select(DocumentChunk).limit(1))).scalars().first()
    chunk.language = "hi"
    await db_session.commit()

    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    config = RetrievalConfig(filters={"language": "hi"})
    results = await retriever.retrieve("Kirchhoff voltage current", config)
    assert all(r.id == str(chunk.id) for r in results) or not results


async def test_reranking_is_a_noop_by_default_and_preserves_fused_order(
    db_session: AsyncSession,
) -> None:
    """ADR-0007: the reranker must not silently change results when it declares it does not
    rerank."""
    embeddings = await _seed_and_fit(db_session)
    retriever = HybridRetriever(db_session, embeddings=embeddings, reranker=NoopReranker())
    without = await retriever.retrieve("Kirchhoff voltage law")
    config = RetrievalConfig(use_reranker=True)
    with_reranker_flag_set = await retriever.retrieve("Kirchhoff voltage law", config)
    assert [r.id for r in without] == [r.id for r in with_reranker_flag_set]


def test_or_tsquery_builds_a_valid_query_for_a_real_natural_language_question() -> None:
    assert or_tsquery("What does KVL state?") == "'what' | 'does' | 'kvl' | 'state'"


def test_or_tsquery_returns_none_for_content_free_input() -> None:
    assert or_tsquery("???") is None
