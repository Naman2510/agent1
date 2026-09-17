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
