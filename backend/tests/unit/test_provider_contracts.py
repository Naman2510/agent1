"""Interface contracts, checked against every implementation we have.

The point of these boundaries is that an adapter can be swapped without touching application code
(ADR-0016). A contract test is how that stays true as adapters are added.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.core.config import Settings
from app.providers.base import Capability, ProviderInfo
from app.providers.embedding.base import EmbeddingProvider
from app.providers.embedding.fake import FakeEmbeddingProvider
from app.providers.llm.anthropic_provider import AnthropicLLMProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.fake import FakeLLMProvider
from app.providers.registry import (
    UnknownProviderError,
    build_embedding,
    build_llm,
    build_reranker,
    build_stt,
    build_tts,
)
from app.providers.reranker.base import NoopReranker, RerankCandidate, RerankerProvider
from app.providers.stt.base import FinalTranscript, PartialTranscript, STTProvider
from app.providers.stt.fake import FakeSTTProvider
from app.providers.tts.base import SynthesisRequest, TTSProvider
from app.providers.tts.fake import FakeTTSProvider

LLM_IMPLEMENTATIONS = [FakeLLMProvider, AnthropicLLMProvider]


@pytest.mark.parametrize(
    ("interface", "implementation"),
    [
        (LLMProvider, FakeLLMProvider),
        (LLMProvider, AnthropicLLMProvider),
        (STTProvider, FakeSTTProvider),
        (TTSProvider, FakeTTSProvider),
        (EmbeddingProvider, FakeEmbeddingProvider),
        (RerankerProvider, NoopReranker),
    ],
)
def test_implementations_satisfy_their_interface(interface: type, implementation: type) -> None:
    assert issubclass(implementation, interface)
    abstract = getattr(interface, "__abstractmethods__", frozenset())
    unimplemented = [name for name in abstract if getattr(implementation, name, None) is None]
    assert not unimplemented


@pytest.mark.parametrize("implementation", LLM_IMPLEMENTATIONS)
def test_llm_stream_is_an_async_generator_so_cancellation_propagates(
    implementation: type,
) -> None:
    """Barge-in aborts generation mid-flight; a coroutine returning a list could not be stopped."""
    assert inspect.isasyncgenfunction(implementation.stream)


@pytest.mark.parametrize("implementation", LLM_IMPLEMENTATIONS)
def test_llm_reports_provider_identity(implementation: type) -> None:
    """Every metric must be attributable to the exact thing that produced it."""
    assert "info" in dir(implementation)


def test_provider_info_serialises_for_telemetry() -> None:
    info = ProviderInfo(
        kind="llm",
        name="anthropic",
        model="claude-opus-5",
        capabilities=frozenset({Capability.TOOL_CALLING, Capability.PROMPT_CACHING}),
    )
    assert info.as_dict() == {
        "kind": "llm",
        "name": "anthropic",
        "model": "claude-opus-5",
        "capabilities": ["prompt_caching", "tool_calling"],
    }
    assert info.supports(Capability.TOOL_CALLING)
    assert not info.supports(Capability.TRUE_STREAMING)


# --- registry ---------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "jwt_secret": "x" * 32,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_the_registry_selects_by_configuration_alone() -> None:
    assert build_llm(_settings(llm_provider="fake")).info.name == "fake"
    assert build_stt(_settings()).info.name == "fake"
    assert build_tts(_settings()).info.name == "fake"
    # tfidf_svd, not fake: it is the shipped, working substitute for multilingual-e5-base
    # (ADR-0006's amendment), so search_knowledge does real retrieval by default rather than
    # needing an env var set to leave a meaningless fake behind (Phase 6).
    assert build_embedding(_settings()).info.name == "tfidf-svd"
    assert build_embedding(_settings(embedding_provider="fake")).info.name == "fake"
    assert build_reranker(_settings()).info.name == "noop"


def test_the_registry_passes_the_configured_model_through() -> None:
    provider = build_llm(_settings(llm_provider="anthropic", llm_model="claude-sonnet-5"))
    assert provider.info.model == "claude-sonnet-5"
    assert provider.info.name == "anthropic"


def test_an_unknown_provider_fails_loudly() -> None:
    """Silently serving a fake in something that looks like production is the worse failure."""
    with pytest.raises(UnknownProviderError, match="unknown stt provider"):
        build_stt(_settings().model_copy(update={"stt_provider": "whisper-cloud"}))


# --- other providers' behaviour --------------------------------------------


async def test_the_fake_embedder_applies_asymmetric_prefixes() -> None:
    """e5 needs query:/passage: prefixes, and the provider owns applying them (R-18)."""
    provider = FakeEmbeddingProvider()
    document = (await provider.embed_documents(["Maxwell's equations"]))[0]
    query = await provider.embed_query("Maxwell's equations")
    assert document != query, "identical text must embed differently on each side"
    assert provider.document_prefixes == ["passage: "]
    assert provider.query_prefixes == ["query: "]


async def test_embeddings_are_deterministic_and_normalised() -> None:
    provider = FakeEmbeddingProvider()
    first = await provider.embed_query("KVL")
    second = await provider.embed_query("KVL")
    assert first == second
    assert len(first) == provider.dimensions
    assert sum(v * v for v in first) == pytest.approx(1.0, abs=1e-9)


async def test_the_noop_reranker_declares_that_it_does_not_rerank() -> None:
    """So telemetry can distinguish a real rerank from a pass-through instead of guessing."""
    reranker = NoopReranker()
    assert reranker.reranks is False

    candidates = [RerankCandidate(id=f"c{i}", text="x", score=1.0 - i / 10) for i in range(5)]
    results = await reranker.rerank("query", candidates, top_k=3)
    assert [r.id for r in results] == ["c0", "c1", "c2"]
    assert [r.rank for r in results] == [0, 1, 2]


async def test_the_fake_stt_emits_partials_then_exactly_one_final() -> None:
    provider = FakeSTTProvider()

    async def frames():  # type: ignore[no-untyped-def]
        for _ in range(50):
            yield b"\x00" * 640

    events = [e async for e in provider.transcribe_stream(frames())]
    assert sum(isinstance(e, FinalTranscript) for e in events) == 1
    assert isinstance(events[-1], FinalTranscript)
    partials = [e for e in events if isinstance(e, PartialTranscript)]
    assert partials
    # Partials are explicitly unstable; the stable prefix is a subset of the text.
    for partial in partials:
        assert 0 <= partial.stable_prefix_chars <= len(partial.text)


async def test_the_fake_tts_streams_audio_proportional_to_text_length() -> None:
    provider = FakeTTSProvider()
    voice = provider.voices()[0]
    short = b"".join(
        [c async for c in provider.synthesize_stream(SynthesisRequest(text="Hi.", voice=voice))]
    )
    long = b"".join(
        [
            c
            async for c in provider.synthesize_stream(
                SynthesisRequest(text="Hi. " * 40, voice=voice)
            )
        ]
    )
    assert len(long) > len(short)


def test_tts_voices_record_the_exact_provider_model() -> None:
    """ "Indian accent" is never claimed from a label; the provider and model id are."""
    for voice in FakeTTSProvider().voices():
        assert voice.provider_model
        assert voice.language
