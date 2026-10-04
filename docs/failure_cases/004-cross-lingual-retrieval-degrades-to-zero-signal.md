# FC-004 — A query with zero vocabulary overlap silently got a fake ranking, not zero results

**Status:** fixed (the ranking-integrity bug) — the underlying zero-signal behaviour for
out-of-vocabulary queries is an **accepted limitation** of the embedder substitution, not something
this fix (or any fix short of a real multilingual embedder) resolves
**Found:** 2026-09-19 · **Phase:** 5 · **Component:** rag
**Severity:** major
**Case IDs:** `ret-020`, `ret-021` (dataset v1, retrieval slice — the two deliberately cross-lingual
cases)

## Input

Two Hindi-script queries against the English-only sample corpus:

- `ret-020`: `"किरचॉफ का वोल्टेज नियम क्या है"` ("What is Kirchhoff's voltage law", pure Devanagari,
  no Latin-script tokens at all)
- `ret-021`: `"मैक्सवेल के समीकरण में displacement current क्यों जोड़ा गया"` ("Why was displacement
  current added to Maxwell's equations", Hindi sentence structure, code-switched with the English
  technical term)

## Expected

Given the embedder is TF-IDF/SVD fit only on the English corpus (ADR-0006's amendment — a
substitute for the originally planned `multilingual-e5-base`, which the sandbox cannot download),
neither query should retrieve well. The honest, correct behaviour for a query with no shared
vocabulary is **no results from that arm** — a visible, honest "not found" — not a result that looks
like a ranked match.

## Actual

Before the fix, the full ablation run reported **`hi` recall@10 = 1.000** (both cross-lingual cases
"succeeding") — a suspiciously perfect number for a mechanism with no cross-lingual capability by
construction, which is exactly the kind of number this project's own methodology exists to
distrust rather than report at face value. Direct inspection showed why:

```
vector arm (ret-020): 19 hits, top ids+scores: [('160c5c9f', nan), ('05ecb7c2', nan), ...]
lexical arm (ret-020): 0 hits
```

Every single chunk in the corpus came back from the vector arm with a `nan` similarity score, and
the fused ranking placed the correct chunk (`Kirchhoff's Laws`, heading `7.1`) at rank 8 of 19 —
comfortably inside the fused top 10, which is why recall@10 read as a perfect 1.000.

## Root cause

Traced end to end, each step verified directly rather than assumed:

1. `"किरचॉफ का वोल्टेज नियम क्या है"` shares zero vocabulary (including n-grams) with the
   English-fit TF-IDF corpus. Verified directly: `TfidfSvdEmbeddingProvider.embed_query()` on this
   text returns a **clean all-zero 256-dimensional vector** (not NaN — sklearn's `Normalizer`
   correctly guards against dividing a zero vector by its own zero norm).
2. That all-zero vector is then compared against every chunk's embedding via pgvector's `<=>`
   (cosine distance) operator in `PgVectorStore.search()`. Cosine similarity is mathematically
   undefined for a zero vector (no defined direction), and pgvector returns `NaN` for it — verified
   directly against the live database: `SELECT '[0,0,0]'::vector <=> '[1,2,3]'::vector` returns
   `NaN`, not an error and not `0`.
3. Every row in the `ORDER BY distance` query therefore ties at `NaN`. Postgres still has to return
   *something* for a tied sort key, so it returns all 19 rows in an arbitrary (physical scan order)
   sequence — a sequence that looks exactly like a ranked result set but carries no similarity
   information whatsoever.
4. `HybridRetriever.vector_search()` passed this arbitrary order through as `RankedItem`s with
   `score=nan`, and **Reciprocal Rank Fusion only looks at rank *position*, never the score
   value** — so the arbitrary tie-break order silently became a real, non-NaN contribution to the
   fused RRF score. For `ret-020`, this arbitrary ordering happened to place the correct chunk at
   position 8 of 19 — a matter of luck in Postgres's tie-break order, not retrieval capability.

This is not exclusively a cross-lingual issue — any query whose every token is out-of-vocabulary
for the fitted corpus (a garbled query, a query in pure stopwords filtered out by `max_df`, a typo
in every word) would trigger the identical bug. Cross-lingual queries are simply the reliable way
to reproduce a zero vector on demand.

## Fix

`PgVectorStore.search()` now checks the query embedding for an all-zero vector (`if not
any(embedding): return []`) before issuing the SQL query at all, and returns no vector matches —
which is both the mathematically honest answer ("no defined direction" → "no signal") and cheaper
than querying and filtering NaNs after the fact. Regression test:
`test_a_zero_query_vector_returns_no_matches_rather_than_nan_ranked_ones` in
`tests/integration/test_pgvector_store.py`.

## Result, after the fix

Re-running the same diagnostic: `ret-020`'s vector arm now correctly returns **0 hits**, its lexical
arm already returned 0 hits (no shared vocabulary there either), and the query correctly fails to
retrieve anything — visible, honest, and no longer disguised as a lucky top-10 hit.

The corrected full ablation run (EVALUATION.md §4):

| Language | n | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| `hi` | 2 | 0.500 | 0.500 | 0.500 | 0.500 |

Exactly 1 of 2 `hi` cases now succeeds — `ret-021`, whose query retains the literal English phrase
"displacement current" and therefore has real, non-zero vocabulary overlap with the corpus (both
arms correctly rank the right chunk 1st). `ret-020`, pure Devanagari with no shared vocabulary,
correctly fails outright ("0 of 1 relevant chunks found in top 10"). This is a **worse-looking, more
honest number** than the pre-fix 1.000 — exactly the trade this project's methodology is supposed to
make.

## What remains open (accepted limitation, not further "fixed" by this change)

The TF-IDF/SVD substitute embedder has **no cross-lingual retrieval capability by construction**: it
is fit on whatever corpus it is given, with no pretraining on parallel or multilingual text, unlike
the originally planned `multilingual-e5-base` (ADR-0006). A query in a different script than the
corpus will retrieve well only insofar as it happens to retain shared vocabulary (as `ret-021`
does via code-switching) — never through genuine cross-lingual semantic matching. Closing this gap
needs the real embedder, which is blocked on network access to HuggingFace Hub (verified via a 403
from the sandbox's proxy, not assumed — see ADR-0006's amendment). Tracked there, not reopened here.

## Experiment

Not registered — this was a correctness bug (NaN silently becoming a fake ranking signal), not a
quality hypothesis under test. The residual cross-lingual gap is tracked as an accepted limitation
in ADR-0006's amendment, to be revisited once a real multilingual embedder is reachable.
