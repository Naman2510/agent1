# VaaniOS

A multilingual conversational AI voice mentor for Indian students — **English, Hindi, and Hinglish
(code-switched)** in the MVP, with **Tamil deferred to a later phase** — built as a **measurable**
voice pipeline rather than a thin wrapper around an LLM API.

---

## Project status

| | |
|---|---|
| **Current phase** | Phase 1 — Backend Foundation (in progress) |
| **Implementation** | Phase 1 complete — 61 tests passing, 93% backend coverage. No voice loop, agent, or RAG yet. |
| **Benchmarks** | None. Every metric table in this repository is empty by design. |
| **Last updated** | 2026-09-17 |

> **Nothing here is measured yet.** Latency figures in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
> are *budgets* (design targets), not results. Quality metrics in
> [`docs/EVALUATION.md`](docs/EVALUATION.md) are *metric definitions*, not scores. No number will be
> written into this repository until it comes out of a reproducible run recorded in
> `evaluation_runs`. See [Honesty rules](#honesty-rules).

---

## The problem

An engineering student in India stuck on Maxwell's equations at 11pm has two options: read a
textbook, or type into a chatbot. Neither matches how they'd actually ask a senior — out loud, in
whatever mixture of languages comes naturally ("Bhai KVL basically kya bol raha hai?"), with
follow-ups, interruptions, and the expectation that the mentor remembers last week's weak spots.

VaaniOS targets that interaction. The hard parts are not "call an LLM":

1. **Latency.** A mentor that answers 4 seconds after you stop talking is not conversational.
2. **Code-switching.** Romanized Hindi mixed with English technical vocabulary is the failure mode
   of nearly every off-the-shelf ASR and TTS system.
3. **Interruption.** Being able to say "wait, stop" mid-explanation is table stakes for speech and
   requires server-authoritative cancellation, not a client-side mute.
4. **Groundedness.** A mentor that invents a formula is worse than no mentor.
5. **Knowing what's actually true.** Each of the above is an empirical claim, so the system is built
   so every stage can be benchmarked in isolation.

## Architecture in one picture

```
 Browser (Next.js)                      Backend (FastAPI, async)
 ┌──────────────┐   PCM 16k/20ms   ┌──────────────────────────────────────────┐
 │ mic ─ Worklet├─────────────────►│ VAD (Silero) ─► STT ─► Language ID       │
 │              │   WebSocket      │                          │               │
 │ speaker ◄────┤◄─────────────────┤ Orchestrator ◄───────────┘               │
 │  jitter buf  │  audio + events  │   ├─ RAG (pgvector + lexical + rerank)   │
 └──────────────┘                  │   ├─ Tools (typed, gated, budgeted)      │
                                   │   ├─ Memory (Redis short / PG long)      │
                                   │   └─ LLM (streaming, cancellable)        │
                                   │            └─► sentence buffer ─► TTS    │
                                   └──────────────────────────────────────────┘
                                        │ Postgres+pgvector │ Redis │ MLflow
```

Full diagrams, the turn state machine, the barge-in protocol, and the latency budget are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation map

| Document | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, turn lifecycle, barge-in, WS protocol, latency budget, repo layout |
| [`docs/PHASE_0_AUDIT.md`](docs/PHASE_0_AUDIT.md) | **Audit Gate 0** — critical review of this design, with blocking findings |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | ADR index (16 records in `docs/adr/`) |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Entities, relationships, indexing strategy; DDL in [`db/schema.sql`](db/schema.sql) |
| [`docs/API.md`](docs/API.md) | Planned HTTP + WebSocket contract |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | The six eval suites, metric definitions, CI tiers, judge methodology |
| [`docs/DATASET.md`](docs/DATASET.md) | Dataset versioning, data-quality pipeline, PII policy, licensing |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model (incl. prompt injection via course material) and checklist |
| [`docs/RISKS.md`](docs/RISKS.md) | Risk register with triggers and mitigations |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phases, audit gates, and the MVP cut line |
| [`docs/failure_cases/`](docs/failure_cases/) | Documented failures — input, expected, actual, root cause, fix, result |

## Tech stack (planned)

**Frontend** Next.js · React · TypeScript · Tailwind · Web Audio API (AudioWorklet)
**Backend** Python 3.11 · FastAPI · Pydantic v2 · asyncio · WebSockets
**Data** PostgreSQL 16 + pgvector · Redis 7 · SQLAlchemy 2 · Alembic
**Voice** Silero VAD · faster-whisper (local) / managed streaming ASR · streaming TTS (provider-abstracted)
**AI** Claude (`claude-opus-5`) via the Anthropic Python SDK · multilingual-e5 embeddings · cross-encoder reranker
**Eval/Infra** pytest · MLflow · OpenTelemetry · Docker Compose · GitHub Actions

Every model-facing component sits behind an interface (`STTProvider`, `TTSProvider`, `LLMProvider`,
`EmbeddingProvider`, `RerankerProvider`, `VectorStore`) so that A/B comparison is a config change,
not a rewrite — see [ADR-0016](docs/adr/0016-provider-abstraction-boundaries.md).

## Setup

```bash
cp .env.example .env
# set VAANIOS_JWT_SECRET — e.g. openssl rand -base64 48
docker compose -f infra/compose.yaml up --build
```

Postgres, Redis, migrations, and the API come up together; the API is on `http://localhost:8000`
with interactive docs at `/docs` (disabled in production builds).

```bash
curl localhost:8000/v1/health   # {"status":"ok",...}
curl localhost:8000/v1/ready    # per-dependency readiness
```

**Running the tests** needs a PostgreSQL to point at — the suite runs the real migrations against a
real database rather than a stand-in, because the schema relies on enums, JSONB, citext, partial
indexes and check constraints:

```bash
cd backend
pip install -e ".[dev]"
export VAANIOS_TEST_DATABASE_URL=postgresql+asyncpg://vaanios:vaanios@localhost:5432/vaanios_test
pytest -q                       # 61 tests
ruff check . && mypy app
```

Without a Docker daemon, `scripts/dev_db.sh start` brings up a local cluster instead (no pgvector,
so it is only sufficient through Phase 4).

## What works today

Phase 1 is the backend foundation — deliberately no voice, agent, or RAG yet:

- Registration, login, `/auth/me`, profile update, and **account erasure** (hard delete, cascading)
- Access tokens (15 min) with **single-use refresh tokens**; replaying a rotated token revokes the
  whole rotation family
- Conversation sessions and transcript reads, scoped so one student cannot reach another's data
- Three-class Redis token-bucket rate limiting (anonymous / authenticated / AI operations)
- Structured JSON logs with request correlation, secret redaction, and transcript hashing
- Reversible Alembic migrations, verified in CI against the same pgvector image Compose uses

## Evaluation approach

Six independently runnable suites, so a regression can be attributed to a stage rather than to "the
system":

```
stt · retrieval · agent-tools · response-quality · voice-latency · end-to-end
```

Each suite consumes a versioned dataset, writes a row to `evaluation_runs`, and logs to MLflow with
the git SHA. Changes that affect AI behaviour must ship as an experiment (baseline vs. candidate,
one variable changed) recorded in `experiments`. Methodology, including the known weaknesses of WER
for Tamil and romanized Hinglish and the self-preference bias of LLM judges, is in
[`docs/EVALUATION.md`](docs/EVALUATION.md).

## Honesty rules

These are enforced in review and in the audit gates:

1. No latency, accuracy, or quality number appears in any document unless it was produced by a
   recorded run and is traceable to an `evaluation_runs.id`.
2. "Complete" means tested and measured, not "code exists".
3. Limitations are documented in the same place as the capability, not in a separate apology
   section.
4. Failures get a file in `docs/failure_cases/`, including the ones that are still unfixed.

## Known limitations (design-stage, already identified)

These are architectural facts, not TODOs that will quietly disappear:

- **No GPU in the target dev environment** (4 vCPU / 15 GB). Real-time-quality local ASR and Indic
  TTS are not achievable on CPU; the real-time path therefore depends on managed providers, and
  local models are used for offline evaluation and deterministic CI. See
  [ADR-0002](docs/adr/0002-stt-provider-strategy.md), [ADR-0003](docs/adr/0003-tts-provider-strategy.md).
- **Whisper is not a streaming model.** Partial transcripts come from a chunked pseudo-streaming
  policy (LocalAgreement) and are unstable by construction. See [ADR-0002](docs/adr/0002-stt-provider-strategy.md).
- **Lexical retrieval is weak for Devanagari and Tamil script** because PostgreSQL ships no stemmer
  for either. See [ADR-0005](docs/adr/0005-vector-store-pgvector.md), [M-02 in the audit](docs/PHASE_0_AUDIT.md).
- **Romanized Hinglish language ID is an open problem**, not a solved sub-task. It is scoped as an
  experiment with a documented baseline. See [ADR-0011](docs/adr/0011-language-detection-strategy.md).
- **No acoustic echo cancellation.** Without headphones the system can hear its own TTS and
  self-interrupt. See [R-07 in the risk register](docs/RISKS.md).
- **Tamil is not in the MVP.** Nothing in the architecture is Tamil-specific except datasets and
  voice selection, but the language claim stays at three until Tamil is measured
  ([M-01](docs/PHASE_0_AUDIT.md)).

## License & data

Code: TBD (Phase 1). Course material used for RAG must be license-cleared before ingestion; no
student voice data or personal data is committed to this repository. See
[`docs/DATASET.md`](docs/DATASET.md).
