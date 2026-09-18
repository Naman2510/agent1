# Roadmap, Phases, and Audit Gates

**Status:** Phase 0 complete pending audit sign-off. Nothing after Phase 0 has started.

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

### Phase 3 — Voice loop
AudioWorklet capture and playback in a minimal client, WebSocket protocol, VAD, turn detection,
STT streaming with LocalAgreement, sentence chunking, TTS streaming, playback ACK ledger, and the
turn state machine **including barge-in**.
**Runnable:** a spoken conversation that can be interrupted.
**Gate 3:** full state-transition test matrix; stale-`turn_id` frames dropped; stored assistant text
equals the spoken prefix; nine stage marks persisted; first real TTFA numbers recorded (whatever they
are).

### Phase 4 — Language routing
Script detection, romanized-Hinglish classification, sticky session state with hysteresis, response
language policy, TTS voice/transliteration selection.
**Gate 4:** per-language LID accuracy recorded as a baseline; mid-conversation switching preserves
context in an e2e test.

### Phase 5 — RAG
Ingestion (parse, clean, structure-aware chunking, metadata, heading paths), hybrid retrieval with
RRF, flag-gated reranking, context builder, citation resolution, `search_knowledge`.
**Gate 5:** labelled retrieval set exists; the ablation grid in EVALUATION §4 is filled from real
runs; invented citation IDs proven to be dropped.

### Phase 6 — Agent tools & memory
The eight tools with typed inputs, authorization, budgets, and tests; `IntentGate`; short-term Redis
window; long-term profile and topics; the async memory extractor with `memory_events` audit.
**Gate 6:** agent suite passing with gated-vs-ungated numbers; injection suite shows zero mutating
calls; a memory delta is traceable end to end.

### Phase 7 — Frontend & dashboard
Voice session UI (transcript, language indicator, tool activity, citations, latency HUD), history,
and the admin dashboard reading real aggregates.
**Gate 7:** no hardcoded metrics anywhere in the UI; "not measured" rendered where no run exists.

### Phase 8 — Evaluation, experiments, observability
All six suites runnable from one entrypoint, MLflow tracking, OpenTelemetry tracing, CI tiers T1–T3,
and the first genuine experiments (EXP-001, EXP-003, EXP-007) written up with decisions.
**Gate 8:** every suite reproducible from a recorded config; at least one experiment concluded
`reject` or `inconclusive` — a project where every experiment "worked" is not being run honestly.

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
