"""RagService end to end: ingest a real file, fit, embed, search — against real pgvector.

This is the seam Phase 6's `search_knowledge` tool calls through, so it is tested as a whole
rather than only through its parts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, IngestStatus
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.context import extract_cited_refs, resolve_citations
from app.rag.ingest import DocumentMetadata
from app.rag.service import DocumentTooShortError, RagService


@pytest.fixture(autouse=True)
async def _clean_rag_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE document_chunks, documents RESTART IDENTITY CASCADE"))


def _write_doc(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


SAMPLE_A = """\
# Unit 3

## 7.1 KVL

Kirchhoff's voltage law says the sum of voltages around a closed loop is zero.

## 7.2 KCL

Kirchhoff's current law says the sum of currents at a node is zero.

## 7.3 Worked example

A loop with a 12 volt source and two resistors in series carries a current found by KVL.
"""

SAMPLE_B = """\
# Unit 5

## 12.1 The equations

Maxwell's four equations describe electric and magnetic fields.

## 12.2 Displacement current

Maxwell added displacement current so Ampere's law holds for a charging capacitor gap.
"""


def _service(session: AsyncSession) -> RagService:
    return RagService(
        session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker()
    )


async def test_ingesting_a_real_file_creates_a_document_and_its_chunks(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = _write_doc(tmp_path, "kvl.md", SAMPLE_A)
    service = _service(db_session)
    result = await service.ingest_file(
        path, DocumentMetadata(title="KVL", subject="EMT", difficulty="easy")
    )
    await db_session.commit()

    assert result.already_ingested is False
    assert result.chunk_count == 3

    document = await db_session.get(Document, result.document_id)
    assert document is not None
    assert document.title == "KVL"
    assert document.ingest_status is IngestStatus.EMBEDDING  # not READY until fit_and_embed_all

    chunks = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == result.document_id)
        )
    ).scalars().all()
    assert len(chunks) == 3
    assert all(c.difficulty == "easy" for c in chunks)


async def test_re_ingesting_the_same_file_is_idempotent(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = _write_doc(tmp_path, "kvl.md", SAMPLE_A)
    service = _service(db_session)
    metadata = DocumentMetadata(title="KVL", subject="EMT")

    first = await service.ingest_file(path, metadata)
    await db_session.commit()
    second = await service.ingest_file(path, metadata)
    await db_session.commit()

    assert first.already_ingested is False
    assert second.already_ingested is True
    assert second.document_id == first.document_id

    count = (
        await db_session.execute(select(func.count()).select_from(Document))
    ).scalar_one()
    assert count == 1, "re-ingesting must not create a duplicate document"


async def test_a_document_producing_fewer_than_two_chunks_is_rejected(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = _write_doc(tmp_path, "tiny.md", "Just one short paragraph, no headings at all.")
    service = _service(db_session)
    with pytest.raises(DocumentTooShortError):
        await service.ingest_file(path, DocumentMetadata(title="Tiny", subject="EMT"))


async def test_fit_and_embed_all_marks_documents_ready(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    service = _service(db_session)
    await service.ingest_file(
        _write_doc(tmp_path, "a.md", SAMPLE_A), DocumentMetadata(title="A", subject="EMT")
    )
    await service.ingest_file(
        _write_doc(tmp_path, "b.md", SAMPLE_B), DocumentMetadata(title="B", subject="EMT")
    )
    await db_session.commit()

    embedded = await service.fit_and_embed_all()
    await db_session.commit()

    assert embedded == 5  # SAMPLE_A has 3 subsections, SAMPLE_B has 2
    documents = (await db_session.execute(select(Document))).scalars().all()
    assert all(d.ingest_status is IngestStatus.READY for d in documents)

    chunks = (await db_session.execute(select(DocumentChunk))).scalars().all()
    assert all(c.embedding is not None for c in chunks)
    assert all(c.embedding_model == service.embeddings.info.model for c in chunks)


async def test_searching_before_any_fit_returns_empty_not_an_error(
    db_session: AsyncSession,
) -> None:
    service = _service(db_session)
    chunks, context = await service.search("anything")
    assert chunks == []
    assert context.is_empty


async def test_search_after_ingestion_finds_the_right_document(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    service = _service(db_session)
    await service.ingest_file(
        _write_doc(tmp_path, "a.md", SAMPLE_A),
        DocumentMetadata(title="Kirchhoff's Laws", subject="EMT"),
    )
    await service.ingest_file(
        _write_doc(tmp_path, "b.md", SAMPLE_B),
        DocumentMetadata(title="Maxwell's Equations", subject="EMT"),
    )
    await db_session.commit()
    await service.fit_and_embed_all()
    await db_session.commit()

    chunks, context = await service.search("displacement current capacitor gap")
    assert chunks
    assert chunks[0].document_title == "Maxwell's Equations"
    assert not context.is_empty
    assert "[1]" in context.text


async def test_a_metadata_filter_excludes_the_other_subject(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    service = _service(db_session)
    await service.ingest_file(
        _write_doc(tmp_path, "a.md", SAMPLE_A),
        DocumentMetadata(title="Kirchhoff's Laws", subject="Circuit Theory"),
    )
    await service.ingest_file(
        _write_doc(tmp_path, "b.md", SAMPLE_B),
        DocumentMetadata(title="Maxwell's Equations", subject="Electromagnetic Theory"),
    )
    await db_session.commit()
    await service.fit_and_embed_all()
    await db_session.commit()

    chunks, _ = await service.search(
        "Kirchhoff voltage current", filters={"subject": "Electromagnetic Theory"}
    )
    assert all(c.document_title != "Kirchhoff's Laws" for c in chunks)


async def test_the_full_pipeline_cannot_be_made_to_cite_a_source_it_never_retrieved(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The end-to-end version of the citation-fabrication guarantee (spec §16): even with a real
    ingested corpus and real retrieval, a reference number the model invents does not resolve."""
    service = _service(db_session)
    await service.ingest_file(
        _write_doc(tmp_path, "a.md", SAMPLE_A), DocumentMetadata(title="KVL Doc", subject="EMT")
    )
    await service.ingest_file(
        _write_doc(tmp_path, "b.md", SAMPLE_B),
        DocumentMetadata(title="Maxwell Doc", subject="EMT"),
    )
    await db_session.commit()
    await service.fit_and_embed_all()
    await db_session.commit()

    _, context = await service.search("Kirchhoff voltage law")
    fabricated_answer = "The answer is here [1], and also here [1] and here [77]."
    refs = extract_cited_refs(fabricated_answer)
    citations = resolve_citations(refs, context)

    assert all(c.ref != "[77]" for c in citations)
    assert len(citations) <= len(context.sources)
