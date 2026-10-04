"""Embedding interface (ADR-0006).

The e5 family requires `"query: "` / `"passage: "` prefixes. Applying them is the *provider's*
job, never the caller's: omitting them, or mismatching them between ingestion and query time,
degrades retrieval with no error and no log line (R-18).
"""

from __future__ import annotations

import abc
from collections.abc import Sequence

from app.providers.base import ProviderInfo


class EmbeddingProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    @abc.abstractmethod
    def dimensions(self) -> int: ...

    @abc.abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus passages. Applies the passage-side prefix if the model needs one."""

    @abc.abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Applies the query-side prefix if the model needs one."""
