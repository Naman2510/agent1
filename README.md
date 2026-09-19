# VaaniOS

A multilingual conversational AI voice mentor for Indian students — **English, Hindi, and Hinglish
(code-switched)** in the MVP, with **Tamil deferred to a later phase** — built as a **measurable**
voice pipeline rather than a thin wrapper around an LLM API.

---

## Project status

| | |
|---|---|
| **Current phase** | Phase 5 complete — RAG: ingestion, hybrid retrieval, citations |
| **Implementation** | Phase 5 complete — 541 tests. Voice loop with barge-in, language routing, and a working retrieval pipeline; no real ASR/TTS provider, no agent tools yet. |
| **Benchmarks** | Two suites have run: language identification (0.9205 signal accuracy) and retrieval (hybrid RRF: recall@10 0.955, nDCG@10 0.893 on `datasets/v1`, 22 cases) — both with documented biases and known gaps. Everything else is still unmeasured. |
| **Last updated** | 2026-09-19 |

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
pip install -e ".[dev,rag]"
export VAANIOS_TEST_DATABASE_URL=postgresql+asyncpg://vaanios:vaanios@localhost:5432/vaanios_test
pytest -q                       # 541 tests
pytest -q tests/unit            # 200+ of them need no database at all
python scripts/fetch_models.sh  # Silero VAD weights (not committed)
python scripts/bench_voice.py   # pipeline overhead, with real numbers
ruff check . && mypy app
```

Without a Docker daemon, `scripts/dev_db.sh start` brings up a local cluster instead (no pgvector,
so it is only sufficient through Phase 4).

## What works today

You can hold a **typed** conversation with the mentor, grounded in real course material with
inspectable citations. Agent tools and memory are Phase 6.

**Phase 5 — RAG**
- Structure-aware Markdown/PDF ingestion: headings define chunk boundaries, and each chunk's full
  heading path (`Unit 5 > Chapter 12 > 12.2 Displacement current`) is prefixed onto the text before
  embedding — a cheap retrieval win, and what makes citations human-readable
- Hybrid retrieval — real pgvector HNSW cosine search fused with PostgreSQL full-text search via
  **Reciprocal Rank Fusion**, both arms independently testable for ablation
- **A real, working embedder** (TF-IDF + truncated SVD) substituting for the originally-planned
  `multilingual-e5-base`, because the sandbox has no route to HuggingFace Hub — documented as a
  substitution, not a supersession, in [ADR-0006's amendment](docs/adr/0006-embedding-model.md)
- Citation IDs are scoped to one turn's retrieved context: a reference number the model invents
  resolves to nothing, proven end-to-end from a real ingested corpus through real retrieval
- **The retrieval eval suite, with a real ablation grid**: `python -m eval.runner --suite retrieval
  --dataset v1` — vector-only, lexical-only, and hybrid RRF, plus an offline real-BM25 reference run
  that quantifies exactly how much the shipped lexical arm loses by not having IDF weighting
- Two honest findings written up as failure cases: [FC-003](docs/failure_cases/003-lexical-arm-lacks-idf-weighting.md)
  (the lexical arm's IDF gap, with a concrete case) and
  [FC-004](docs/failure_cases/004-cross-lingual-retrieval-degrades-to-zero-signal.md) (the
  TF-IDF/SVD substitute has no cross-lingual capability by construction)

**Phase 1 — foundation**
- Registration, login, `/auth/me`, profile update, and **account erasure** (hard delete, cascading)
- Access tokens (15 min) with **single-use refresh tokens**; replaying a rotated token revokes the
  whole rotation family
- Conversation sessions and transcript reads, scoped so one student cannot reach another's data
- Three-class Redis token-bucket rate limiting (anonymous / authenticated / AI operations)
- Structured JSON logs with request correlation, secret redaction, and transcript hashing
- Reversible Alembic migrations, verified in CI against the same pgvector image Compose uses

**Phase 4 — language routing**
- Unicode script detection (Devanagari, Tamil) — settled by codepoints, **1.000 recall**
- A romanized-Hinglish classifier built on Hindi *grammatical scaffolding*, because the content
  words in code-switched speech are routinely English on purpose
- Sticky session language with hysteresis: the mentor mirrors the student's language immediately,
  but the conversation's default moves only after two consecutive turns — so "ok" cannot redefine
  it
- Per-turn response directives placed *after* the cache breakpoints, so routing never invalidates
  the prompt cache
- **The first working eval suite**: `python -m eval.runner --suite lid --dataset v1`

**Phase 3 — the voice loop**
- A WebSocket carrying 20 ms PCM frames up and synthesised audio down, with a `[turn_id][seq]`
  fencing header so either end can drop audio from a turn that has ended
- **Real barge-in**: the client is told to flush first (audible silence is what the student
  experiences), then generation and synthesis are cancelled server-side, and the assistant turn is
  stored as *the prefix that actually reached the speaker*
- **Silero VAD v5** running for real at **0.12 ms per 32 ms window — 0.38% of one core**
- A 500 ms audio pre-roll, so an interrupting "Wait, stop" doesn't reach the recogniser as "stop"
- A turn state machine whose 19 legal transitions and all 49 illegal ones are tested
- Multilingual sentence chunking (Devanagari danda, no splitting inside "3.5 kΩ" or "e.g.")
- Nine stage marks persisted per turn, and a minimal browser client

**Phase 2 — providers and the LLM path**
- Six provider interfaces (`LLMProvider`, `STTProvider`, `TTSProvider`, `EmbeddingProvider`,
  `RerankerProvider`, `VectorStore`) with deterministic fakes, selected by config
- A Claude adapter: token streaming, adaptive thinking, `effort`, strict tool schemas,
  cache breakpoints on the stable prefix, refusal handled as a stop reason rather than a hang
- `POST /v1/sessions/{id}/messages` streams a turn over SSE and persists both messages with
  token usage, estimated cost, and time-to-first-token
- A spend ceiling and a daily voice-minute meter, in integer micro-dollars
- **The interrupted-turn invariant is already enforced and tested**: abandon the stream mid-answer
  and what gets stored is what was delivered, not what was generated

```bash
# no API key needed — the deterministic fake provider answers
VAANIOS_LLM_PROVIDER=fake docker compose -f infra/compose.yaml up --build
curl -N -X POST localhost:8000/v1/sessions/$SID/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Kirchhoff ka voltage law samjhao"}'
```

**What is not verified.** Three things, and they are the honest boundary of this project today:

1. **No real ASR or TTS.** The voice loop is complete and *provider-less* — every mechanism is
   tested and no word has been transcribed or synthesised by a real model. `build_stt`/`build_tts`
   raise for anything but the fake, deliberately, so nothing can silently serve a fake in
   production. ([M3-03](docs/PHASE_3_AUDIT.md))
2. **The Claude adapter has never run against the live API** — no credential where it was built.
   Every parameter it sends was checked against the installed SDK's signatures;
   `backend/scripts/smoke_llm.py` is the live check. ([M2-01](docs/PHASE_2_AUDIT.md))
3. **The LID baseline measures internal consistency, not accuracy.** The 88 cases were authored
   by the same person who wrote the lexicon they test — the strongest available bias, recorded at
   severity `high` in `datasets/v1/MANIFEST.yaml`. The `mixed` class sits at 0.625 recall and was
   **deliberately not tuned**, because adjusting two constants until a self-authored suite scores
   100% is a better number and a worse system. ([M4-01](docs/PHASE_4_AUDIT.md))
4. **There is no TTFA number.** What was measured is our pipeline's own overhead with fake
   providers (~0.4% of one core). Real TTFA is set by the ASR round trip, LLM time-to-first-token
   and TTS time-to-first-byte. ([M3-01](docs/PHASE_3_AUDIT.md))
5. **The retrieval numbers are measured on a 5-document, 19-chunk, self-authored corpus.** Hybrid
   RRF's recall@10 is 0.955 on 22 labelled queries — real, reproducible, and far too small a corpus
   to say anything about recall at production scale. The embedder itself is a TF-IDF/SVD substitute
   for the planned `multilingual-e5-base` (no route to HuggingFace Hub in this sandbox), which has
   **no cross-lingual retrieval capability by construction** — a pure-script Hindi query against
   this English-only corpus returns nothing, honestly, rather than a wrong answer.
   ([FC-004](docs/failure_cases/004-cross-lingual-retrieval-degrades-to-zero-signal.md))

The browser client (`frontend/voice-client.html`) was also written without a browser to run it in,
and says so at the top of the page.

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
- **The lexical retrieval arm has no IDF weighting.** PostgreSQL's `ts_rank_cd` is cover-density
  ranking, not BM25 — a common word can outrank a rare, diagnostic one. Measured directly (a query
  for "What does KVL state?" ties an off-topic chunk against the actual KVL definition) and
  quantified against a real offline BM25 reference in the eval suite. See
  [FC-003](docs/failure_cases/003-lexical-arm-lacks-idf-weighting.md).
- **The embedder has no cross-lingual capability.** The shipped TF-IDF/SVD substitute is corpus-fit,
  not pretrained on parallel text, so a query in a different script than the corpus gets no vector
  signal at all. See [ADR-0006's amendment](docs/adr/0006-embedding-model.md) and
  [FC-004](docs/failure_cases/004-cross-lingual-retrieval-degrades-to-zero-signal.md).
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
