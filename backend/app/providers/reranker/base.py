"""Reranker interface (ADR-0007).

Reranking is flag-gated and off by default in the voice path: a 568M cross-encoder over 40
candidates on CPU does not fit a 200 ms retrieval budget. `NoopReranker` is therefore the default
and the honest baseline, not a placeholder to be replaced silently.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass

from app.providers.base import ProviderInfo


@dataclass(frozen=True)
class RerankCandidate:
    id: str
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class RerankResult:
    id: str
    score: float
    rank: int


class RerankerProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    @abc.abstractmethod
    def reranks(self) -> bool:
        """False for the no-op, so callers and telemetry can tell a real rerank from a pass-through
        instead of inferring it from timings."""

    @abc.abstractmethod
    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int | None = None
    ) -> list[RerankResult]:
        """Score and reorder candidates."""


class NoopReranker(RerankerProvider):
    """Preserves the fused ordering.

    The default in the voice path until measurement earns a change (ADR-0007).
    """

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="reranker", name="noop", model="none")

    @property
    def reranks(self) -> bool:
        return False

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_k: int | None = None
    ) -> list[RerankResult]:
        selected = list(candidates)[: top_k or len(candidates)]
        return [
            RerankResult(id=c.id, score=c.score, rank=index) for index, c in enumerate(selected)
        ]
