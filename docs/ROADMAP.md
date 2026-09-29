# Roadmap, Phases, and Audit Gates

**Status:** Phases 0–8 have passed their audit gates; Phase 9 (failure analysis and hardening) is in
progress: the degradation matrix (docs/DEGRADATION.md) and 14 failure cases are done; load behaviour
and the security checklist are not.

The specification (§43) mandates phased delivery with an audit gate between phases. Phases 1+ below
are reconstructed from spec §1–42; **the original specification was truncated part-way through the
Phase 1 description**, so the phase contents after Phase 0 are this project's proposal and should be
confirmed before Phase 1 begins.

---

## MVP cut line

The largest risk in this project is not technical, it is scope (R-06). So the cut line is explicit:

**Must exist for the project to be worth presenting** — a student can hold a real spoken
conversation in English and Hinglish, interrupt it, get answers grounded in course material with
inspectable citations, and see per-stage latency; and at least the `retrieval` and `voice` suites
produce recorded numbers with one honest experiment write-up.

**Valuable, after the above works** — Tamil (decided 2026-09-17: deferred past the MVP, M-01), the full six suites, memory extraction, quizzes and
study plans, the admin dashboard, experiment tracking UI.

**Deferred with trigger conditions, not promised** — fine-tuning (only if EXP-010's baseline shows
headroom), WebRTC (only if measured jitter hurts), Prometheus/Grafana (only under real operational
load), Qdrant (only if pgvector recall or latency fails), separate eval service container.

A complete small system beats a broad set of stubs. Every phase must end with something a person can
run.

---

## Phases

### Owner decisions (2026-09-17)

Recorded here because they closed two Gate 0 findings:

| Question | Decision |
|---|---|
| Autonomy | Full automation authority granted 2026-09-18: proceed through phases without asking. The reconstructed roadmap is authoritative; Gate 0 C-05(b) is closed as accepted rather than resolved. |
| MVP cut line | Agreed as written below. Phase 1 started immediately. |
| Tamil in the MVP? (M-01) | **No** — deferred past the cut line. Architecture stays language-agnostic; the README claims three languages until Tamil is measured. |
| Monthly spend ceiling (M-11) | Deferred. Phase 2 implements the cap mechanism and daily voice-minute limit with the value set in `.env` (`VAANIOS_MONTHLY_SPEND_CAP_USD`), unset meaning "no cap enforced" and logged loudly as such. |

### Phase 0 — Architecture & planning ✅
ARCHITECTURE, DATA_MODEL + reference DDL, API contract, EVALUATION, DATASET, SECURITY, RISKS,
ROADMAP, 16 ADRs, and the Gate 0 audit. No implementation.
**Gate 0:** [`PHASE_0_AUDIT.md`](PHASE_0_AUDIT.md) — blocking findings must be resolved or explicitly
accepted before Phase 1.

### Phase 1 — Backend foundation ✅
Delivered 2026-09-17: 61 tests, 93% coverage, lint and types clean. Gate 1 passed —
[`PHASE_1_AUDIT.md`](PHASE_1_AUDIT.md). Account erasure was pulled forward from the API design
because the security checklist already required the cascade test.

FastAPI app factory, settings via Pydantic Settings, Postgres + Alembic migrations matching
`db/schema.sql`, SQLAlchemy models and repositories, auth (Argon2id + JWT + refresh rotation),
Redis-backed rate limiting, structured logging with `request_id`, health endpoints, Docker Compose
(backend + postgres + redis), and CI tier T0.
**Runnable:** `docker compose up`, register a user, log in, create a session, see a request traced.
**Gate 1:** migrations reversible; IDOR test per endpoint; rate limits asserted; no secrets in the
repo; coverage on `core/` and `db/`.

### Phase 2 — Provider layer & LLM path (text first) ✅
Delivered 2026-09-18: 164 tests, 94% coverage. Gate 2 passed with the cache-hit criterion
deferred — [`PHASE_2_AUDIT.md`](PHASE_2_AUDIT.md). The spend-cap mechanism (Gate 0 M-11) shipped
here as agreed.

`LLMProvider`, `STTProvider`, `TTSProvider`, `EmbeddingProvider`, `RerankerProvider`, `VectorStore`
interfaces plus fakes for tests. Claude adapter with streaming, adaptive thinking, `strict` tools,
prompt-cache breakpoints, refusal fallbacks, and token accounting. Text chat endpoint end to end.
**Runnable:** a text conversation with the mentor, with usage and latency recorded per turn.
**Gate 2:** provider swap requires no application change; cache-hit test passing; cost per turn
recorded.

### Phase 3 — Voice loop ✅ (mechanisms; providers outstanding)
Delivered 2026-09-18: 353 tests, lint and types clean. Gate 3 passed —
[`PHASE_3_AUDIT.md`](PHASE_3_AUDIT.md). The loop is complete and provider-less: every mechanism is
tested, and no word has yet been transcribed or synthesised by a real model (M3-03).

AudioWorklet capture and playback in a minimal client, WebSocket protocol, VAD, turn detection,
STT streaming with LocalAgreement, sentence chunking, TTS streaming, playback ACK ledger, and the
turn state machine **including barge-in**.
**Runnable:** a spoken conversation that can be interrupted.
**Gate 3:** full state-transition test matrix; stale-`turn_id` frames dropped; stored assistant text
equals the spoken prefix; nine stage marks persisted; first real TTFA numbers recorded (whatever they
are).

### Phase 4 — Language routing ✅
Delivered 2026-09-18: 423 tests, 96% coverage. Gate 4 passed —
[`PHASE_4_AUDIT.md`](PHASE_4_AUDIT.md). First working eval suite and first versioned dataset:
LID signal accuracy 0.9205 (macro F1 0.8988) on `datasets/v1`, with the self-authorship bias
documented at severity `high`.

Script detection, romanized-Hinglish classification, sticky session state with hysteresis, response
language policy, TTS voice/transliteration selection.
**Gate 4:** per-language LID accuracy recorded as a baseline; mid-conversation switching preserves
context in an e2e test.

### Phase 5 — RAG ✅
Delivered 2026-09-19: 541 tests. Gate 5 passed — [`PHASE_5_AUDIT.md`](PHASE_5_AUDIT.md). Second
working eval suite: retrieval hybrid RRF recall@10 0.955, MRR 0.871, nDCG@10 0.893 on 22 labelled
queries against a 5-document self-authored corpus, with the self-authorship bias documented at
severity `high` (same shape as the LID dataset's).

Ingestion (parse, clean, structure-aware chunking with heading-path prefixing, metadata, idempotent
by content hash), hybrid retrieval (real pgvector HNSW cosine search + PostgreSQL full-text search)
fused by RRF, flag-gated reranking (interface wired, `NoopReranker` shipped — no real reranker
built), context builder, citation resolution, `search_knowledge` tool schema. The planned
`multilingual-e5-base` embedder is substituted with a real, working TF-IDF/SVD implementation
because the sandbox has no route to HuggingFace Hub (verified, not assumed) — documented as a
substitution pending network access, not a supersession ([ADR-0006's amendment](adr/0006-embedding-model.md)).
**Gate 5:** labelled retrieval set exists (`datasets/v1/retrieval`, 22 cases); the ablation grid in
[EVALUATION.md §4](EVALUATION.md) is filled from real runs; invented citation IDs proven to be
dropped, both in isolation and end-to-end from a real ingested corpus through real retrieval.

### Phase 6 — Agent tools & memory
The seven tools with typed inputs, authorization enforced at execution (not only at offer-time —
[PHASE_6_AUDIT.md](PHASE_6_AUDIT.md)'s D6-02, this phase's most significant finding), budgets, and
tests; `IntentGate` and its allowlist table (corrected mid-phase: `update_student_progress` was
registered and tested but reachable from no intent, D6-04); the short-term Redis window with a
rolling summary of turns older than it; long-term profile and topics; the async `MemoryExtractor`
with EWMA at a conversational alpha and a `memory_events` audit trail for every delta, applied or
rejected. **No real Anthropic API key exists in this sandbox** — same limitation as the STT/TTS
providers since Phase 3 — so the agent and injection suites both measure real mechanisms (allowlist
coverage, executor-level authorization, pipeline execution) against a scripted model, not a real
model's judgement; PHASE_6_AUDIT.md's M6-02 and the suites' own module docstrings say so plainly.
**Gate 6:** agent suite passing with gated-vs-ungated numbers; injection suite shows zero mutating
calls; a memory delta is traceable end to end. All three passed against real infrastructure:
14/14 scenarios' allowlists correctly supported (`eval/suites/agent.py`), 19/19 attempted injected
calls blocked and cross-checked against real Postgres row counts (`eval/suites/injection.py`), and
one real turn traced from utterance to a `student_topics` mastery update to its `memory_events` row
(`test_a_memory_delta_is_traceable_end_to_end_from_a_real_turn`).

### Phase 7 — Frontend & dashboard
Voice session UI (transcript, language indicator, tool activity, citations, latency HUD), history,
and the admin dashboard reading real aggregates.
**Gate 7:** no hardcoded metrics anywhere in the UI; "not measured" rendered where no run exists.

Delivered 2026-09-26: 725 backend tests (97% coverage), 35 frontend unit tests, and 14 end-to-end
tests in a real browser — with the real VAD and a microphone playing recorded speech — that CI runs
against the Docker Compose stack built as the README describes. Gate 7 passed —
[`PHASE_7_AUDIT.md`](PHASE_7_AUDIT.md). The web app is Next.js: sign-in with the refresh token kept
from page script, the voice session, typed sessions, history with each answer's sources and tools,
and the dashboard. Building it and running the whole system surfaced 23 defects, three Critical: the
VAD could not hear speech, so no spoken turn could ever have begun (D7-12); the production image
could not start (D7-14); and the configuration `.env.example` documents could not start the backend
(D7-17). CI had been red since Phase 5, so none of its later jobs had run; it is green on every job,
and now fails where a check used to skip or pass only on the developer's machine. Still provider-less:
every word heard and spoken in the suite is a fake's (M7-01), and only Chromium is tested (M7-02).

### Phase 8 — Evaluation, experiments, observability
All six suites runnable from one entrypoint, MLflow tracking, OpenTelemetry tracing, CI tiers T1–T3,
and the first genuine experiments (EXP-001, EXP-003, EXP-007) written up with decisions.
**Gate 8:** every suite reproducible from a recorded config; at least one experiment concluded
`reject` or `inconclusive` — a project where every experiment "worked" is not being run honestly.

Delivered 2026-09-27: every evaluation run is recorded — config, dataset digest, git SHA, every case
— in PostgreSQL and MLflow, reproducible from that record alone, and every committed config is
checked against its baseline in CI (ten on every push; the two `stt` configs in tier T2, with their
downloaded model, on every push that changes what they measure — and nightly once merged).
Two new suites: `voice`, the production voice session on synthetic speech in audio time, and
`stt`, faster-whisper on the same speech. EXP-003 (semantic endpointing) was **rejected** — 227 ms
faster, and three more students cut off — and EXP-008 (heading-path prefixing) **inconclusive**;
EXP-001 and EXP-007 are blocked on data and say what they need. One trace per voice turn
(OpenTelemetry), CI tiers T1–T3, and the dashboard's evaluation and experiment views. Gate 8 passed —
[`PHASE_8_AUDIT.md`](PHASE_8_AUDIT.md). Building the evaluations surfaced 15 defects, two Critical:
the turn detector was never consulted, so the experiment could not have taken effect (D8-02), and an
interruption landing mid-query broke every later turn of a voice session (D8-04). Of the six planned
suites, `response` and `e2e` do not exist (they need a live model, M8-03), and every number is on
self-authored or synthetic data (M8-02).

### Phase 9 — Failure analysis & hardening
At least eight documented failure cases with root causes and fixes, load behaviour under concurrent
sessions, graceful degradation when each provider fails, and the security checklist closed out.
**Gate 9:** every checklist item either done or explicitly accepted with a reason.

### Phase 10 — Optional fine-tuning (only if justified)
Intent classification only. Zero-shot → prompted → fine-tuned, on a held-out split, with cost and
latency compared. **If the prompted baseline is already strong enough, this phase is a written
decision not to fine-tune, which is a legitimate outcome and will be recorded as such.**

---

## Gate procedure

Each gate produces `PHASE_N_AUDIT.md` covering: architecture consistency, unnecessary complexity,
technology compatibility, security, scalability, external dependencies, testing, and evaluation.
Findings are graded **Critical** (blocks the next phase), **Major** (must be scheduled), **Minor**
(recorded). A gate may not be passed by asserting that code exists; it is passed by tests and, where
the phase produces metrics, by recorded runs.
