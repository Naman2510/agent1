"""Retrieval evaluation: the ablation grid required by Gate 5.

Runs the same labelled queries through four configurations — vector-only, lexical-only,
hybrid (RRF), and hybrid+reranker — against the real, already-ingested corpus in the database.
This suite needs a live PostgreSQL with pgvector and the sample corpus loaded
(`scripts/ingest_sample_corpus.py`); it is not a pure-Python suite like `lid`, which is why it is
not in CI tier T1 alongside it (EVALUATION.md §6 places it in T2).

**A fifth row, `lexical_bm25_offline`, is not a retrieval configuration this system runs.** It
rescores the same queries with a real BM25 implementation (`rank_bm25`) purely to quantify the gap
between it and the shipped `ts_rank_cd` lexical arm — a gap ADR-0005 predicted and this suite
measures directly, with a concrete case (see the Phase 5 audit's "state vs kvl" example).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.chunking import embed_text
from app.rag.retrieve import HybridRetriever, RetrievalConfig
from app.rag.tokenize import tokenize
from eval.metrics.retrieval import RetrievalReport, evaluate_query


@dataclass(frozen=True)
class RelevanceRef:
    document: str
    heading_contains: str


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    query: str
    language: str
    difficulty: str
    relevant: list[RelevanceRef]
    filters: dict[str, Any] | None = None
    note: str | None = None


def load_cases(path: Path) -> list[RetrievalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            RetrievalCase(
                id=row["id"],
                query=row["query"],
                language=row["language"],
                difficulty=row["difficulty"],
                relevant=[RelevanceRef(**r) for r in row["relevant"]],
                filters=row.get("filters"),
                note=row.get("note"),
            )
        )
    return cases


async def _resolve_relevant_ids(session: AsyncSession, refs: list[RelevanceRef]) -> set[str]:
    """Turn a (document title, heading substring) reference into real chunk UUIDs.

    The dataset references chunks this way rather than by UUID because UUIDs are generated at
    ingest time and would have to be re-captured every time the corpus is re-ingested — a
    human-readable reference is what an annotator can actually write and verify by eye.
    """
    ids: set[str] = set()
    for ref in refs:
        stmt = (
            select(DocumentChunk.id)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.title == ref.document)
            .where(DocumentChunk.heading_path.contains(ref.heading_contains))
        )
        result = await session.execute(stmt)
        found = [str(row[0]) for row in result.all()]
        if not found:
            raise ValueError(
                f"no chunk found for {ref.document!r} containing {ref.heading_contains!r} — "
                "the dataset reference does not match the ingested corpus"
            )
        ids.update(found)
    return ids


async def run_config(
    session: AsyncSession,
    cases: list[RetrievalCase],
    *,
    embeddings: TfidfSvdEmbeddingProvider,
    use_vector: bool,
    use_lexical: bool,
    use_reranker: bool = False,
) -> RetrievalReport:
    """Run one ablation configuration. Disabling an arm means fusing it with an empty ranking,
    not writing a second retrieval code path — so what is measured is the real production
    retriever with an arm turned off, not a reimplementation of it."""
    retriever = HybridRetriever(session, embeddings=embeddings, reranker=NoopReranker())
    report = RetrievalReport()

    for case in cases:
        relevant = await _resolve_relevant_ids(session, case.relevant)
        config = RetrievalConfig(filters=case.filters or {})
        vector_ranking = await retriever.vector_search(case.query, config) if use_vector else []
        lexical_ranking = await retriever.lexical_search(case.query, config) if use_lexical else []

        from app.rag.fusion import reciprocal_rank_fusion

        fused = reciprocal_rank_fusion(
            {"vector": vector_ranking, "lexical": lexical_ranking}, limit=20
        )
        returned = [item.id for item in fused]
        report.add(case.id, evaluate_query(returned, relevant))

    return report


async def run_bm25_offline(
    session: AsyncSession, cases: list[RetrievalCase]
) -> RetrievalReport:
    """Real BM25 (Okapi, via `rank_bm25`), scored offline in Python against the same corpus.

    Not a candidate to replace the production lexical arm — it runs over an in-memory corpus with
    no incremental indexing story — but it is the honest reference point for "how much does IDF
    weighting matter here", which `ts_rank_cd` alone cannot answer.
    """
    result = await session.execute(
        select(DocumentChunk.id, DocumentChunk.content, DocumentChunk.document_id)
    )
    rows = result.all()
    corpus_ids = [str(r.id) for r in rows]
    tokenized_corpus = [tokenize(r.content) for r in rows]
    bm25 = BM25Okapi(tokenized_corpus)

    report = RetrievalReport()
    for case in cases:
        relevant = await _resolve_relevant_ids(session, case.relevant)
        scores = bm25.get_scores(tokenize(case.query))
        ranked = sorted(
            zip(corpus_ids, scores, strict=True), key=lambda pair: pair[1], reverse=True
        )
        returned = [doc_id for doc_id, score in ranked if score > 0][:20]
        report.add(case.id, evaluate_query(returned, relevant))

    return report


async def fit_embedder_on_corpus(
    session: AsyncSession, embeddings: TfidfSvdEmbeddingProvider
) -> None:
    """A fresh eval process has no fit; this reproduces it from what is already persisted,
    exactly as `RagService.fit_and_embed_all` does, without re-writing the embeddings."""
    result = await session.execute(select(DocumentChunk))
    chunks = list(result.scalars().all())
    texts = [
        embed_text_from_row(chunk) for chunk in chunks
    ]
    embeddings.fit_corpus(texts)


def embed_text_from_row(chunk: DocumentChunk) -> str:
    from app.rag.chunking import Chunk as ChunkDTO

    return embed_text(
        ChunkDTO(
            content=chunk.content,
            heading_path=chunk.heading_path or "",
            section=chunk.section,
            token_count=chunk.token_count or 0,
        )
    )
