# Evaluation Framework

**Status:** Phase 5. **Two suites have run.** The language-identification and retrieval numbers
below are real, recorded, and reproducible from a committed dataset. Every other table in this
document is still empty, and stays empty until a recorded run fills it.

The evaluation subsystem is a first-class component, not a test folder. Its job is to make the
statement "this change improved the system" falsifiable.

---

## 1. Principles

1. **Per-stage attribution.** Six suites, each exercising one boundary, so a regression points at a
   component. An end-to-end score alone tells you something broke, not what.
2. **Everything is versioned.** A result is `(suite, dataset_version, config, git_sha)`. A metric
   without those four is not a result.
3. **Metrics are defined before they are measured**, including their known invalidities (§3.1).
4. **Judges are audited.** An LLM judge is a model under evaluation, not an oracle (§5.3).
5. **CI must be cheap and deterministic.** Paid model calls are not in the default CI path (§6).

## 2. Suite inventory

| Suite | Question it answers | Fixture type | Cost tier |
|---|---|---|---|
| `lid` ✅ | Do we identify the utterance's language? | text + label | free (no model) |
| `stt` | Do we hear the student correctly, per language? | audio + reference transcript | local model / paid ASR |
| `retrieval` ✅ | Do we find the right course material? | query + labelled relevant chunk IDs | free (local embeddings) |
| `agent` | Does the mentor choose the right tool with the right arguments? | scenario + expected tool trace | paid LLM, mockable |
| `response` | Is the answer grounded, relevant, and in the right language? | question + context + rubric | paid LLM + judge |
| `voice` | Does the conversation feel responsive? | scripted audio sessions | full stack |
| `e2e` | Do complete multi-turn conversations work, including interruption? | scripted sessions + assertions | full stack (mocked in CI) |

Each writes one `evaluation_runs` row plus per-case `evaluation_results`, and logs to MLflow.
Invocation: `python -m eval.runner --suite retrieval --dataset v1 --config configs/baseline.yaml`.

## 2a. Language identification — measured

```
python -m eval.runner --suite lid --dataset v1 [--failures]
```

**Run:** suite `lid`, dataset `v1` (88 cases), git `0adf300`, 2026-09-18. No model: the router is
Unicode script detection plus a hand-curated lexicon (ADR-0011).

Two reports, because there are two questions. **Signal** asks whether the utterance itself carried
enough evidence to identify its language — an utterance with no evidence counts as `unknown` even
where the router then answered correctly from its sticky prior. **Routed** asks what the router
actually chose, which is closer to what a student experiences. Reporting only the first understates
the system; reporting only the second hides that the signal is weak.

| | Signal | Routed |
|---|---|---|
| Accuracy | **0.9205** | 0.8750 |
| Macro F1 | **0.8988** | 0.7568 |

Per language (signal), recall:

| Language | Support | Recall | Precision | F1 |
|---|---|---|---|---|
| `hi` (Devanagari) | 17 | **1.000** | 1.000 | 1.000 |
| `ta` (Tamil script) | 9 | **1.000** | 1.000 | 1.000 |
| `hi-Latn` (romanized) | 25 | 0.960 | 0.923 | 0.941 |
| `en` | 22 | 0.864 | 0.950 | 0.905 |
| `mixed` (code-switched) | 8 | **0.625** | 1.000 | 0.769 |
| `unknown` | 7 | 1.000 | 0.636 | 0.778 |

By difficulty (signal): easy 0.980 (n=50) · medium 0.842 (n=19) · hard 0.842 (n=19).

**What these numbers say.** Script-based languages are settled by codepoints, so 1.000 there is
arithmetic, not achievement. The two informative rows are `hi-Latn` at 0.960 — optimistic, see the
bias note — and `mixed` at 0.625, which is the genuine weak spot and is written up as
[FC-002](failure_cases/002-mixed-language-under-detected.md).

**What they do not say.** The 88 cases were authored by the same person who wrote the lexicon they
test. That is the strongest available bias, it is recorded in `datasets/v1/MANIFEST.yaml`, and it
means these figures measure internal consistency and guard against regressions. **They are not
evidence of accuracy on real student speech.** Thresholds were deliberately left untuned against
this set: adjusting two constants until a self-authored suite scores 100% produces a better number
and a worse system.

The `unknown` row in the *routed* report scores zero by construction — the router always picks a
concrete language, because a voice product must answer in *some* language. That is a metric
artifact, not a defect; the router's uncertainty is exposed as a confidence value, not as a
refusal to answer.

Failures, all seven, are traceable to the tokens that caused them (`--failures` prints the
reasoning per case) and are written up as
[FC-001](failure_cases/001-insufficient-lexical-evidence.md) and
[FC-002](failure_cases/002-mixed-language-under-detected.md).

## 3. STT evaluation

### 3.1 Metrics, and where they lie

| Metric | Definition | Known invalidity |
|---|---|---|
| WER | word errors / reference words, after normalisation | Meaningless for Tamil (agglutinative — one wrong morpheme fails a whole word) and unstable for romanized Hinglish (`kyun`/`kyon`/`kyu` are the same word) |
| CER | character errors / reference characters | Primary metric for Tamil and Devanagari; less interpretable for English |
| Entity WER | WER restricted to Indian names, technical terms, and numerals | The metric that actually matters for a mentor; a 5% WER that eats every formula is useless |
| Numeral accuracy | exact match after numeric normalisation ("3.5" ≡ "three point five") | Requires a normaliser that is itself language-specific |
| LID accuracy | per-utterance language label vs. reference | `mixed` is a judgement call; the reference set defines a ≥20%-of-tokens threshold |
| Latency | `turn_end → final transcript`, p50/p95 | Provider-dependent and network-dependent; reported with the run config |

**Normalisation is part of the metric.** The pipeline (lowercase, punctuation strip, Unicode NFC,
numeral expansion, a documented romanized-Hindi spelling-variant map) is versioned alongside the
dataset, because changing the normaliser silently changes every historical WER. Results are reported
as `WER@norm-v1`.

### 3.2 Reporting

Always broken down by language; the aggregate is reported last because it hides the interesting case.

| Language | Cases | WER@norm-v1 | CER | Entity WER | LID acc | p95 latency |
|---|---|---|---|---|---|---|
| English | — | — | — | — | — | — |
| Hindi (Devanagari) | — | — | — | — | — | — |
| Hinglish (romanized, code-switched) | — | — | — | — | — | — |
| Tamil | — | — | — | — | — | — |
| Noisy (any language, SNR ≤ 10 dB) | — | — | — | — | — | — |

## 4. Retrieval evaluation — measured

```
python -m eval.runner --suite retrieval --dataset v1 [--failures]
```

**Run:** suite `retrieval`, dataset `v1` (22 cases), git `de38217`, 2026-09-19. Corpus:
`datasets/v1/corpus`, 5 self-authored documents, 19 chunks (§ below and DATASET.md). Embedder:
`tfidf-svd-256d(fit_rank=18)@19docs` — TF-IDF + truncated SVD, substituting for the originally
planned `multilingual-e5-base` (see [ADR-0006's amendment](adr/0006-embedding-model.md)).

| Metric | Definition |
|---|---|
| Recall@k | share of labelled-relevant chunks in the top *k* (k ∈ {5, 10}) |
| Precision@5 | labelled-relevant share of the top 5 |
| nDCG@10 | rank-sensitive quality with graded relevance |
| MRR | reciprocal rank of the first relevant chunk |
| Hit rate | share of queries with at least one relevant chunk anywhere in the top 20 |
| Context relevance | judge-scored 0–1 usefulness of the assembled context — not yet measured, needs a judge (§5.3) |
| Filter fidelity | share of results satisfying the requested metadata filter — exercised by `ret-022`; both arms respect `subject`/`topic` (Phase 5 audit D5-05) |

**Labelling, honestly.** Relevant chunks were labelled by the same person who wrote the corpus
documents and the retrieval pipeline, from memory rather than from a pooled candidate list across
configurations — the pooling method described below (kept as the target for a larger set) was
skipped as disproportionate for 19 chunks. This is the same shape of bias as the LID dataset (§2a):
these numbers show the pipeline retrieves what its own author expects, and are a regression guard,
not evidence of retrieval quality on material its builder did not write. Full statement in
`datasets/v1/MANIFEST.yaml`'s `retrieval_bias`.

**Ablations run as a standard grid**, because the claim "hybrid retrieval helps" is exactly the kind
of thing that is usually asserted and rarely tested. Disabling an arm means fusing it with an empty
ranking through the *same* production RRF code path, not a separate reimplementation, so what is
measured is the real retriever with an arm turned off:

| Config | Recall@5 | Recall@10 | Precision@5 | MRR | nDCG@10 | Hit rate |
|---|---|---|---|---|---|---|
| vector only | 0.932 | 0.955 | 0.209 | 0.856 | 0.885 | 0.955 |
| lexical only | 0.909 | 0.955 | 0.218 | 0.710 | 0.771 | 0.955 |
| **hybrid (RRF)** | 0.932 | 0.955 | 0.209 | **0.871** | **0.893** | 0.955 |
| hybrid + reranker | — | — | — | — | — | — (`NoopReranker` only; a real reranker is unbuilt) |
| lexical, real BM25 (reference only) | 0.932 | 0.955 | 0.216 | 0.886 | 0.897 | 0.955 |

The last row is not a retrieval configuration this system runs — it rescores the same queries
offline with `rank_bm25.BM25Okapi` purely to quantify the gap ADR-0005 predicted for the shipped
`ts_rank_cd` lexical arm (no IDF weighting). See "what these numbers say" below.

Reported per language, specifically to expose the embedder's cross-lingual gap
(ADR-0006's amendment):

| Language | n | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| `en` | 20 | 0.975 | 1.000 | 0.908 | 0.932 |
| `hi` (Devanagari/code-switched) | 2 | 0.500 | 0.500 | 0.500 | 0.500 |

**What these numbers say.** On this corpus, hybrid RRF ties vector-only on recall (both find a
relevant chunk in the top 5/10 for the same queries) but has the best ranking quality of the three
shipped configurations (MRR 0.871, nDCG@10 0.893) — ranking evidence, on 22 cases, that fusion helps
even where it does not change *what* is found. Lexical-only is the clear laggard on ranking quality
(MRR 0.710) despite matching the others on hit rate, which is the IDF gap made visible: a common
word can outrank a rare, diagnostic one under `ts_rank_cd`'s cover-density ranking. The concrete
case — a query where an off-topic chunk ties the actual definition it was looking for — is written
up as [FC-003](failure_cases/003-lexical-arm-lacks-idf-weighting.md).

**What they do not say.** The real-BM25 reference row's MRR (0.886) is the *highest* of all four —
higher than the shipped hybrid configuration. IDF weighting helps even on a 19-chunk corpus, and
this project does not ship it in the lexical arm; that gap is accepted, not hidden (ADR-0005). The
`hi` row's 0.500 across every column is exactly 1 of 2 cases succeeding: the one case that retains
literal English technical vocabulary in an otherwise Hindi sentence, and the one that is pure
Devanagari failing outright, honestly, with zero results rather than a wrong answer — see
[FC-004](failure_cases/004-cross-lingual-retrieval-degrades-to-zero-signal.md). n=2 is nowhere near
enough to size the cross-lingual gap, only to demonstrate that it exists. As with the LID dataset,
the corpus, queries, and relevance labels were all authored by the same person who built the
pipeline — see `retrieval_bias` in `datasets/v1/MANIFEST.yaml` before quoting any number above.

Labelling for a future, larger set: annotators mark chunks as `irrelevant / partially relevant /
fully relevant` from a pooled candidate list (top-20 from vector, lexical, and reranked runs) to
limit pool bias. Not yet needed at 19 chunks, where the author can enumerate every chunk directly.

## 5. Agent, response, and voice evaluation

### 5.1 Agent (tool use)

Scenarios are written as expected traces, and a case passes only on the whole trace:

| Field | Example |
|---|---|
| utterance | "How am I doing in electromagnetic theory?" |
| expected tools | `get_student_progress`, then optionally `retrieve_previous_conversation` |
| forbidden tools | `search_knowledge` (it would answer from the textbook, not the student's record) |
| argument assertions | `subject == "Electromagnetic Theory"`; **no** `student_id` present |
| expected outcome | response references mastery figures actually present in the tool result |

Metrics: tool-selection accuracy, argument exact/semantic match, **unnecessary-call rate** (a call
that did not change the answer), task-completion rate, and failure-recovery rate (behaviour when a
tool returns an error — the mentor must say so, not invent the data). Gated vs. ungated tool
exposure is reported side by side so the `IntentGate` has to earn its place.

**Measured, Phase 6 (`datasets/v1/agent/scenarios.jsonl`, 14 cases, `eval/suites/agent.py`):**

| Metric | Result | What it actually shows |
|---|---|---|
| Allowlist coverage | 14/14 | Every scenario's expected trace is supported, and its named-wrong tools excluded, by `IntentGate`'s real allowlist table — the check that would have caught `update_student_progress` never being reachable from any intent (a real bug this phase found and fixed, PHASE_6_AUDIT.md). |
| Pipeline completion | 10/10 | A scripted model requesting each scenario's trace completes end to end against the real orchestrator, executor, and database, including a deliberately-unnecessary allowed call (correctly flagged) and a handler-raised error (correctly surfaced, turn still completes). |
| Forbidden-tool leaks | 0/10 | No pipeline run executed a tool outside its scenario's forbidden list. |
| Gate earns its place | 5/5 probes | For five scenarios, the same attempted extra call is blocked under the scenario's real gated allowlist and would execute if every tool were offered instead — gating demonstrably changes the outcome. |

**What this is not.** No Anthropic API key exists in this sandbox (the same limitation already
noted for STT/TTS in Phase 3), so every "model" call above is scripted, not a real model choosing.
**Tool-selection accuracy and task-completion rate, as this section defines them — did a real model
pick correctly — are not measured.** Argument exact/semantic match is not scored either: every
argument was authored to be correct, so there is nothing for a real model to have gotten right or
wrong. What the gated-vs-ungated result shows is that the gate *mechanically* changes which calls
execute; it is not evidence for the actual question ARCHITECTURE §8.2 asks — whether narrowing
tool exposure helps or hurts a *real* model's completion rate — which needs a real agent-suite run
and is unmeasured. See `agent_scenarios_bias` in `datasets/v1/MANIFEST.yaml` for the full statement,
including an authoring bug this dataset's own construction caught (not by inspection, but by
running the allowlist check against the real table) as a concrete instance of the bias it describes.

### 5.2 Response quality

Dimensions scored per response: relevance, coherence, **groundedness** (every factual claim
attributable to retrieved context), citation correctness, helpfulness, language consistency
(answered in the language asked), conciseness (voice answers that run long are a defect), and
hallucination rate on adversarial "hallucination trap" cases.

### 5.3 Judge methodology, stated up front

- **Judge model:** a Claude model from a *different* tier than the one under test, pinned by exact ID
  in the run config. Same-model judging inflates scores through self-preference.
- **Prompt:** versioned in `eval/judges/`, with a rubric, few-shot anchors, and forced structured
  output (`output_config.format`) so scores are parseable rather than regex-scraped.
- **Calibration:** a ≥100-case human-labelled subset per language; agreement reported as Cohen's κ
  and Spearman ρ. **A judge with κ < 0.6 is reported as unreliable and its scores are not used to
  make decisions.** This is the check that keeps LLM-judge numbers from being decoration.
- **Determinism:** judge runs pin the model ID and use the Batch API (50% cost) for offline suites.
  Judge scores are still not deterministic; every reported score carries the run ID.
- **Limitations, written into the report:** position bias (mitigated by randomised presentation
  order), verbosity bias, weaker judging in Tamil and romanized Hinglish than in English, and the
  fact that a judge cannot assess pronunciation at all — that needs human raters.

| Dimension | EN | HI | Hinglish | TA | Human κ |
|---|---|---|---|---|---|
| Groundedness | — | — | — | — | — |
| Language consistency | — | — | — | — | — |
| Hallucination rate | — | — | — | — | — |

### 5.4 Voice / latency

Measured from real runs against scripted audio sessions, never estimated:

| Metric | Definition | p50 | p95 |
|---|---|---|---|
| TTFA | user speech end → first audio sample played | — | — |
| TTFA (filler enabled) | same, with cached opener audio | — | — |
| STT final latency | turn end → final transcript | — | — |
| LLM TTFT | request sent → first token | — | — |
| TTS TTFB | first sentence → first audio byte | — | — |
| Barge-in stop | voice onset → last sample played | — | — |
| End-to-end turn | user speech end → response fully played | — | — |

TTFA is reported with and without the filler-audio optimisation, and a filler-enabled number is
never presented as the bare TTFA — that would be measuring a trick.

TTS quality (intelligibility, pronunciation of Indian names and technical terms, code-switch
handling) is assessed by **human MOS-style rating** on a fixed script; there is no automatic metric
for this and none will be invented.

## 6. Test and CI tiers

| Tier | Runs on | Contents | External calls |
|---|---|---|---|
| T0 | every push | unit + integration + e2e with all providers faked | none |
| T1 | every push | `retrieval` suite on a small fixture corpus | none (local embeddings) |
| T2 | nightly + pre-release | `stt` (local model), full `retrieval` | none |
| T3 | manual / release gate | `agent`, `response`, `voice`, `e2e` live | paid |

T0 mocks at the **provider interface** (`LLMProvider`, `STTProvider`, …), never by patching HTTP, so
tests exercise real orchestration logic. Determinism comes from: recorded provider fixtures, a fake
clock for latency assertions, and a seeded fake embedding provider.

Tests that must exist and must be behavioural, not `assert x is not None` (spec §36):

- Barge-in: every state transition, including the illegal ones; stale-`turn_id` frames are dropped;
  the stored assistant message equals the spoken prefix for a given ACK sequence.
- Tool gating: a progress question selects `get_student_progress` and **not** `search_knowledge`.
- Authority: a tool-argument `student_id` injected by a prompt-injection fixture cannot reach the
  database.
- Citations: a model-invented citation ID is dropped rather than surfaced.
- Chunking: a 3.5 kΩ / Devanagari danda / Tamil punctuation fixture set is never split mid-token.
- Rate limiting: the 61st authenticated request in a minute returns 429 with `Retry-After`.
- Prompt cache: turn two of a session reports `cache_read_input_tokens > 0`.

## 7. Experiment workflow

Every AI-affecting change follows spec §31 and lands as a row in `experiments`:

```
Observation (from a metric or a failure case)
   → Hypothesis (falsifiable)
   → Design (ONE variable, which suites, what difference would matter)
   → Baseline run (recorded)
   → Candidate run (recorded)
   → Compare + inspect failure cases
   → Decision: adopt / reject / inconclusive, with rationale
```

Registered experiments (all **pending** — none has been designed in detail, let alone run):

| ID | Hypothesis | Variable | Suites | Status |
|---|---|---|---|---|
| EXP-001 | A managed Indic ASR beats local faster-whisper on Hinglish entity WER | STT provider | stt | pending |
| EXP-002 | Contextual vocabulary biasing reduces technical-term errors | ASR prompt/vocab | stt | pending |
| EXP-003 | Semantic endpointing cuts turn-end latency without more premature cutoffs | turn detector | voice, e2e | pending |
| EXP-004 | Response latency/quality trade across LLM tiers | LLM model | response, voice | pending |
| EXP-005 | Short first TTS chunk improves TTFA without hurting prosody ratings | chunker policy | voice + human | pending |
| EXP-006 | Transliterating romanized Hindi before Indic TTS improves intelligibility | TTS preprocessing | human MOS | pending |
| EXP-007 | Hybrid retrieval beats vector-only on Hindi/Tamil queries | retriever | retrieval | pending |
| EXP-008 | Heading-path prefixing improves recall on lecture material | chunk enrichment | retrieval | pending |
| EXP-009 | Intent-gated tool exposure improves selection without hurting completion | tool gate | agent | pending |
| EXP-010 | A fine-tuned intent classifier beats the prompted baseline | classifier | agent | pending |
| EXP-011 | Lowering the `mixed` gate raises its recall without costing `en`/`hi-Latn` precision | classifier thresholds | lid | registered, blocked on a dataset that is not self-authored |

An experiment that changes two variables is recorded as `inconclusive`. This is enforced socially,
by review, and structurally, by `experiments.variable_changed` being a single column.

## 8. Dashboard

The admin dashboard (spec §33) reads only from `evaluation_runs`, `evaluation_results`,
`experiments`, `tool_calls`, and `messages.latency_ms` — real system data, with no hardcoded numbers
and no placeholder charts. Panels: system health (active sessions, error rate, stage-failure counts),
model quality (latest run per suite, per language), experiment comparison (baseline vs. candidate),
and a failure-case browser backed by `evaluation_results WHERE passed = false`.

If a suite has never run, the dashboard shows "not measured" — not a zero, and not a sample value.
