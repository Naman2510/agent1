# ADR-0006 — `multilingual-e5-base` as the default embedding model

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Queries arrive in English, Hindi, Tamil, and romanized Hinglish; the corpus is mostly English
technical material. Cross-lingual retrieval therefore matters: a Hindi question must find English
lecture content. Embedding runs on CPU — once per chunk at ingestion (batchable) and once per query
on the latency path.

## Options considered
| Option | Dims | Notes |
|---|---|---|
| `intfloat/multilingual-e5-base` | 768 | ~278M, strong multilingual retrieval, CPU-feasible |
| `BAAI/bge-m3` | 1024 | Stronger multilingual and multi-vector, ~568M — heavier on CPU, and exceeds the 768-dim serving column |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | ~118M, fastest, weaker retrieval quality |
| Managed embedding API | varies | Removes CPU cost, adds per-query network latency and spend |

## Decision
`multilingual-e5-base` (768 dims, cosine) as the default, behind `EmbeddingProvider`. Alternatives
are config-selectable and compared as an experiment on the `retrieval` suite.

## Rationale
- Best quality-per-CPU-millisecond of the CPU-feasible options for multilingual retrieval; 768 dims
  keeps the HNSW index and row size reasonable.
- Query embedding for a short utterance is tens of milliseconds on CPU, which fits the 200 ms
  retrieval budget; a managed API would add a network round trip to the critical path for no clear
  quality gain at this corpus size.
- MiniLM is tempting for speed but the retrieval budget is not the binding constraint — stage 2 and
  stage 6 are (ARCHITECTURE §9) — so spending it on quality is the right trade.

## Tradeoffs accepted
- **E5 requires `"query: "` and `"passage: "` prefixes.** Omitting them silently degrades retrieval
  with no error — a classic invisible bug (R-18). Mitigation: the prefixes are applied *inside* the
  provider, never by callers, and a unit test asserts both are present; a mismatch between ingestion
  and query prefixing is a specific test case.
- 512-token input limit constrains chunk size, which is compatible with the 512-token chunk target.
- `bge-m3` may well be better; it is excluded for now by CPU cost and the fixed-dimension serving
  column (R-14), not by a quality judgement.

## Consequences
- `embedding_model` is stored on every chunk, so a model change is detectable and a partial
  re-embedding is impossible to confuse with a complete one.
- Query embeddings are cached in Redis keyed by `(model, sha256(text))`.
- Changing the embedding model requires re-embedding the corpus; experiments use side tables
  (DATA_MODEL §5).

## Revisit when
The retrieval suite shows a materially better model within budget, a GPU is available, or per-language
recall on Tamil/Hindi queries is unacceptable and points at the embedder rather than the lexical arm.

## Update — 2026-09-19 (Phase 5 implementation)

**What actually shipped differs from this ADR's decision, and the reason is environmental, not a
design change.**

The execution environment's outbound network policy allows PyPI and a small allowlist of API
hosts, but blocks the Hugging Face Hub and Ollama's registry (both return `403` at the proxy —
verified, not assumed: see the Phase 5 audit). `multilingual-e5-base`'s weights cannot be
downloaded from inside this environment. `torch` and `sentence-transformers` install fine from
PyPI; there is simply nothing to load once installed.

**What shipped instead:** `TfidfSvdEmbeddingProvider` — TF-IDF vectorisation followed by truncated
SVD (classical Latent Semantic Analysis), fit on the ingested corpus at ingestion time via
scikit-learn, which installs from PyPI with no blocked dependency. This is a real, decades-old,
well-documented technique — not a placeholder and not the `FakeEmbeddingProvider` used in tests.

**What is honestly different from the ADR's decision, stated plainly:**

- **No cross-lingual retrieval.** e5 was chosen specifically because a Hindi query can retrieve an
  English document (ADR-0006's stated rationale). TF-IDF/SVD is fit on the corpus's own vocabulary
  and script; a Devanagari or heavily romanized query shares almost no tokens with an English
  corpus and will not retrieve it. This is not a tuning gap — it is a property of the method, and
  it is measured, not asserted, in the Phase 5 retrieval suite.
- **No general-purpose pretraining.** The e5 model encodes broad world knowledge from its training
  corpus; TF-IDF/SVD only knows the statistics of documents it has seen. A held-out document type
  will embed worse than one similar to the fitted corpus.
- **A fit-at-ingest lifecycle, not a fixed model.** e5 is one pretrained model reused everywhere;
  TF-IDF/SVD is refit whenever the corpus changes materially, which the ingestion pipeline must
  version and track (`embedding_model` on each chunk records the fit's identity, per
  DATA_MODEL.md §5).
- **Fewer dimensions by design.** 256 rather than e5's 768 — LSA's useful rank for a corpus this
  size is much lower, and claiming 768 dimensions of a linear method fit on a few dozen documents
  would be false precision.

**What is unchanged:** the `EmbeddingProvider` interface, the `query:`/`passage:` asymmetry
handling (TF-IDF has no such asymmetry, so both methods apply the identity transform — recorded
explicitly rather than silently matching e5's contract by coincidence), and the decision to swap
based on measurement. The interface boundary this ADR argued for is exactly what makes the
substitution a one-file change rather than a rewrite.

**This is not a supersession.** `multilingual-e5-base` remains the intended production embedder.
The moment weights are reachable — a different execution environment, a vetted local mirror, or a
managed embedding API — `TfidfSvdEmbeddingProvider` is replaced by measurement (EVALUATION §4's
retrieval suite already reports per-language recall, which is precisely the number that would
justify or reject the swap), not by assumption. Presenting TF-IDF/SVD numbers as representative of
what this architecture achieves with its intended embedder would be a fabrication this project's
own rules forbid.
