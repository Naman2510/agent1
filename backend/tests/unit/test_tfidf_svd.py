"""The TF-IDF/SVD embedder — the shipped substitute for `multilingual-e5-base`
(docs/adr/0006-embedding-model.md's amendment).
"""

from __future__ import annotations

import math

import pytest

from app.providers.base import Capability
from app.providers.embedding.tfidf_svd import NotFittedError, TfidfSvdEmbeddingProvider

CORPUS = [
    "Kirchhoff's voltage law states the sum of voltages around a loop is zero.",
    "Kirchhoff's current law states the sum of currents at a node is zero.",
    "Maxwell added displacement current to Ampere's law for a charging capacitor.",
    "A rectangular waveguide supports TE and TM modes above their cutoff frequency.",
    "The time constant of an RC circuit is the product of resistance and capacitance.",
]


async def test_embedding_before_fitting_raises() -> None:
    provider = TfidfSvdEmbeddingProvider(dimensions=8)
    with pytest.raises(NotFittedError, match="fit_corpus"):
        await provider.embed_query("test")
    with pytest.raises(NotFittedError):
        await provider.embed_documents(["a", "b"])


def test_fitting_on_fewer_than_two_documents_raises() -> None:
    provider = TfidfSvdEmbeddingProvider(dimensions=8)
    with pytest.raises(ValueError, match="at least 2 documents"):
        provider.fit_corpus(["only one document"])


async def test_a_fit_provider_produces_vectors_of_the_configured_width() -> None:
    provider = TfidfSvdEmbeddingProvider(dimensions=8)
    provider.fit_corpus(CORPUS)
    vector = await provider.embed_query("Kirchhoff voltage law")
    assert len(vector) == 8


async def test_dimensions_are_padded_not_shrunk_when_the_corpus_is_small() -> None:
    """The defect found by running real ingestion: with fewer documents than the configured
    width, SVD's achievable rank is capped below it — the provider must still honour its
    dimensional contract by padding, not silently report a narrower vector."""
    provider = TfidfSvdEmbeddingProvider(dimensions=256)
    provider.fit_corpus(CORPUS)  # 5 documents -> max possible rank is 4
    vector = await provider.embed_query("anything")
    assert len(vector) == 256
    assert provider.dimensions == 256, "the public contract must not shrink"


async def test_padding_with_zeros_does_not_change_cosine_similarity() -> None:
    """The mathematical claim the ADR amendment makes: appending zeros to every vector alike
    changes neither the dot product nor either norm, so padding is neutral, not fabricated
    signal."""
    narrow = TfidfSvdEmbeddingProvider(dimensions=4)
    narrow.fit_corpus(CORPUS)
    wide = TfidfSvdEmbeddingProvider(dimensions=256)
    wide.fit_corpus(CORPUS)

    a_narrow = await narrow.embed_query(CORPUS[0])
    b_narrow = await narrow.embed_query(CORPUS[1])
    a_wide = await wide.embed_query(CORPUS[0])
    b_wide = await wide.embed_query(CORPUS[1])

    def cosine(x: list[float], y: list[float]) -> float:
        dot = sum(p * q for p, q in zip(x, y, strict=True))
        norm_x = math.sqrt(sum(p * p for p in x))
        norm_y = math.sqrt(sum(q * q for q in y))
        return dot / (norm_x * norm_y)

    assert cosine(a_narrow, b_narrow) == pytest.approx(cosine(a_wide, b_wide), abs=1e-9)


async def test_vectors_are_l2_normalised() -> None:
    """So cosine distance behaves the same as it would for a neural embedder's unit-norm output
    (pgvector's HNSW index uses cosine distance, per ADR-0005)."""
    provider = TfidfSvdEmbeddingProvider(dimensions=4)
    provider.fit_corpus(CORPUS)
    vector = await provider.embed_query(CORPUS[0])
    norm = math.sqrt(sum(x * x for x in vector))
    assert norm == pytest.approx(1.0, abs=1e-6)


async def test_similar_documents_are_closer_than_dissimilar_ones() -> None:
    """The property that actually matters for retrieval: the two Kirchhoff sentences should be
    more alike than either is to the waveguide sentence."""
    provider = TfidfSvdEmbeddingProvider(dimensions=4)
    provider.fit_corpus(CORPUS)
    kvl = await provider.embed_query(CORPUS[0])
    kcl = await provider.embed_query(CORPUS[1])
    waveguide = await provider.embed_query(CORPUS[3])

    def cosine(x: list[float], y: list[float]) -> float:
        return sum(p * q for p, q in zip(x, y, strict=True))  # already unit-norm

    assert cosine(kvl, kcl) > cosine(kvl, waveguide)


def test_info_reports_the_fit_rank_when_it_is_narrower_than_the_target() -> None:
    """A reader must be able to tell padded width from real learned rank from the model string
    alone — the whole reason the two are tracked separately."""
    provider = TfidfSvdEmbeddingProvider(dimensions=256)
    assert "unfit" in provider.info.model
    provider.fit_corpus(CORPUS)
    assert "fit_rank=4" in provider.info.model
    assert "256d" in provider.info.model


def test_info_omits_the_fit_rank_note_when_it_equals_the_target() -> None:
    provider = TfidfSvdEmbeddingProvider(dimensions=2)
    provider.fit_corpus(CORPUS)  # rank 4 available, only 2 requested — no padding needed
    assert "fit_rank" not in provider.info.model


async def test_there_is_no_query_passage_asymmetry_unlike_e5() -> None:
    """Documented explicitly so nobody assumes e5's prefix contract is silently honoured."""
    provider = TfidfSvdEmbeddingProvider(dimensions=4)
    provider.fit_corpus(CORPUS)
    query_vec = await provider.embed_query(CORPUS[0])
    doc_vec = (await provider.embed_documents([CORPUS[0]]))[0]
    assert query_vec == pytest.approx(doc_vec)


def test_capability_and_identity_are_reported() -> None:
    provider = TfidfSvdEmbeddingProvider()
    assert provider.info.kind == "embedding"
    assert provider.info.name == "tfidf-svd"
    assert Capability.PROMPT_CACHING not in provider.info.capabilities  # no bogus claims
