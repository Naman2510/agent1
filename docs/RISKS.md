# Risk Register

**Status:** Phase 0. Scored at design time; to be re-scored at each audit gate.
**Scale:** Likelihood / Impact ∈ {Low, Med, High}. **Trigger** = the observable event that means the
risk has materialised and the mitigation must be executed.

---

## Critical and high risks

### R-01 — No GPU in the development environment
**L: Certain · I: High.** The target environment is 4 vCPU / 15 GB with no CUDA device. Local
`faster-whisper medium/large`, a 568M cross-encoder reranker, and open Indic TTS models are all far
too slow for a real-time voice loop on that hardware.
**Mitigation:** the real-time path uses managed ASR/TTS providers; local models are used for offline
evaluation and deterministic CI only. Provider abstractions make the split a config choice
(ADR-0002, ADR-0003). The latency budget (ARCHITECTURE §9) is written for this reality.
**Trigger:** stage-3 or stage-7 p95 exceeds budget in the voice suite.
**Residual:** the demo depends on third-party availability and on network latency from India.

### R-02 — Managed provider cost and quota
**L: High · I: High.** Voice is billed per minute of audio in *and* out, plus LLM tokens per turn. An
unbounded demo or a runaway agent loop is a real financial risk for an individual developer.
**Mitigation:** per-user daily voice-minute cap and AI-operation rate class (SECURITY §4); tool-call
budgets; prompt caching on the stable prefix; the Batch API at 50% for offline judge runs; T0/T1 CI
makes no paid calls; a hard monthly spend alert with the demo disabled on breach.
**Trigger:** projected monthly spend exceeds the stated budget, or any single session exceeds its cap.

### R-03 — Whisper is not a streaming model
**L: Certain · I: Med.** Whisper's encoder consumes 30-second windows and is non-causal; there is no
true incremental decode. Partial transcripts must come from repeated decodes of a growing buffer with
a stability policy (LocalAgreement), so partials will visibly revise themselves.
**Mitigation:** partials are UI-only and labelled unstable in the protocol (`stable_prefix_len`); the
turn commits on a final. If revisions prove distracting, switch the real-time path to a genuinely
streaming managed ASR (ADR-0002) — an already-designed swap, not a redesign.
**Trigger:** user-visible partial churn, or stage-3 budget misses.

### R-04 — Romanized Hinglish language identification
**L: High · I: High.** Off-the-shelf LID (fastText `lid.176`, provider language tokens) performs
poorly on romanized Hindi, which is the project's flagship case. There is no reliable pre-built
component to drop in.
**Mitigation:** a layered, cheap-first policy with session stickiness and hysteresis (ARCHITECTURE
§7); measured as LID accuracy per language with the `mixed` class defined by an explicit token
threshold; scoped as EXP-010's natural companion and as the fine-tuning candidate.
**Trigger:** LID accuracy on the Hinglish slice below the baseline recorded in the first `stt` run.
**Honest position:** this may remain the weakest component. It gets a failure-case file either way.

### R-05 — Code-switched TTS intelligibility
**L: High · I: High.** A multilingual voice handed "Bhai KVL basically kya bol raha hai" tends to read
romanized Hindi with English phonetics. Output can be near-unintelligible even when the text is
correct — and this is what a demo audience actually notices.
**Mitigation:** transliterate romanized Hindi spans to Devanagari before Indic synthesis while keeping
technical terms in Latin script (EXP-006); per-language voice selection; human intelligibility
ratings, because no automatic metric captures this.
**Trigger:** human intelligibility rating below the level recorded in the first TTS assessment.

### R-06 — Scope exceeds the available time
**L: High · I: High.** The specification describes roughly a small team's quarter: streaming voice,
agentic tools, hybrid RAG with reranking, two-tier memory, six eval suites, experiment tracking, a
dashboard, CI/CD, and optional fine-tuning. Attempting all of it in parallel produces a repository of
half-built subsystems, which is *worse* than a smaller complete system for the project's stated
purpose.
**Mitigation:** the MVP cut line in [ROADMAP.md](ROADMAP.md#mvp-cut-line): a demonstrable voice loop
with one eval suite beats ten stubs. Each phase ends with something runnable. Fine-tuning, WebRTC,
Prometheus, and Qdrant are explicitly deferred with trigger conditions.
**Trigger:** any phase overrunning its gate by more than 50% with nothing runnable.

### R-07 — Self-barge-in from acoustic echo
**L: High · I: Med.** With laptop speakers the microphone hears the assistant's own voice; the VAD
fires, and the system interrupts itself mid-sentence. Browser AEC helps for `getUserMedia` but is
unreliable when playback goes through Web Audio.
**Mitigation:** headphone recommendation surfaced in the UI; `echoCancellation: true`; a half-duplex
mode that gates VAD during playback (losing barge-in for those users); an energy-correlation guard
comparing mic input against the audio we are playing.
**Trigger:** any self-interruption observed in the e2e suite or in manual testing on speakers.
**Residual:** full AEC is not in scope for v1; the limitation is documented in the README.

## Medium risks

### R-08 — Backchannels kill good explanations
**L: Med · I: Med.** "Hmm", "haan", "achha" are agreement, not interruption, but they satisfy the
250 ms speech threshold. Once audio is flushed the turn cannot be resumed.
**Mitigation:** a language-specific backchannel stoplist checked against the first partial; tune
`min_speech` from the interruption dataset. **Residual:** documented, not solved.

### R-09 — Reranker breaks the latency budget
**L: High · I: Med.** A 568M cross-encoder over 40 candidates on CPU will not fit 200 ms.
**Mitigation:** flag-gated reranking, top-10 only in the voice path, or a managed reranker; decided
by measurement (ADR-0007). Reranking stays on for the offline retrieval suite regardless.

### R-10 — Indic lexical retrieval is weak
**L: Certain · I: Med.** PostgreSQL has no Hindi or Tamil stemmer, so the lexical arm of hybrid
retrieval degrades to near-exact matching for those scripts.
**Mitigation:** `simple` config plus trigram matching; per-language recall reported so the gap is a
number, not a surprise; consider ParadeDB `pg_search` or a real BM25 rescorer if the gap is material
(ADR-0005).

### R-11 — LLM judge unreliability
**L: Med · I: High.** Quality conclusions rest on a judge that has self-preference, position, and
verbosity biases, and is weaker in Tamil and Hinglish than in English.
**Mitigation:** cross-tier judge, versioned rubric prompts, randomised presentation order, and a
human-labelled calibration subset with **κ < 0.6 meaning the scores are declared unusable for
decisions** (EVALUATION §5.3).

### R-12 — Small datasets support no strong claims
**L: Certain · I: Med.** ~50 cases per language cannot separate small differences from noise.
**Mitigation:** manifests state the limitation; experiment decisions require effect sizes larger than
the slice can plausibly produce by chance, or are recorded as `inconclusive`. No confidence interval
is reported that the sample cannot support.

### R-13 — Sticky-session backend cannot scale a single conversation
**L: Med · I: Low (v1).** Turn state lives in a worker's memory, so a session cannot migrate.
**Mitigation:** stated as a v1 constraint (ARCHITECTURE §15); sticky routing by `session_id`; the
upgrade path (state in Redis, cancellation over pub/sub) is described but not built.

### R-14 — pgvector fixed dimensions block embedding experiments
**L: Certain · I: Low.** The serving column is `vector(768)`; a 1024-dim model cannot share it, and
HNSW caps at 2000 dimensions.
**Mitigation:** experiment-scoped side tables built by the eval harness; migrate the serving column
only when an experiment wins (DATA_MODEL §5).

### R-15 — Course-material licensing
**L: Med · I: High.** Ingesting copyrighted textbooks or lecture material into a public repository's
pipeline is a legal problem, not a technical one.
**Mitigation:** `documents.license` must be set before ingestion; the demo corpus uses openly
licensed or self-authored material; no corpus content is committed.

### R-16 — Voice data of minors
**L: Med · I: High.** Students may be under 18, which engages the DPDP Act's verifiable-parental-
consent requirement.
**Mitigation:** consent-gated, off-by-default audio retention; no personal data in the repository;
demo participants are adults; the position is written down in [DATASET.md](DATASET.md#5-pii-and-legal-position)
so it can be reviewed rather than assumed.

## Low risks

| ID | Risk | Mitigation |
|---|---|---|
| R-17 | WebSocket head-of-line blocking causes audio jitter on poor networks | Client jitter buffer; WebRTC is the documented upgrade path (ADR-0001) |
| R-18 | e5 embedding prefixes (`query:` / `passage:`) omitted, silently degrading retrieval | Enforced inside the provider, asserted by a unit test (ADR-0006). Not currently active: Phase 5 shipped a TF-IDF/SVD substitute because the sandbox has no route to HuggingFace Hub, which has no such prefix contract — see ADR-0006's amendment |
| R-19 | Prompt-cache invalidation from unstable serialisation | Deterministic tool ordering; a test asserting `cache_read_input_tokens > 0` on turn two |
| R-20 | MLflow / Postgres metric divergence | One-way mirror written once at run completion (ADR-0013) |
| R-21 | Provider API drift breaking the client | Pinned SDK versions; provider adapters isolated; contract tests against recorded fixtures |
| R-22 | Model refusal on an edge-case utterance stalls the turn | Handle `stop_reason: "refusal"` explicitly and enable server-side fallbacks (ADR-0008) |
