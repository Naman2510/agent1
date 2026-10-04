# Phase 5 Audit — Audit Gate 5

**Reviewed:** RAG — ingestion (parse, clean, structure-aware chunking, metadata), hybrid retrieval
(pgvector HNSW + PostgreSQL full-text search fused by RRF), context building, citation resolution,
the `search_knowledge` tool schema, and the second working evaluation suite.
**Date:** 2026-09-19 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus the Phase 5 gate criteria, each checked by running
something against a real PostgreSQL + pgvector, not asserted from reading the code. 552 tests,
96% coverage on `app/` (93% including `eval/`, where the CLI entrypoint itself is exercised by real
runs rather than unit tests — the same carve-out Phase 4 made for `eval/runner.py`'s `lid` path).
`ruff` and `mypy` clean.

**Outcome:** 8 defects found and fixed, 6 Major items scheduled, 5 Minor recorded. Two failure
cases written up, one of which is a deliberate decision not to fix a measured gap.

**Gate status: PASSED.**

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Labelled retrieval set exists | `datasets/v1/retrieval/cases.jsonl`, 22 cases (20 `en`, 2 `hi`), referencing a real 5-document/19-chunk corpus by (document title, heading substring) so it survives re-ingestion. Provenance and bias recorded in `datasets/v1/MANIFEST.yaml`'s `retrieval_provenance`/`retrieval_bias` | pass |
| Ablation grid in EVALUATION §4 filled from real runs | `python -m eval.runner --suite retrieval --dataset v1`: vector-only, lexical-only, hybrid-RRF, and an offline real-BM25 reference, all against the live database. Full table in [EVALUATION.md §4](EVALUATION.md) | pass |
| Invented citation IDs proven to be dropped | `test_a_fabricated_citation_id_is_dropped` (unit, `resolve_citations` in isolation) and `test_the_full_pipeline_cannot_be_made_to_cite_a_source_it_never_retrieved` (integration — real ingested corpus, real retrieval, a `[77]` the model never received resolves to nothing) | pass |

Also verified: ingestion is idempotent on content hash (`test_re_ingesting_the_same_file_is_idempotent`); the HNSW index and GIN indexes match the model exactly (`alembic check` clean); a document producing fewer than two chunks is rejected rather than silently fit on nothing; and metadata filters (`subject`, `topic`, `difficulty`, `language`, `document_id`) are honoured identically by both retrieval arms.

---

## 2. Defects found and fixed

### D5-01 — The lexical arm silently never contributed to hybrid results
**Severity: major.** `lexical_search` built its Postgres query with `plainto_tsquery`, which ANDs
every input word. A six-word natural-language question ("What does KVL state?") requires all six
words present verbatim in a chunk to match at all — running real queries against the real corpus
returned **zero** lexical results for ordinary student phrasing, so the "hybrid" retriever was
silently vector-only.

**Fix:** `or_tsquery()` tokenizes the query with the shared Unicode-aware tokenizer and joins the
result with `|`, so `to_tsquery` matches *any* term, ranked by how many match. Caught by testing
real queries against the real ingested corpus, not by a unit test with a convenient fixture.

### D5-02 — Unicode combining marks silently fragmented every Devanagari and Tamil word
**Severity: critical for this project's mission.** Python's stdlib `\w` (used both in the tsquery
builder and in scikit-learn's `TfidfVectorizer(token_pattern=...)`) excludes Unicode categories Mc
and Mn — combining marks. Devanagari and Tamil vowel signs are combining marks attached to a base
consonant, so `\w+` split every word into its base consonants and floating marks:
`"किरचॉफ का नियम"` tokenized to `['क', 'रच', 'फ', 'क', 'न', 'यम']` — fragments, not words. Every
lexical match and every TF-IDF feature for these two scripts was built on garbage tokens.

**Fix:** switched to the third-party `regex` package with `[\p{L}\p{M}\p{N}]+`, applied identically
in both the tsquery builder and the vectorizer (via `tokenizer=`, since `token_pattern=` only
accepts stdlib-`re` patterns), deduplicated into a shared `app/rag/tokenize.py`. Verified:
`tokenize("किरचॉफ का नियम समझाओ")` → `['किरचॉफ', 'का', 'नियम', 'समझाओ']`, correct words, and
equivalently for Tamil.

### D5-03 — Model/migration drift, found twice by `alembic check`
**Severity: major (would have broken on a clean checkout).** First: the SQLAlchemy model did not
declare the HNSW (`vector_cosine_ops`) or GIN indexes the migration created, so `alembic check`
reported four indexes as spurious removals. Second, after fixing that: running real ingestion threw
`asyncpg.exceptions.GeneratedAlwaysError: cannot insert a non-DEFAULT value into column
"content_tsv"` — the model was missing `Computed("to_tsvector('simple', content)", persisted=True)`
that the migration had already applied to the real column.

**Fix:** both declarations added to `DocumentChunk`, mirroring migration 0002 exactly. `alembic
check` now reports "No new upgrade operations detected." This class of bug is specifically why
`alembic check` is run as part of this phase's own gate, not only in CI.

### D5-04 — A fixed `vector(256)` column vs. a small corpus's achievable SVD rank
**Severity: major (blocked all real ingestion).** With only 19 chunks in the sample corpus,
`TruncatedSVD`'s achievable rank is capped at 18 (rank ≤ min(features, n_samples − 1)), but the
schema column is a fixed-width `vector(256)`. Real ingestion failed outright: `expected 256
dimensions, not 18`.

**Fix:** `TfidfSvdEmbeddingProvider` zero-pads output vectors to the configured width while tracking
the real achieved rank separately for honest reporting (`tfidf-svd-256d(fit_rank=18)@19docs` — the
exact string this phase's `embedding_model` provenance column records). Zero-padding is
mathematically neutral for cosine similarity, verified by a dedicated test rather than assumed.

### D5-05 — Chunk-level copies of parent-document fields were unreliable or entirely absent
**Severity: major.** Found in two parts, the same underlying anti-pattern both times:

- `document_title` was read from `chunk.metadata_.get("document_title", "")`, a field nothing ever
  populated — every retrieved chunk's title was an empty string.
- `subject`/`topic` metadata filters were worse than merely unpopulated: `RagService.ingest_file()`
  never wrote `subject`/`topic` into `DocumentChunk.metadata_` at all, so `PgVectorStore`'s filter
  (`metadata_["subject"].astext == value`) compared against `NULL` and matched **nothing** —
  silently excluding every chunk whenever a subject filter was applied. Simultaneously,
  `HybridRetriever._apply_lexical_filters` didn't recognise `subject`/`topic` as filter keys at all
  and silently ignored them rather than raising, so the lexical arm ran **unfiltered**. The two
  arms disagreed about which filter keys existed, and RRF fusion papered over it: a subject filter
  meant to exclude a whole document instead let that document's chunks back in through the
  unfiltered lexical arm. Caught by
  `test_a_metadata_filter_excludes_the_other_subject`.

**Fix:** both retrieval arms now join to `Document` and filter on `Document.subject`/`Document.topic`
directly — the same fix pattern as `document_title` (read from the real source, never a
duplicated copy that can silently go stale). `HybridRetriever._apply_lexical_filters` now raises on
an unsupported filter key, exactly like `PgVectorStore._apply_filters` already did — the asymmetry
between a strict arm and a permissive one is precisely what let this hide.

### D5-06 — A zero-vector query got a fake ranking instead of "no results"
**Severity: major — inflated a headline retrieval number.** Full account in
[FC-004](failure_cases/004-cross-lingual-retrieval-degrades-to-zero-signal.md). In short: a query
with zero vocabulary overlap with the fitted TF-IDF corpus embeds to an all-zero vector; pgvector's
cosine distance against a zero vector is `NaN` for every row (verified directly against Postgres);
`ORDER BY` on all-NaN ties returns every row in an arbitrary scan-order sequence; and RRF fusion,
which only looks at rank position, silently turned that arbitrary order into a real fused score.
The pre-fix ablation run reported a suspiciously perfect `hi` recall@10 of 1.000 — found by
distrusting a number that looked too good for a mechanism with no cross-lingual capability by
construction, then tracing it to the actual mechanism rather than accepting it.

**Fix:** `PgVectorStore.search()` now short-circuits on an all-zero query embedding and returns no
matches. The corrected, honest `hi` recall@10 is **0.500** (1 of 2 cases), not 1.000.

### D5-07 — The `search_knowledge` tool input silently dropped an unexpected field
**Severity: low today, by design a security boundary.** `SearchKnowledgeInput`'s own module
docstring states "no `student_id` field, on purpose: identity is never a tool argument" — but
Pydantic v2's default is to silently *ignore* unrecognised fields rather than reject them, so a
model-supplied `student_id` (or anything else) would vanish quietly rather than fail loudly at the
one validation boundary between model output and this tool. Not yet exploitable — Phase 6 hasn't
built the execution loop that would read tool arguments — but the guarantee as stated was not
actually enforced.

**Fix:** `model_config = ConfigDict(extra="forbid")`. Verified directly: constructing the model with
an extra field now raises `ValidationError` instead of succeeding silently.

### D5-08 — The retrieval eval suite's own logic had zero test coverage
**Severity: major (a testing gap, found via this audit's own coverage diff, not a runtime
failure).** `eval/suites/lid.py` has a dedicated test file exercising `load_cases`/`run` directly
(`test_eval_lid_suite.py`, 98% covered); `eval/suites/retrieval.py` — `load_cases`,
`_resolve_relevant_ids`, `run_config`, `run_bm25_offline`, `fit_embedder_on_corpus` — had none,
0% covered, exercised only indirectly through one real CLI run. An evaluation harness that silently
miscounts is worse than none (Phase 4's own stated principle), and this one had never been checked
against a known-good fixture.

**Fix:** `tests/integration/test_eval_retrieval_suite.py`, 10 tests, now 99% covered (the one
remaining branch is a defensive-but-genuinely-hard-to-hit `# pragma` elsewhere). One `# pragma: no
cover` was removed from `_resolve_relevant_ids`'s error path once a test actually exercised it.
Building the fixture surfaced a real, separate fact worth recording so it isn't mistaken for a bug
later: classic BM25's IDF term goes *negative* for any word appearing in more than half the
documents in a corpus (`log((N−n+0.5)/(n+0.5))`, negative once n > N/2) — a 2-chunk fixture where
both chunks shared most of their vocabulary produced negative BM25 scores for a genuinely relevant
match. Not a defect (this is standard Okapi BM25 behaviour, confirmed against `rank_bm25` directly),
just a reason the test fixture needed five chunks, not two — and a reason to read any BM25 number
from a very small corpus with that pathology in mind.

---

## 3. A deliberate decision not to fix a measured gap

The lexical retrieval arm (`ts_rank_cd`) has no IDF weighting and, under the `simple` text-search
configuration, no stemming. Measured directly: for the query "What does KVL state?", a chunk that
never mentions KVL ties the actual KVL definition in rank, and a chunk that mentions KVL only as an
incidental reference outranks it outright — full mechanism, verified lexeme-by-lexeme against the
live database, in [FC-003](failure_cases/003-lexical-arm-lacks-idf-weighting.md). Aggregate cost is
visible too: `lexical_only`'s MRR is 0.710 against 0.856–0.886 for every other configuration.

**Not fixed.** This is the design ADR-0005 already committed to: the lexical arm is one signal fused
via RRF, expected to be weak alone, specifically so no single arm's weakness becomes the system's
ceiling — and the measured hybrid MRR (0.871) confirms fusion recovers most of the gap on this
corpus. A real BM25 rescoring, tried as a reference only, improves but does not fully close it
(the "steady state" false-positive from FC-003 still scores 2nd, because `rank_bm25`'s tokenizer
doesn't stem any more than `simple` does) — so implementing real IDF weighting is not a clean win
worth the schema and query-time cost until a larger corpus shows the lexical arm actually costing
fused-ranking quality, which it does not at 19 chunks.

---

## 4. Major findings (scheduled)

**M5-01 — Retrieval quality is measured on a 5-document, 19-chunk, self-authored corpus.**
Same bias shape as the LID dataset (Gate 4's M4-01): the person who wrote the corpus, the pipeline,
and the queries also labelled relevance, from memory rather than independent judgement. Recorded at
severity `high` in `datasets/v1/MANIFEST.yaml`'s `retrieval_bias`. *Blocking for:* any claim about
retrieval quality on real course material. *Scheduled:* a corpus and query set from an actual
course, labelled by someone other than this pipeline's author.

**M5-02 — No real embedder; the shipped substitute has no cross-lingual capability by construction.**
`multilingual-e5-base` is blocked on network access to HuggingFace Hub — verified via a 403 from the
sandbox's proxy, not assumed (ADR-0006's amendment). The TF-IDF/SVD substitute is fit per-corpus
with no pretraining on parallel text, so a pure-script Hindi query against the English corpus
retrieves nothing (D5-06/FC-004), and a code-switched one succeeds only by retaining literal shared
vocabulary. *Blocking for:* any cross-lingual retrieval claim. *Scheduled:* once network access (or
an offline-downloadable alternative) exists.

**M5-03 — No real reranker is exercised.** `RerankerProvider`'s interface has existed since Phase 2
and `NoopReranker` is wired through the whole ablation grid, but no cross-encoder reranker has been
built or measured (ADR-0007 leaves it flag-gated, off by default until it earns its latency).
*Scheduled:* once a larger corpus's precision@5 (currently 0.209–0.218 across all shipped configs —
expected at k=5 against only 19 chunks, not yet informative) shows headroom worth spending latency
on.

**M5-04 — The lexical arm's IDF/stemming gap is measured, not fixed.** See §3 above and FC-003.
*Scheduled:* revisit only if a larger corpus shows it costing fused recall or nDCG, which it does
not today.

**M5-05 — PDF ingestion is unit-tested but never exercised against a real PDF in this phase.**
`parse_pdf` (via `pypdf`) has unit coverage for its joining/page-marker behaviour, but the sample
corpus is Markdown only — no scanned or native PDF has gone through the real ingestion pipeline
end to end. *Scheduled:* whenever the first real course PDF is sourced (also needed for M5-01).

**M5-06 — Filter interaction with HNSW recall is functionally correct but not latency-measured.**
ADR-0005's own stated caveat — a selective metadata filter alongside the ANN operator can force a
fuller index scan — is true by construction of the query (`WHERE` applied alongside `ORDER BY
distance`), and filter *correctness* is tested (D5-05's fix), but no run has measured filtered vs.
unfiltered query latency. *Scheduled:* Phase 8, once corpus size makes the difference measurable
(19 chunks is too small for a scan-vs-index-use latency gap to show up at all).

---

## 5. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m5-01 | A test's own assertion miscounted expected chunks (`SAMPLE_B` has 2 subsections, asserted as 3) | Caught by the test failing immediately; fixed by correcting the test, not the pipeline — the pipeline's count (5) was right |
| m5-02 | Two fixture bugs in early `test_hybrid_retriever.py`: hardcoded `chunk_index=0` across chunks of the same document (`UniqueViolationError`), and `dimensions=8` against the real fixed schema width of 256 (`DataError`) | Both caught by the database rejecting the write, not by a silently-wrong result; fixed in the fixture |
| m5-03 | A `test_rag_context.py` fixture generated a different `document_id` per chunk by default, breaking a dedup test that needed two chunks to share one document | Fixed: default keys on title instead |
| m5-04 | Dead code found during development: an `if False` branch and an unused `RankCandidateAdapter` class in `retrieve.py` | Removed before either became tech debt |
| m5-05 | The lexical arm's filter function was more permissive than the vector arm's (silently accepted an unknown key instead of raising) | This asymmetry is what let D5-05 hide; both now raise identically on an unsupported key |

---

## 6. Dimensions reviewed with no finding above Minor

**Architecture consistency.** The pipeline matches ARCHITECTURE §11's own design exactly: parse →
clean → chunk → embed → store → hybrid retrieve → fuse → context build → cite. `RagService` is
deliberately not itself a tool (spec §12) — it returns structured data, and Phase 6's tool wrapper
is what the model will actually see, with its own validation and logging layered on top.

**Unnecessary complexity.** No new infrastructure was added beyond what ADR-0005/0006 already
committed to. The TF-IDF/SVD substitution is scoped narrowly (one provider class) and documented as
temporary rather than allowed to quietly become "how embeddings work here" — the amendment to
ADR-0006 says so explicitly, with an honest list of what it gives up relative to the originally
planned model.

**Security.** Citation IDs are scoped to a single turn's retrieved context server-side; a model
cannot cite a source it was never given regardless of what it emits (D-checked twice: unit and
end-to-end). The `search_knowledge` schema carries no student-identifying field, and D5-07 closed
the last gap between that stated guarantee and its actual enforcement. Filters are course-metadata
only — nothing behind this tool is student-shaped data at all (ARCHITECTURE §8.4).

**Testing strategy.** Every defect above was found by running something real — actual queries
against actual ingested content in a live pgvector database, never a mocked retriever — which is
exactly why D5-01, D5-02, and D5-06 were catchable at all: each is invisible to a unit test built
from a convenient fixture and only appears against real data with real script diversity. D5-08
extends the same discipline to the evaluation harness itself.

**Evaluation strategy.** The second working suite (`retrieval`, after Phase 4's `lid`) reuses the
same honesty pattern: a real ablation grid, a per-language breakdown specifically to expose the
weak case rather than average over it, an offline ground-truth reference (BM25) to quantify a known
gap rather than only assert it, and a bias statement recorded before any number is presented. The
`hi` row's corrected 0.500 (down from a pre-fix, bugged 1.000) is the clearest demonstration in this
phase of preferring an honest worse number over a flattering wrong one.

---

## 7. Gate decision

**PASSED.** Phase 6 (agent tools & memory) may begin.

Carried forward, unchanged in priority from Gate 4:
1. Run `scripts/smoke_llm.py` with a credential — the Claude adapter is still unexercised live.
2. Choose and implement a real ASR and TTS adapter; then measure TTFA.
3. Collect real speech and real course material: the same self-authorship bias now affects two
   datasets (LID and retrieval), and a real corpus additionally unblocks M5-01 and M5-05.

New from this gate:
4. Network access (or an offline-downloadable alternative) for `multilingual-e5-base`, to close the
   cross-lingual retrieval gap that the TF-IDF/SVD substitute cannot close by construction (M5-02).
