"""Vector store interface (ADR-0005).

The pgvector implementation arrives with the ingestion pipeline in Phase 5; the interface exists
now so the retriever can be written against it and so Qdrant remains a swap rather than a rewrite.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ProviderInfo


@dataclass(frozen=True)
class VectorRecord:
    id: str
    embedding: Sequence[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @abc.abstractmethod
    async def upsert(self, records: Sequence[VectorRecord]) -> int: ...

    @abc.abstractmethod
    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        """Nearest neighbours, optionally restricted by metadata.

        Filtering interacts badly with HNSW recall, so the retrieval suite measures recall with
        and without filters rather than assuming they are free.
        """
