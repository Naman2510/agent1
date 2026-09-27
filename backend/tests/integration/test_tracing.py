"""Tracing through the running app (ADR-0014): a request, a typed turn, a retrieval.

The voice turn's trace is tested with the voice session (tests/integration/test_voice_session.py).
"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.ingest import DocumentMetadata
from app.rag.service import RagService


async def test_a_request_is_a_span_named_by_its_route(
    client: AsyncClient, registered, auth_headers, spans: InMemorySpanExporter
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = (await client.post("/sessions", headers=headers, json={})).json()["id"]
    spans.clear()

    response = await client.get(f"/sessions/{session_id}", headers=headers)

    assert response.status_code == 200
    [span] = [s for s in spans.get_finished_spans() if s.kind is SpanKind.SERVER]
    # The template, not the path: every session's reads group together.
    assert span.name == "GET /v1/sessions/{session_id}"
    assert span.attributes is not None
    assert span.attributes["http.route"] == "/v1/sessions/{session_id}"
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["request_id"] == response.headers["X-Request-ID"]


async def test_a_typed_turn_is_traced_inside_its_request(
    client: AsyncClient, registered, auth_headers, spans: InMemorySpanExporter
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = (await client.post("/sessions", headers=headers, json={})).json()["id"]
    spans.clear()

    response = await client.post(
        f"/sessions/{session_id}/messages", headers=headers, json={"text": "What is KVL?"}
    )
    assert response.status_code == 200
    assert "event: done" in response.text

    finished = spans.get_finished_spans()
    [request] = [s for s in finished if s.kind is SpanKind.SERVER]
    assert request.name == "POST /v1/sessions/{session_id}/messages"
    [generate] = [s for s in finished if s.name == "conversation.generate"]
    assert generate.context.trace_id == request.context.trace_id
    assert generate.attributes is not None
    assert generate.attributes["llm.model"]
    assert "llm.output_tokens" in generate.attributes


SAMPLE = """\
# Circuit laws

## Kirchhoff's voltage law

The sum of the voltages around any closed loop is zero.

## Kirchhoff's current law

The currents into a node sum to zero.
"""


async def test_a_retrieval_is_a_span_without_the_query_in_it(
    db_session: AsyncSession, tmp_path: Path, spans: InMemorySpanExporter
) -> None:
    path = tmp_path / "laws.md"
    path.write_text(SAMPLE, encoding="utf-8")
    service = RagService(
        db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker()
    )
    await service.ingest_file(path, DocumentMetadata(title="Circuit laws", subject="EMT"))
    await service.fit_and_embed_all()
    spans.clear()

    chunks, _ = await service.search("voltage around a closed loop")

    assert chunks
    [span] = [s for s in spans.get_finished_spans() if s.name == "rag.search"]
    assert span.attributes is not None
    assert span.attributes["rag.results"] == len(chunks)
    assert not any("loop" in str(v) for v in span.attributes.values())
