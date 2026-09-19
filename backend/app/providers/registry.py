"""Config-driven provider selection (ADR-0016).

Adding a provider is one adapter plus one entry here; no application code changes. That is the
property the evaluation framework depends on — a model comparison must be a config change, or it
is not a controlled experiment.
"""

from __future__ import annotations

import structlog

from app.core.config import Settings
from app.providers.embedding.base import EmbeddingProvider
from app.providers.embedding.fake import FakeEmbeddingProvider
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.fake import FakeLLMProvider
from app.providers.reranker.base import NoopReranker, RerankerProvider
from app.providers.stt.base import STTProvider
from app.providers.stt.fake import FakeSTTProvider
from app.providers.tts.base import TTSProvider
from app.providers.tts.fake import FakeTTSProvider

log = structlog.get_logger(__name__)


class UnknownProviderError(ValueError):
    def __init__(self, kind: str, name: str, known: list[str]) -> None:
        super().__init__(f"unknown {kind} provider {name!r}; known: {sorted(known)}")


def build_llm(settings: Settings) -> LLMProvider:
    name = settings.llm_provider
    if name == "fake":
        return FakeLLMProvider(model="fake-llm-1")
    if name == "anthropic":
        # Imported lazily so a deployment using the fake does not require the SDK, and so an
        # import-time credential error cannot break unrelated tests.
        from app.providers.llm.anthropic_provider import AnthropicLLMProvider

        return AnthropicLLMProvider(
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            refusal_fallback_model=settings.llm_refusal_fallback_model or None,
        )
    raise UnknownProviderError("llm", name, ["fake", "anthropic"])


def build_stt(settings: Settings) -> STTProvider:
    if settings.stt_provider == "fake":
        return FakeSTTProvider()
    # Real adapters land in Phase 3 with the voice loop. Failing loudly here is better than
    # silently serving a fake in something that looks like production.
    raise UnknownProviderError("stt", settings.stt_provider, ["fake"])


def build_tts(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "fake":
        return FakeTTSProvider()
    raise UnknownProviderError("tts", settings.tts_provider, ["fake"])


def build_embedding(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider()
    if settings.embedding_provider == "tfidf_svd":
        # The shipped substitute for multilingual-e5-base (ADR-0006's amendment): this sandbox
        # cannot reach HuggingFace Hub to fetch e5's weights. Returns unfit — the caller (app
        # startup) fits it from whatever is already persisted, or it stays unfit until an
        # ingestion + fit_and_embed_all runs, at which point RagService.search reports "not
        # found yet" rather than erroring (Phase 5).
        return TfidfSvdEmbeddingProvider()
    raise UnknownProviderError("embedding", settings.embedding_provider, ["fake", "tfidf_svd"])


def build_reranker(settings: Settings) -> RerankerProvider:
    if settings.reranker_provider in {"noop", "none", ""}:
        return NoopReranker()
    raise UnknownProviderError("reranker", settings.reranker_provider, ["noop"])
