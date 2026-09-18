"""Deterministic, seeded embedding double.

Hash-based rather than random, so the same text always yields the same vector and retrieval tests
are reproducible without downloading a model.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from app.providers.base import ProviderInfo
from app.providers.embedding.base import EmbeddingProvider

_DIMENSIONS = 32


def _vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [
        (digest[i % len(digest)] ^ digest[(i * 7 + 3) % len(digest)]) / 255.0 - 0.5
        for i in range(_DIMENSIONS)
    ]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        self.document_prefixes: list[str] = []
        self.query_prefixes: list[str] = []

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(kind="embedding", name="fake", model="fake-embed-1")

    @property
    def dimensions(self) -> int:
        return _DIMENSIONS

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        # Mirrors e5's asymmetry so a prefix mismatch is reproducible in tests.
        self.document_prefixes.extend("passage: " for _ in texts)
        return [_vector("passage: " + text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.query_prefixes.append("query: ")
        return _vector("query: " + text)
