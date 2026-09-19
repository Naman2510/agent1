"""pgvector-backed vector store (ADR-0005).

Talks to `document_chunks` directly rather than through a generic `VectorRecord` table, because
this application has exactly one embedded table and a generic one would just be an unnecessary
indirection between this class and the schema in migration 0002.

Filtering interacts with HNSW recall (ADR-0005's stated caveat): a metadata filter is applied as a
SQL `WHERE` alongside the ANN operator, which can force a fuller scan when the filter is
selective. The retrieval suite measures recall with and without filters rather than assuming
either is free.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.base import ProviderInfo
from app.providers.vector.base import VectorMatch, VectorRecord, VectorStore


class PgVectorStore(VectorStore):
    def __init__(self, session: AsyncSession, *, embedding_model: str) -> None:
        self._session = session
        self._embedding_model = embedding_model

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="vector", name="pgvector", model=self._embedding_model)

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Write embeddings onto existing `document_chunks` rows.

        Rows are created by the ingestion pipeline (they need `content` and metadata that this
        interface does not carry); this only fills in the vector once it has been computed. `id`
        is the chunk's UUID.
        """
        count = 0
        for record in records:
            chunk = await self._session.get(DocumentChunk, record.id)
            if chunk is None:  # pragma: no cover - ingestion always creates the row first
                continue
            chunk.embedding = list(record.embedding)
            chunk.embedding_model = self._embedding_model
            count += 1
        await self._session.flush()
        return count

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        # A zero vector has no defined direction, so pgvector's cosine distance against it is
        # NaN for *every* row (verified directly: `'[0,0,0]' <=> '[1,2,3]'` returns NaN, not an
        # error). Left unchecked, Postgres still has to order those tied NaNs somehow, so
        # `ORDER BY distance` returns all rows back in an arbitrary (scan-order) sequence that
        # looks like a ranking but carries no similarity signal at all — and RRF fusion only
        # looks at rank *position*, not the NaN score, so that arbitrary order silently becomes
        # a real, non-NaN contribution to the fused result. This happens for real: a query with
        # zero vocabulary overlap with the fitted TF-IDF corpus (e.g. a pure-Devanagari query
        # against this English-only corpus, ADR-0006's amendment) embeds to exactly the zero
        # vector. Treating "no direction" as "no vector signal" and returning no matches is both
        # more correct and cheaper than querying and filtering NaNs after the fact.
        if not any(embedding):
            return []

        distance = DocumentChunk.embedding.cosine_distance(list(embedding))
        stmt = (
            select(DocumentChunk, distance.label("distance"))
            .where(DocumentChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        stmt = _apply_filters(stmt, filters)

        result = await self._session.execute(stmt)
        matches = []
        for chunk, dist in result.all():
            matches.append(
                VectorMatch(
                    id=str(chunk.id),
                    score=1.0 - float(dist),
                    metadata={
                        "document_id": str(chunk.document_id),
                        "chunk_index": chunk.chunk_index,
                        "language": chunk.language,
                        "difficulty": chunk.difficulty,
                        **chunk.metadata_,
                    },
                )
            )
        return matches


def _apply_filters(stmt: Any, filters: dict[str, Any] | None) -> Any:
    if not filters:
        return stmt
    # subject/topic live on the parent Document, not duplicated onto every chunk's metadata_
    # (that copy would drift the moment a document's subject changed) — same reasoning as
    # HybridRetriever._load_chunks's join for document_title.
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
        else:  # pragma: no cover - defensive; catches a typo'd filter key rather than ignoring it
            raise ValueError(f"unsupported filter key: {key!r}")
    return stmt
