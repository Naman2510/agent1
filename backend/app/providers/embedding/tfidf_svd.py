"""TF-IDF + truncated SVD embeddings — the shipped substitute for `multilingual-e5-base`.

**Read `docs/adr/0006-embedding-model.md`'s 2026-09-19 update before trusting anything from this
module in a retrieval-quality argument.** The short version: the execution environment cannot
reach the Hugging Face Hub (verified — a 403 at the outbound proxy, not a guess), so the
originally-designed multilingual neural embedder cannot be fetched. This is a real, working,
decades-old technique (Latent Semantic Analysis) fit locally with scikit-learn, not a stub and not
the `FakeEmbeddingProvider` used in tests. It is also **not cross-lingual**: it is fit on one
corpus's vocabulary and script, and a Hindi-script or heavily romanized query sharing few tokens
with an English corpus will not retrieve from it. That limitation is measured, not hidden — see the
retrieval suite's per-language breakdown.

**Lifecycle, and why it differs from a pretrained model.** e5 is one model reused everywhere; this
is fit *on a specific corpus* and must be refit when the corpus changes materially. `fit_corpus`
does the fit; `embed_documents`/`embed_query` require a prior fit and raise otherwise — silently
returning zero vectors for an unfit model would produce a retrieval suite that "works" by finding
nothing distinguishable, which is worse than an explicit error.
"""

from __future__ import annotations

from collections.abc import Sequence

from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer

from app.providers.base import ProviderInfo
from app.providers.embedding.base import EmbeddingProvider
from app.rag.tokenize import tokenize

DEFAULT_DIMENSIONS = 256


class NotFittedError(RuntimeError):
    """Raised by embed_documents/embed_query before fit_corpus has run.

    An explicit error rather than a zero vector: a retriever fed zero vectors would appear to
    "work" (it returns *something*) while actually distinguishing nothing, which is a worse
    failure than a loud one.
    """


class TfidfSvdEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, dimensions: int = DEFAULT_DIMENSIONS, random_state: int = 0) -> None:
        self._dimensions = dimensions
        self._random_state = random_state
        self._pipeline: Pipeline | None = None
        self._fit_corpus_size = 0
        # The rank SVD actually achieved, which can be less than `_dimensions` on a small corpus
        # (SVD needs strictly more documents than components). `_dimensions` is the contract
        # every returned vector honours via zero-padding; `_fit_rank` is what real signal exists
        # within it — reported separately so nobody mistakes padding for learned structure.
        self._fit_rank = dimensions

    @property
    def info(self) -> ProviderInfo:
        rank_note = f"(fit_rank={self._fit_rank})" if self._fit_rank < self._dimensions else ""
        return ProviderInfo(
            kind="embedding",
            name="tfidf-svd",
            model=f"tfidf-svd-{self._dimensions}d{rank_note}"
            + (f"@{self._fit_corpus_size}docs" if self._pipeline is not None else "@unfit"),
        )

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def is_fit(self) -> bool:
        return self._pipeline is not None

    def fit_corpus(self, texts: Sequence[str]) -> None:
        """Fit TF-IDF + SVD on a corpus. Call once per ingestion batch, before embedding.

        `n_components` is capped below the corpus size: SVD cannot usefully extract more
        components than there are documents, and scikit-learn raises on that condition rather
        than silently truncating, so the cap is applied here with a clear reason.
        """
        if len(texts) < 2:
            raise ValueError(
                f"need at least 2 documents to fit TF-IDF/SVD, got {len(texts)}. "
                "A single document has no term co-occurrence structure to model."
            )
        n_components = min(self._dimensions, len(texts) - 1)
        self._fit_rank = n_components
        pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        lowercase=False,  # _tokenize already casefolds
                        # A custom tokenizer, not token_pattern: token_pattern is compiled with
                        # the standard-library `re`, which cannot express Unicode combining-mark
                        # classes. This is script-agnostic (Latin, Devanagari, Tamil) but does
                        # NOT make retrieval cross-lingual — it means a Devanagari corpus
                        # tokenizes correctly, not that a Devanagari query matches a Latin-script
                        # corpus. Those are different problems (ADR-0006's amendment).
                        tokenizer=tokenize,
                        token_pattern=None,
                        ngram_range=(1, 2),
                        min_df=1,
                        max_df=0.95,
                        sublinear_tf=True,
                    ),
                ),
                ("svd", TruncatedSVD(n_components=n_components, random_state=self._random_state)),
                # L2-normalise so cosine distance (what pgvector's HNSW index uses, per ADR-0005)
                # behaves the same as it would for a neural embedder's unit-norm output.
                ("normalize", Normalizer(copy=False)),
            ]
        )
        pipeline.fit(list(texts))
        self._pipeline = pipeline
        self._fit_corpus_size = len(texts)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        # No passage-side prefix: unlike e5, this method has no query/passage asymmetry to apply.
        # Recorded explicitly so a reader does not assume e5's contract is silently honoured.
        return self._transform(texts)

    async def embed_query(self, text: str) -> list[float]:
        return self._transform([text])[0]

    def _transform(self, texts: Sequence[str]) -> list[list[float]]:
        if self._pipeline is None:
            raise NotFittedError(
                "TfidfSvdEmbeddingProvider.fit_corpus() must run before embedding — "
                "this is a corpus-fit method, not a pretrained model"
            )
        vectors = self._pipeline.transform(list(texts))
        pad = self._dimensions - self._fit_rank
        if pad <= 0:
            return [[float(x) for x in row] for row in vectors]
        # Zero-padding to a wider column is mathematically neutral for cosine similarity — the
        # dot product and both norms are unchanged by appending zeros to every vector alike — so
        # this does not fabricate signal, it only satisfies the fixed-width pgvector column
        # (ADR-0005's stated fixed-dimension tradeoff). Found by running real ingestion: a corpus
        # small enough that SVD's rank is capped below the schema's 256 columns is exactly the
        # case this project's sample corpus hits.
        return [[float(x) for x in row] + [0.0] * pad for row in vectors]
