"""Hybrid retrieval: vector + lexical, fused by RRF, optionally reranked (ADR-0005, ADR-0007).

The lexical arm uses Postgres `ts_rank_cd` over the `simple` text-search configuration — called
"lexical" throughout this codebase, deliberately never "BM25" (Gate 0 finding M-03): cover-density
ranking and Okapi BM25 are different algorithms, and the retrieval eval suite rescores offline with
real BM25 (`rank_bm25`) wherever that comparison actually matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.embedding.base import EmbeddingProvider
from app.providers.reranker.base import RerankCandidate, RerankerProvider
from app.rag.fusion import RankedItem, reciprocal_rank_fusion
from app.rag.tokenize import tokenize


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    content: str
    heading_path: str | None
    document_id: str
    document_title: str
    page_start: int | None
    page_end: int | None
    section: str | None
    score: float
    source_ranks: dict[str, int]
    rerank_score: float | None = None


@dataclass(frozen=True)
class RetrievalConfig:
    """Recorded verbatim into `retrieval_logs.retriever_config`, so any answer is traceable to the
    configuration that produced it (ARCHITECTURE §11)."""

    vector_k: int = 20
    lexical_k: int = 20
    fused_limit: int = 10
    use_reranker: bool = False
    filters: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "vector_k": self.vector_k,
            "lexical_k": self.lexical_k,
            "fused_limit": self.fused_limit,
            "use_reranker": self.use_reranker,
            "filters": dict(self.filters),
        }


def or_tsquery(query: str) -> str | None:
    """Build a Postgres tsquery string that matches ANY term, not all of them.

    `to_tsquery` requires already-tokenised lexemes joined by explicit operators; this uses the
    shared Unicode-aware tokenizer (`app.rag.tokenize`) and joins the result with `|`. Returns
    None for a query with no word tokens at all (pure punctuation, or empty), so the caller can
    skip the lexical arm rather than send `to_tsquery` an empty string, which Postgres rejects.
    """
    tokens = tokenize(query)
    if not tokens:
        return None
    # Escaping: a token from \w+ never contains a single quote or backslash, so no escaping is
    # needed before embedding it in the tsquery string.
    return " | ".join(f"'{token}'" for token in tokens)


class HybridRetriever:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embeddings: EmbeddingProvider,
        reranker: RerankerProvider,
    ) -> None:
        self._session = session
        self._embeddings = embeddings
        self._reranker = reranker

    async def retrieve(
        self, query: str, config: RetrievalConfig | None = None
    ) -> list[RetrievedChunk]:
        cfg = config or RetrievalConfig()

        vector_ranking = await self.vector_search(query, cfg)
        lexical_ranking = await self.lexical_search(query, cfg)

        fused = reciprocal_rank_fusion(
            {"vector": vector_ranking, "lexical": lexical_ranking}, limit=cfg.fused_limit
        )
        if not fused:
            return []

        rows_by_id = await self._load_chunks([item.id for item in fused])
        ordered = [
            self._to_retrieved(*rows_by_id[item.id], item.rrf_score, item.source_ranks)
            for item in fused
            if item.id in rows_by_id
        ]

        if cfg.use_reranker and self._reranker.reranks:
            ordered = await self._apply_reranker(query, ordered)

        return ordered

    async def vector_search(self, query: str, cfg: RetrievalConfig) -> list[RankedItem]:
        """The vector arm alone. Public because ablation testing — comparing each arm in
        isolation — is a first-class use case (Gate 5), not an internal it needs."""
        from app.providers.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(self._session, embedding_model=self._embeddings.info.model)
        query_vector = await self._embeddings.embed_query(query)
        matches = await store.search(query_vector, limit=cfg.vector_k, filters=cfg.filters or None)
        return [RankedItem(id=m.id, score=m.score) for m in matches]

    async def lexical_search(self, query: str, cfg: RetrievalConfig) -> list[RankedItem]:
        """The lexical arm alone. See `vector_search` for why this is public."""
        # NOT plainto_tsquery: it ANDs every input word, including "what"/"does"/"is", so a
        # six-word natural-language question requires all six words present verbatim in a chunk
        # to match at all — found by running real queries against the real corpus, where it
        # returned zero lexical results for ordinary student questions. An OR-of-terms query,
        # ranked by how many terms match, is what a lexical retrieval arm actually needs; the
        # gap between this and true BM25 (no IDF weighting, no term-frequency saturation) is the
        # reason this arm is called "lexical" and never "BM25" (ADR-0005, Gate 0 finding M-03).
        or_query = or_tsquery(query)
        if or_query is None:
            return []
        tsquery = func.to_tsquery("simple", or_query)
        rank = func.ts_rank_cd(DocumentChunk.content_tsv, tsquery)
        stmt = (
            select(DocumentChunk.id, rank.label("rank"))
            .where(DocumentChunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(cfg.lexical_k)
        )
        stmt = self._apply_lexical_filters(stmt, cfg.filters)
        result = await self._session.execute(stmt)
        return [RankedItem(id=str(row.id), score=float(row.rank)) for row in result.all()]

    def _apply_lexical_filters(self, stmt: Any, filters: dict[str, Any]) -> Any:
        if not filters:
            return stmt
        # Mirrors PgVectorStore._apply_filters exactly, including the reject-unknown-keys
        # behaviour: a filter key silently accepted by one arm and ignored by the other is
        # exactly how subject/topic filtering broke before (the lexical arm returned every
        # document unfiltered while the vector arm alone tried to exclude one).
        if "subject" in filters or "topic" in filters:
            stmt = stmt.join(Document, DocumentChunk.document_id == Document.id)
        for key, value in filters.items():
            if key == "language":
                stmt = stmt.where(DocumentChunk.language == value)
            elif key == "difficulty":
                stmt = stmt.where(DocumentChunk.difficulty == value)
            elif key == "document_id":
                stmt = stmt.where(DocumentChunk.document_id == value)
            elif key == "subject":
                stmt = stmt.where(Document.subject == value)
            elif key == "topic":
                stmt = stmt.where(Document.topic == value)
            else:
                raise ValueError(f"unsupported filter key: {key!r}")
        return stmt

    async def _load_chunks(self, ids: list[str]) -> dict[str, tuple[DocumentChunk, Document]]:
        """Chunks joined to their parent document, so the title is real rather than duplicated
        into every chunk's metadata at ingest time (one more thing that could drift)."""
        if not ids:
            return {}
        stmt = (
            select(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.id.in_(ids))
        )
        result = await self._session.execute(stmt)
        return {str(chunk.id): (chunk, document) for chunk, document in result.all()}

    def _to_retrieved(
        self,
        chunk: DocumentChunk,
        document: Document,
        score: float,
        source_ranks: dict[str, int],
    ) -> RetrievedChunk:
        return RetrievedChunk(
            id=str(chunk.id),
            content=chunk.content,
            heading_path=chunk.heading_path,
            document_id=str(chunk.document_id),
            document_title=document.title,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
            score=score,
            source_ranks=source_ranks,
        )

    async def _apply_reranker(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        results = await self._reranker.rerank(
            query,
            [RerankCandidate(id=c.id, text=c.content, score=c.score) for c in chunks],
        )
        by_id = {c.id: c for c in chunks}
        reranked = []
        for result in results:
            original = by_id.get(result.id)
            if original is None:  # pragma: no cover - defensive; the reranker must not invent ids
                continue
            reranked.append(replace(original, rerank_score=result.score))
        return reranked
