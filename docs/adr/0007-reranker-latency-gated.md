# ADR-0007 — Reranking is flag-gated and must earn its latency

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Cross-encoder reranking usually improves retrieval precision substantially. It is also the most
expensive component in the retrieval path: scoring *k* query–document pairs, each a full forward pass.
Our retrieval budget is 200 ms total, on CPU, inside a voice turn.

## Options considered
1. `BAAI/bge-reranker-v2-m3` (~568M, multilingual) over 30–40 candidates.
2. A smaller multilingual cross-encoder over a reduced candidate set.
3. A managed reranking API.
4. No reranker; rely on hybrid fusion (RRF) alone.
5. LLM-based reranking as part of generation.

## Decision
Reranking is **configurable and off by default in the voice path**, on by default in the offline
`retrieval` suite. Three configurations are measured before any default changes: no reranker;
local cross-encoder over top-10; managed reranker over top-40. The winner is whichever improves
nDCG@10 without breaching the retrieval budget.

## Rationale
- The arithmetic is not close: a 568M cross-encoder over 40 pairs on 4 CPU cores is on the order of
  seconds, not 200 ms. Enabling it by default in a voice loop would knowingly break the budget.
- Retrieval quality and voice latency are genuinely in tension here, so the honest resolution is to
  measure both and let the numbers decide — which is exactly the methodology the project claims.
- Keeping the reranker on for offline evaluation preserves the *upper bound* on retrieval quality as a
  reference point, so we always know what latency is costing us in quality.

## Tradeoffs accepted
- The voice path may run at lower retrieval precision than the system is capable of. That gap is
  quantified rather than hidden.
- Offline and online retrieval configurations differ, so retrieval-suite numbers are not automatically
  the numbers the voice path achieves. Run configs record which was used, and the two are never
  compared as if they were the same system.
- A managed reranker adds cost and a network hop.

## Consequences
- `RerankerProvider` with a `NoopReranker` default; retriever config is recorded in
  `retrieval_logs.retriever_config` per query, so any answer can be traced to the configuration that
  produced it.
- EXP-007 covers the ablation grid in EVALUATION §4.

## Revisit when
A GPU is available, a smaller multilingual cross-encoder hits the budget, or measurement shows the
quality gap from skipping reranking is large enough to justify spending latency elsewhere.
