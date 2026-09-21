"""FastAPI application factory and lifespan.

Everything shared lives on `app.state` and is created once per process: the engine, the session
factory, the Redis client, the password hasher, and the rate limiter. Dependencies read from
there, which keeps them cheap and makes overriding them in tests a one-liner.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.intent import IntentGate
from app.agent.memory_extractor import MemoryExtractor
from app.agent.tools.registry import DEFAULT_REGISTRY
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import RateLimiter
from app.core.redis import create_redis
from app.core.security import PasswordHasherService
from app.db.session import create_engine, create_session_factory
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.registry import build_llm, build_reranker
from app.rag.service import RagService
from app.services.memory_window import SessionWindowCache
from app.services.usage import UsageLedger
from app.ws.voice import router as voice_router

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
    app.state.hasher = PasswordHasherService(settings)
    app.state.rate_limiter = RateLimiter(app.state.redis, settings)
    app.state.llm = build_llm(settings)
    app.state.usage_ledger = UsageLedger(app.state.redis, settings)

    # Shared for the process lifetime, unlike a per-request RagService: TF-IDF/SVD's fit is a
    # corpus-wide computation (Phase 5), so every request reuses one fitted embedder rather than
    # refitting on every turn. A fresh process has no fit even if the database already holds real
    # embeddings from a previous ingestion — refit_from_persisted reproduces it without
    # re-embedding anything. Left unfit (not an error) if nothing has been ingested yet.
    app.state.embeddings = TfidfSvdEmbeddingProvider()
    async with app.state.session_factory() as startup_session:
        refitted = await RagService(
            startup_session, embeddings=app.state.embeddings, reranker=build_reranker(settings)
        ).refit_from_persisted()
    if refitted:
        log.info("rag.embedder_refit", chunks=refitted, model=app.state.embeddings.info.model)
    else:
        log.warning(
            "rag.embedder_unfit",
            detail="no corpus ingested yet; search_knowledge will report nothing found",
        )

    app.state.tool_registry = DEFAULT_REGISTRY
    app.state.intent_gate = IntentGate(app.state.llm)
    # Both wrap only shared, stable dependencies (the LLM, the session factory, settings), so —
    # like intent_gate above — one instance is reused across every request rather than rebuilt
    # per turn (ARCHITECTURE §12/§13).
    app.state.window_cache = SessionWindowCache(
        app.state.redis, capacity=settings.llm_history_turns, llm=app.state.llm
    )
    app.state.memory_extractor = MemoryExtractor(app.state.llm, app.state.session_factory)

    if settings.monthly_spend_cap_usd is None:
        # Gate 0 finding M-11: say plainly that nothing is capped rather than implying a limit.
        log.warning(
            "cost_guard.disabled",
            detail="VAANIOS_MONTHLY_SPEND_CAP_USD is unset; no spend ceiling is enforced",
        )
    else:
        log.info("cost_guard.enabled", cap_usd=settings.monthly_spend_cap_usd)

    log.info(
        "app.started",
        environment=settings.environment,
        rate_limiting=settings.rate_limit_enabled,
        **{
            f"provider_{k}": v
            for k, v in app.state.llm.info.as_dict().items()
            if k != "capabilities"
        },
    )
    try:
        yield
    finally:
        await app.state.llm.aclose()
        await app.state.redis.aclose()
        await app.state.engine.dispose()
        log.info("app.stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="VaaniOS API",
        version="0.1.0",
        description=(
            "Multilingual conversational AI voice mentor. Phase 1: backend foundation — "
            "no voice loop, agent, or RAG yet."
        ),
        lifespan=lifespan,
        # Interactive docs are useful in development and are attack surface in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/v1")
    app.include_router(voice_router, prefix="/v1")
    return app
