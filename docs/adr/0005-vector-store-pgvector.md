# ADR-0005 — PostgreSQL + pgvector as the vector store (not Qdrant)

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Hybrid retrieval over course material needs vector search, lexical search, and metadata filtering,
joined to relational data (documents, subjects, semesters) that already lives in Postgres. Realistic
corpus size for this project is 10⁴–10⁵ chunks.

## Options considered
1. **Postgres + pgvector** (HNSW) with Postgres full-text search for the lexical arm.
2. **Qdrant** for vectors, Postgres for everything else.
3. **pgvector + a dedicated BM25 engine** (ParadeDB `pg_search`, or Elasticsearch/OpenSearch).
4. In-process FAISS with vectors on disk.

## Decision
Postgres 16 + pgvector with an HNSW index, plus Postgres FTS (`tsvector`/GIN) and `pg_trgm` for the
lexical arm. Both arms behind a `VectorStore` / retriever interface so Qdrant remains swappable.

## Rationale
- At 10⁴–10⁵ chunks, pgvector HNSW is comfortably adequate; choosing a distributed vector database at
  this scale is complexity without measurable benefit, and would be hard to defend.
- **Transactional consistency for free:** ingesting a document and its chunks, or deleting them, is
  one transaction. With a separate store, chunk rows and vectors can diverge and need reconciliation.
- Metadata filtering and citation resolution become ordinary SQL joins rather than a filter DSL plus
  a second lookup.
- One fewer service in Compose, one fewer thing to operate, back up, and explain.

## Tradeoffs accepted
- **Fixed-dimension columns.** `vector(768)` cannot hold a 1024-dim model, and pgvector's HNSW index
  supports at most 2000 dimensions. Multi-model embedding experiments need side tables
  (DATA_MODEL §5, R-14); Qdrant's named vectors would handle this natively. This is the strongest
  argument *against* this decision and it is accepted knowingly.
- **No native hybrid fusion.** RRF is implemented in application code.
- **No true BM25.** `ts_rank_cd` is cover-density ranking. The lexical arm is called "lexical"
  everywhere, and where a real BM25 comparison matters the retrieval suite rescores offline with
  `rank_bm25` (M-03 in the Gate 0 audit).
- **No Hindi or Tamil stemmer exists in Postgres.** Those scripts use the `simple` configuration plus
  trigram matching, making the lexical arm materially weaker for them. Per-language recall is
  reported precisely so this appears as a number (R-10).
- Filtered HNSW search can lose recall when a filter is highly selective; measured with and without
  filters.

## Consequences
- Retrieval quality claims must always be reported per language.
- If pgvector recall or p95 latency fails its target, the migration path is Qdrant behind the same
  interface, with the embedding-dimension problem solving itself as a side effect.

## Revisit when
Corpus exceeds ~10⁶ chunks, or recall@10 falls short of target with filters applied, or multi-vector
retrieval (ColBERT-style, bge-m3 multi-vector) becomes a serious candidate.
