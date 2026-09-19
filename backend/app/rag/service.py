"""The RAG service: ingestion and retrieval against the real database.

This is the seam Phase 6's agent orchestrator calls through (`search_knowledge`). It is
deliberately *not* itself a tool — spec §12 warns against exposing raw capabilities directly to
the model — so this returns structured data, and Phase 6's tool wrapper is what the LLM actually
sees, with its own validation, authorization and logging (ARCHITECTURE §8.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, IngestStatus
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import RerankerProvider
from app.rag.chunking import embed_text
from app.rag.context import ContextBlock, build_context
from app.rag.ingest import DocumentMetadata, prepare_document
from app.rag.retrieve import HybridRetriever, RetrievalConfig, RetrievedChunk


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    chunk_count: int
    already_ingested: bool


class DocumentTooShortError(ValueError):
    """A document with too few chunks to fit the embedder (needs >= 2 for SVD)."""


class RagService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embeddings: TfidfSvdEmbeddingProvider,
        reranker: RerankerProvider,
    ) -> None:
        self._session = session
        self._embeddings = embeddings
        self._reranker = reranker

    @property
    def embeddings(self) -> TfidfSvdEmbeddingProvider:
        """Exposed read-only so callers (scripts, the eval suite) can report which embedder and
        fit produced a given search — the provenance every metric in this project requires."""
        return self._embeddings

    # --- ingestion -----------------------------------------------------

    async def ingest_file(self, path: Path, metadata: DocumentMetadata) -> IngestResult:
        """Ingest one file. Idempotent on content hash (DATA_MODEL.md §5)."""
        prepared = prepare_document(path, metadata)

        existing = await self._session.execute(
            select(Document).where(Document.source_hash == prepared.source_hash)
        )
        if (row := existing.scalar_one_or_none()) is not None:
            return IngestResult(document_id=row.id, chunk_count=0, already_ingested=True)

        if len(prepared.chunks) < 2:
            raise DocumentTooShortError(
                f"{path.name} produced {len(prepared.chunks)} chunk(s); "
                "at least 2 are needed for the corpus-fit embedder to have anything to model"
            )

        document = Document(
            title=metadata.title,
            subject=metadata.subject,
            topic=metadata.topic,
            semester=metadata.semester,
            language=metadata.language,
            source_path=str(path),
            source_hash=prepared.source_hash,
            license=metadata.license,
            page_count=None,
            ingest_status=IngestStatus.PARSING,
        )
        self._session.add(document)
        await self._session.flush()

        rows = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=prepared_chunk.chunk.content,
                heading_path=prepared_chunk.chunk.heading_path,
                token_count=prepared_chunk.chunk.token_count,
                section=prepared_chunk.chunk.section,
                difficulty=prepared_chunk.difficulty,
                language=prepared_chunk.language,
            )
            for index, prepared_chunk in enumerate(prepared.chunks)
        ]
        self._session.add_all(rows)
        await self._session.flush()

        document.ingest_status = IngestStatus.EMBEDDING
        document.ingested_at = datetime.now(UTC)
        await self._session.flush()

        return IngestResult(
            document_id=document.id, chunk_count=len(rows), already_ingested=False
        )

    async def fit_and_embed_all(self) -> int:
        """Fit the embedder on every chunk in the corpus and write embeddings back.

        A batch step rather than per-document, because TF-IDF/SVD is a corpus-fit method (unlike
        a pretrained model): adding one document should refit against the whole corpus, not embed
        the new document against a stale fit. Called once after a batch of `ingest_file` calls.
        """
        result = await self._session.execute(select(DocumentChunk))
        chunks = list(result.scalars().all())
        if len(chunks) < 2:
            return 0

        texts = [embed_text_from_row(chunk) for chunk in chunks]
        self._embeddings.fit_corpus(texts)
        vectors = await self._embeddings.embed_documents(texts)

        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = self._embeddings.info.model

        document_ids = {chunk.document_id for chunk in chunks}
        documents = await self._session.execute(
            select(Document).where(Document.id.in_(document_ids))
        )
        for document in documents.scalars():
            document.ingest_status = IngestStatus.READY

        await self._session.flush()
        return len(chunks)

    # --- retrieval -------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        use_reranker: bool = False,
        citation_start_index: int = 1,
    ) -> tuple[list[RetrievedChunk], ContextBlock]:
        if not self._embeddings.is_fit:
            # A query against an empty or unembedded corpus is not an error — it is "nothing to
            # find yet" — but it must be explicit rather than a confusing empty result further up.
            return [], ContextBlock(text="", sources={})

        retriever = HybridRetriever(
            self._session, embeddings=self._embeddings, reranker=self._reranker
        )
        config = RetrievalConfig(filters=filters or {}, use_reranker=use_reranker)
        chunks = await retriever.retrieve(query, config)
        return chunks, build_context(chunks, start_index=citation_start_index)


def embed_text_from_row(chunk: DocumentChunk) -> str:
    """Adapts a persisted chunk row to `chunking.embed_text`'s `Chunk` shape."""
    from app.rag.chunking import Chunk as ChunkDTO

    return embed_text(
        ChunkDTO(
            content=chunk.content,
            heading_path=chunk.heading_path or "",
            section=chunk.section,
            token_count=chunk.token_count or 0,
        )
    )
