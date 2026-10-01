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
from app.providers.llm.watchdog import StallGuard
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

        # Guarded: an upstream that goes quiet is given up on, not waited out (StallGuard).
        return StallGuard(
            AnthropicLLMProvider(
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                refusal_fallback_model=settings.llm_refusal_fallback_model or None,
            ),
            stall_seconds=settings.llm_stall_seconds,
        )
    raise UnknownProviderError("llm", name, ["fake", "anthropic"])


def build_stt(settings: Settings) -> STTProvider:
    if settings.stt_provider == "fake":
        return FakeSTTProvider()
    if settings.stt_provider == "faster-whisper":
        # Imported here: the production image does not install it (ADR-0015).
        from app.providers.stt.faster_whisper import FasterWhisperSTT

        return FasterWhisperSTT(settings.stt_model)
    # Failing loudly is better than silently serving a fake in something that looks like
    # production.
    raise UnknownProviderError("stt", settings.stt_provider, ["fake", "faster-whisper"])


def build_tts(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "fake":
        return FakeTTSProvider()
    if settings.tts_provider == "espeak":
        # Imported here: it loads scipy, and needs a program the production image does not install
        # (ADR-0018). Constructing it fails at startup if the program is missing.
        from app.providers.tts.espeak import EspeakTTSProvider

        return EspeakTTSProvider()
    raise UnknownProviderError("tts", settings.tts_provider, ["fake", "espeak"])


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
