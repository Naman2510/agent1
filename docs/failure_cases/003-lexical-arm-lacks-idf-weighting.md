# FC-003 — The lexical retrieval arm ranks a common word as strongly as a rare, diagnostic one

**Status:** accepted-limitation
**Found:** 2026-09-19 · **Phase:** 5 · **Component:** rag
**Severity:** major
**Case ID:** `ret-001` (dataset v1, retrieval slice); reproduced directly against the live database,
not only through the eval suite

## Input

Query: `"What does KVL state?"`, run through `HybridRetriever.lexical_search` alone (the shipped
`ts_rank_cd` arm), against the ingested sample corpus (`datasets/v1/corpus`).

## Expected

The chunk that actually defines KVL — *"Kirchhoff's Voltage Law, usually written KVL, states that
the sum of all potential differences..."* (`Kirchhoff's Laws`, heading `7.1`) — should rank at or
near the top. `kvl` is a rare, maximally diagnostic token in this corpus; a lexical ranker should
reward matching it.

## Actual

It ranks **4th**, tied in score with an unrelated Waveguides chunk, and *behind* two chunks that
have nothing to do with KVL at all:

| Rank | Score | Document / heading | Contains `kvl`? |
|---|---|---|---|
| 1 | 0.300 | Network Theorems — 9.1 Mesh analysis | yes (3×, incidentally) |
| 2 (tied) | 0.300 | Transient Response — 11.3 Second-order RLC circuits | **no** |
| 3 (tied) | 0.200 | Waveguides — 19.2 TE and TM modes | no |
| 4 (tied) | 0.200 | **Kirchhoff's Laws — 7.1 Kirchhoff's Voltage Law (the definition itself)** | yes |

Verified directly in Postgres which lexemes actually matched for each chunk (`to_tsvector('simple',
content) @@ to_tsquery('simple', '<lexeme>')`):

| Chunk | has `state` | has `states` | has `kvl` |
|---|---|---|---|
| 9.1 Mesh analysis | no | no | **yes** (repeated) |
| 11.3 Second-order RLC circuits | **yes** (via "steady **state**", ×2) | no | no |
| 7.1 Kirchhoff's Voltage Law | no | **yes** ("...KVL, **states** that...") | yes |

## Root cause

Two compounding defects in the shipped lexical arm, both real and both verified against the live
database, not inferred:

1. **No IDF weighting.** `ts_rank_cd` is Postgres's cover-density ranking — it rewards how many
   query lexemes match and how close together they are, with no discount for how common or
   diagnostic a lexeme is. The word `state` matching twice, via the unrelated idiom "steady
   state", scores exactly as well as `kvl` — a term that appears in exactly one topic in the whole
   corpus — matching once. This is precisely the algorithm this codebase has always called
   "lexical", never "BM25" (ADR-0005, Gate 0 finding M-03): Okapi BM25's IDF term is the piece that
   would fix this, and `ts_rank_cd` does not have one.
2. **No stemming under the `simple` text-search configuration.** The query's tokenized term is
   `state`; the KVL definition's own sentence uses `states` ("...KVL, **states** that..."). Postgres
   `simple` does no stemming, so these are different lexemes and the match is lost entirely — the
   one sentence that most directly answers the question gets no credit at all for its own defining
   verb. This is a second, independent defect layered on top of the first: even a corrected IDF
   weighting would not by itself fix the state/states mismatch.

Together: a chunk that never mentions KVL (11.3, via "steady state") ties the actual KVL definition
in rank, and a chunk that mentions KVL only as a side reference three times (9.1, mesh analysis)
outranks it outright.

## Proposed fix

Real IDF weighting (a genuine BM25 implementation) would address defect 1. A stemming or
lemmatizing text-search configuration (Postgres ships `english`, but nothing for Hindi/Tamil, which
is a separate documented gap — ADR-0005) would address defect 2 for English queries only.

## Decision

**Not fixed — accepted as a known, quantified limitation**, per the design already recorded in
ADR-0005: the lexical arm exists as one signal fused via RRF with the vector arm, not as the sole
retriever, specifically because it is expected to be weak in isolation. What this failure case adds
is a *concrete, verified case* rather than a description of the mechanism, and a *measured size* of
the gap:

- On the full 22-case retrieval eval, `lexical_only`'s MRR is 0.710 against 0.856–0.886 for every
  other configuration (EVALUATION.md §4) — the ranking-quality cost is real and visible in the
  aggregate, not just this one example.
- Real BM25, rescored offline over the same corpus (`rank_bm25.BM25Okapi`, reference only — never a
  shipped code path) on this exact query, correctly promotes the chunk that discusses KVL vs KCL
  directly (score 3.951, rank 1) and demotes Mesh analysis relative to `ts_rank_cd` (rank 4, down
  from a tie for 1st) — but does **not** fully solve it either: "Second-order RLC circuits" (the
  "steady state" chunk, zero KVL relevance) still scores 2nd (3.189), ahead of the literal
  definition chunk, because `rank_bm25`'s default tokenizer does not stem any more than `simple`
  does. IDF weighting alone is a real improvement, not a complete fix, for this specific case.
- **hybrid RRF still finds a relevant chunk for this query** (the retrieval dataset labels both 7.1
  and 7.3 as relevant for `ret-001`, and 7.3 ranks well via the vector arm), which is the point of
  fusing two weak-in-isolation arms rather than depending on either alone.

Revisiting this is worthwhile if a larger corpus ever shows the lexical arm materially hurting
fused ranking quality — not indicated yet at 19 chunks, where the vector arm carries most of the
useful signal (EVALUATION.md §4).

## Experiment

Not registered. This is a measured, understood, currently-accepted gap rather than a hypothesis
under test; if a future corpus shows lexical-arm ranking quality actually costing fused recall or
nDCG, that would justify EXP-007's converse (does a *better* lexical arm help beyond what hybrid
already provides over vector-only).

## Result

Not applicable — no fix was attempted. The gap is measured (MRR 0.710 vs. 0.856–0.886) and
documented rather than closed.
