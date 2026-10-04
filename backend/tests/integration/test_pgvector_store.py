"""The pgvector-backed vector store, against a real PostgreSQL + pgvector.

Runs real HNSW cosine search — not a mock of one — because the interesting behaviour (ranking by
actual cosine distance, metadata filtering interacting with the index) only exists in the real
database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.providers.vector.base import VectorRecord
from app.providers.vector.pgvector_store import PgVectorStore


async def _seed_chunk(
    db_session: AsyncSession,
    *,
    content: str = "content",
    language: str = "en",
    difficulty: str | None = None,
    document_id: uuid.UUID | None = None,
) -> DocumentChunk:
    if document_id is None:
        document = Document(
            title="Test Doc",
            subject="Testing",
            source_path="test.md",
            source_hash=f"hash-{uuid.uuid4().hex}",
        )
        db_session.add(document)
        await db_session.flush()
        document_id = document.id

    chunk = DocumentChunk(
        document_id=document_id,
        chunk_index=0,
        content=content,
        language=language,
        difficulty=difficulty,
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


def _unit_vector(dominant_dim: int, dims: int = 256) -> list[float]:
    vector = [0.01] * dims
    vector[dominant_dim] = 1.0
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector]


@pytest.fixture(autouse=True)
async def _clean_rag_tables(engine):  # type: ignore[no-untyped-def]
    yield
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE document_chunks, documents RESTART IDENTITY CASCADE"))


async def test_upsert_writes_the_embedding_onto_an_existing_chunk(
    db_session: AsyncSession,
) -> None:
    chunk = await _seed_chunk(db_session)
    store = PgVectorStore(db_session, embedding_model="test-model")

    count = await store.upsert([VectorRecord(id=str(chunk.id), embedding=_unit_vector(0))])
    await db_session.commit()

    assert count == 1
    refreshed = await db_session.get(DocumentChunk, chunk.id)
    assert refreshed.embedding_model == "test-model"
    assert len(refreshed.embedding) == 256


async def test_upsert_to_a_nonexistent_chunk_id_is_ignored_not_an_error(
    db_session: AsyncSession,
) -> None:
    store = PgVectorStore(db_session, embedding_model="test-model")
    count = await store.upsert([VectorRecord(id=str(uuid.uuid4()), embedding=_unit_vector(0))])
    assert count == 0


async def test_search_ranks_by_real_cosine_distance(db_session: AsyncSession) -> None:
    """The property that makes this a real vector store test, not a mock: nearest-neighbour
    ordering is computed by Postgres/pgvector, not asserted by construction."""
    close = await _seed_chunk(db_session, content="close")
    far = await _seed_chunk(db_session, content="far")
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert(
        [
            VectorRecord(id=str(close.id), embedding=_unit_vector(0)),
            VectorRecord(id=str(far.id), embedding=_unit_vector(200)),
        ]
    )
    await db_session.commit()

    # A query vector very close to `close`'s direction.
    query = _unit_vector(0)
    results = await store.search(query, limit=10)

    assert results[0].id == str(close.id)
    assert results[0].score > results[1].score
    assert results[0].score == pytest.approx(1.0, abs=0.01)


async def test_a_chunk_with_no_embedding_is_never_returned(db_session: AsyncSession) -> None:
    unembedded = await _seed_chunk(db_session, content="never embedded")
    embedded = await _seed_chunk(db_session, content="embedded")
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert([VectorRecord(id=str(embedded.id), embedding=_unit_vector(5))])
    await db_session.commit()

    results = await store.search(_unit_vector(5), limit=10)
    assert {r.id for r in results} == {str(embedded.id)}
    assert str(unembedded.id) not in {r.id for r in results}


async def test_a_language_filter_excludes_other_languages(db_session: AsyncSession) -> None:
    hindi = await _seed_chunk(db_session, content="hindi chunk", language="hi")
    english = await _seed_chunk(db_session, content="english chunk", language="en")
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert(
        [
            VectorRecord(id=str(hindi.id), embedding=_unit_vector(0)),
            VectorRecord(id=str(english.id), embedding=_unit_vector(0)),
        ]
    )
    await db_session.commit()

    results = await store.search(_unit_vector(0), limit=10, filters={"language": "hi"})
    assert {r.id for r in results} == {str(hindi.id)}


async def test_a_difficulty_filter_narrows_results(db_session: AsyncSession) -> None:
    easy = await _seed_chunk(db_session, content="easy", difficulty="easy")
    hard = await _seed_chunk(db_session, content="hard", difficulty="hard")
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert(
        [
            VectorRecord(id=str(easy.id), embedding=_unit_vector(0)),
            VectorRecord(id=str(hard.id), embedding=_unit_vector(0)),
        ]
    )
    await db_session.commit()

    results = await store.search(_unit_vector(0), limit=10, filters={"difficulty": "hard"})
    assert {r.id for r in results} == {str(hard.id)}


async def test_a_document_id_filter_restricts_to_one_document(db_session: AsyncSession) -> None:
    doc_a = Document(title="A", subject="S", source_path="/a", source_hash=f"h-{uuid.uuid4().hex}")
    doc_b = Document(title="B", subject="S", source_path="/b", source_hash=f"h-{uuid.uuid4().hex}")
    db_session.add_all([doc_a, doc_b])
    await db_session.flush()

    chunk_a = await _seed_chunk(db_session, content="in a", document_id=doc_a.id)
    chunk_b = await _seed_chunk(db_session, content="in b", document_id=doc_b.id)
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert(
        [
            VectorRecord(id=str(chunk_a.id), embedding=_unit_vector(0)),
            VectorRecord(id=str(chunk_b.id), embedding=_unit_vector(0)),
        ]
    )
    await db_session.commit()

    results = await store.search(_unit_vector(0), limit=10, filters={"document_id": doc_a.id})
    assert {r.id for r in results} == {str(chunk_a.id)}


async def test_an_unsupported_filter_key_is_rejected_rather_than_silently_ignored(
    db_session: AsyncSession,
) -> None:
    store = PgVectorStore(db_session, embedding_model="test-model")
    with pytest.raises(ValueError, match="unsupported filter key"):
        await store.search(_unit_vector(0), filters={"student_id": "should-not-exist"})


async def test_a_zero_query_vector_returns_no_matches_rather_than_nan_ranked_ones(
    db_session: AsyncSession,
) -> None:
    """A zero vector has no direction, so pgvector's cosine distance against it is NaN for every
    row — verified directly against Postgres (`'[0,0,0]' <=> '[1,2,3]'` returns NaN). Real trigger:
    a query with zero vocabulary overlap with the fitted TF-IDF corpus embeds to exactly this
    (see the Phase 5 audit's D5-06 and FC-004). Without this guard, `ORDER BY` on all-NaN
    distances still returns every row in some arbitrary order, which RRF fusion would then treat
    as a real rank."""
    chunk = await _seed_chunk(db_session, content="anything")
    store = PgVectorStore(db_session, embedding_model="test-model")
    await store.upsert([VectorRecord(id=str(chunk.id), embedding=_unit_vector(0))])
    await db_session.commit()

    zero_vector = [0.0] * 256
    results = await store.search(zero_vector, limit=10)
    assert results == []


async def test_limit_caps_the_number_of_results(db_session: AsyncSession) -> None:
    store = PgVectorStore(db_session, embedding_model="test-model")
    records = []
    for i in range(5):
        chunk = await _seed_chunk(db_session, content=f"chunk {i}")
        records.append(VectorRecord(id=str(chunk.id), embedding=_unit_vector(i)))
    await store.upsert(records)
    await db_session.commit()

    results = await store.search(_unit_vector(0), limit=2)
    assert len(results) == 2
