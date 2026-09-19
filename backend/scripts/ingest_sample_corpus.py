"""Ingest the self-authored sample corpus into the RAG pipeline.

    python scripts/ingest_sample_corpus.py

Ingests every document under datasets/v1/corpus/, fits the TF-IDF/SVD embedder on the whole
corpus, and writes embeddings. Idempotent: re-running skips documents already ingested by content
hash.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.session import create_engine
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.ingest import DocumentMetadata
from app.rag.service import DocumentTooShortError, RagService

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "datasets" / "v1" / "corpus"

# Metadata the ingestion pipeline does not infer from content (spec §15) — supplied here exactly
# as an admin uploading these files would supply it via POST /documents.
DOCUMENTS: list[tuple[str, DocumentMetadata]] = [
    (
        "emt-01-kirchhoffs-laws.md",
        DocumentMetadata(
            title="Kirchhoff's Laws",
            subject="Electromagnetic Theory",
            topic="Kirchhoff's Laws",
            semester=3,
            difficulty="easy",
            license="authored for this project",
        ),
    ),
    (
        "emt-02-maxwells-equations.md",
        DocumentMetadata(
            title="Maxwell's Equations",
            subject="Electromagnetic Theory",
            topic="Maxwell's Equations",
            semester=3,
            difficulty="medium",
            license="authored for this project",
        ),
    ),
    (
        "emt-03-waveguides.md",
        DocumentMetadata(
            title="Waveguides",
            subject="Electromagnetic Theory",
            topic="Waveguides",
            semester=5,
            difficulty="hard",
            license="authored for this project",
        ),
    ),
    (
        "ckt-01-network-theorems.md",
        DocumentMetadata(
            title="Network Theorems",
            subject="Circuit Theory",
            topic="Network Theorems",
            semester=3,
            difficulty="medium",
            license="authored for this project",
        ),
    ),
    (
        "ckt-02-transient-response.md",
        DocumentMetadata(
            title="Transient Response",
            subject="Circuit Theory",
            topic="Transient Response",
            semester=3,
            difficulty="medium",
            license="authored for this project",
        ),
    ),
]


async def main() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        service = RagService(
            session,
            embeddings=TfidfSvdEmbeddingProvider(),
            reranker=NoopReranker(),
        )

        ingested = skipped = 0
        for filename, metadata in DOCUMENTS:
            path = CORPUS_DIR / filename
            if not path.exists():
                print(f"missing: {path}", file=sys.stderr)
                continue
            try:
                result = await service.ingest_file(path, metadata)
            except DocumentTooShortError as exc:
                print(f"skipped {filename}: {exc}", file=sys.stderr)
                continue
            if result.already_ingested:
                print(f"already ingested: {filename}")
                skipped += 1
            else:
                print(f"ingested: {filename} ({result.chunk_count} chunks)")
                ingested += 1

        await session.commit()

        embedded = await service.fit_and_embed_all()
        await session.commit()
        print(f"\nembedded {embedded} chunks with {service.embeddings.info.model}")

    print(f"\n{ingested} ingested, {skipped} already present")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
