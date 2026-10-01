# VaaniOS

A multilingual conversational AI voice mentor for Indian students — **English, Hindi, and Hinglish
(code-switched)** in the MVP, with **Tamil deferred to a later phase** — built as a **measurable**
voice pipeline rather than a thin wrapper around an LLM API.

---

## Project status

| | |
|---|---|
| **Current phase** | Roadmap complete: Phases 0–10 have passed their gates. Phase 10 decided not to fine-tune the intent classifier until its prompted baseline is measured ([ADR-0017](docs/adr/0017-intent-classifier-not-fine-tuned.md)). What is not true yet is listed in [PHASE_10_AUDIT.md](docs/PHASE_10_AUDIT.md) §3: above all, no real model has run in the loop |
| **Implementation** | 884 backend tests (97% line coverage), 42 frontend unit tests and 14 end-to-end browser tests, all in CI — the end-to-end suite runs against the Docker Compose stack, built as documented. A local recogniser (faster-whisper) and a local voice (eSpeak NG) exist for evaluation and development; no managed recogniser or voice does, and the Claude adapter has never run against the live API. |
| **Benchmarks** | Six suites have run, each recorded, reproducible from its record, and checked in CI, on small self-authored or synthetic datasets with their biases documented: language identification (0.9205 signal accuracy), retrieval (hybrid RRF: recall@10 0.955, nDCG@10 0.893, 22 cases), agent tool gating (14/14 allowlist coverage, against a scripted model), prompt injection (19/19 attempted mutating calls blocked), the voice front end (a turn ends 575 ms after speech, in audio time, on synthetic speech) and recognition (English WER 0.123, exact on the CPU model that computed it and only compared on others ([FC-006](docs/failure_cases/006-stt-baseline-not-reproducible.md)); synthetic Hindi not recognised as Hindi at all). Three experiments decided: EXP-003 rejected, EXP-008 and EXP-013 inconclusive. Full-stack latency is unmeasured. |
| **Last updated** | 2026-09-30 |

> **Full-stack latency is not measured yet.** Latency figures in
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) are *budgets* (design targets), not results; the one
> measured timing is the voice front end's, in audio time on synthetic speech. Every number above is
> a recorded run (`evaluation_runs`, MLflow), reported in [`docs/EVALUATION.md`](docs/EVALUATION.md)
> beside the command that reproduces it and the dataset's biases; metrics there without a reported
> run are definitions, not scores. Experiments are in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).
> See [Honesty rules](#honesty-rules).

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
| [`docs/PHASE_0_AUDIT.md`](docs/PHASE_0_AUDIT.md) … [`PHASE_7_AUDIT.md`](docs/PHASE_7_AUDIT.md) | **The audit gates** — one per phase: what was found, what was fixed, what is still open |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | ADR index (16 records in `docs/adr/`) |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Entities, relationships, indexing strategy; the live schema in [`db/schema.current.sql`](db/schema.current.sql) |
| [`docs/API.md`](docs/API.md) | The HTTP API and the voice socket; the checked contract is [`docs/openapi.json`](docs/openapi.json) |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | The six eval suites, metric definitions, CI tiers, judge methodology |
| [`docs/DATASET.md`](docs/DATASET.md) | Dataset versioning, data-quality pipeline, PII policy, licensing |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model (incl. prompt injection via course material) and checklist |
| [`docs/RISKS.md`](docs/RISKS.md) | Risk register with triggers and mitigations |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phases, audit gates, and the MVP cut line |
| [`docs/failure_cases/`](docs/failure_cases/) | Documented failures — input, expected, actual, root cause, fix, result |
| [`frontend/README.md`](frontend/README.md) | The web app: layout, sign-in design, and how to run the end-to-end tests |

## Tech stack

**Frontend** Next.js 16 · React 19 · TypeScript · Tailwind 4 · Web Audio API (AudioWorklet)
**Backend** Python 3.11 · FastAPI · Pydantic v2 · asyncio · WebSockets
**Data** PostgreSQL 16 + pgvector · Redis 7 · SQLAlchemy 2 · Alembic
**Voice** Silero VAD v6.2 · STT and TTS behind interfaces — faster-whisper for evaluation and local
development, deterministic fakes otherwise (managed streaming providers are the plan,
[ADR-0002](docs/adr/0002-stt-provider-strategy.md))
**AI** Claude (`claude-opus-5`) via the Anthropic Python SDK · TF-IDF/SVD embeddings, standing in for
multilingual-e5 ([ADR-0006](docs/adr/0006-embedding-model.md)) · reranker interface, off by default
**Tests/Infra** pytest · Vitest · Playwright · Docker Compose · GitHub Actions (tiers T1–T3) · MLflow
(evaluation runs) · OpenTelemetry (one trace per voice turn)

Every model-facing component sits behind an interface (`STTProvider`, `TTSProvider`, `LLMProvider`,
`EmbeddingProvider`, `RerankerProvider`, `VectorStore`) so that A/B comparison is a config change,
not a rewrite — see [ADR-0016](docs/adr/0016-provider-abstraction-boundaries.md).

## Setup

```bash
cp .env.example .env
# set VAANIOS_JWT_SECRET — e.g. openssl rand -base64 48
docker compose --env-file .env -f infra/compose.yaml up --build
```

(`--env-file` matters: Compose otherwise looks for `.env` next to the compose file, in `infra/`.)

Postgres, Redis, migrations, the API and the web app come up together: the app on
`http://localhost:3000`, the API on `http://localhost:8000` with interactive docs at `/docs`
(disabled in production builds). Make an account in the app, then give it the admin role with
`docker compose --env-file .env -f infra/compose.yaml exec backend python scripts/promote_admin.py you@example.com`.

```bash
curl localhost:8000/v1/health   # {"status":"ok",...}
curl localhost:8000/v1/ready    # per-dependency readiness
```

**To hear the mentor speak,** add the local-voice overlay. It builds the backend with eSpeak NG
and selects it, so answers are spoken in a robotic voice instead of the fake's silence (ADR-0018).
The recogniser is still the fake unless `.env` says otherwise:

```bash
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-voice.yaml up --build
```

**Running the tests** needs a PostgreSQL to point at — the suite runs the real migrations against a
real database rather than a stand-in, because the schema relies on enums, JSONB, citext, partial
indexes and check constraints:

```bash
cd backend
pip install -c constraints.txt -e ".[dev,rag,eval]"   # the versions CI tests
export VAANIOS_TEST_DATABASE_URL=postgresql+asyncpg://vaanios:vaanios@localhost:5432/vaanios_test
bash scripts/fetch_models.sh    # Silero VAD weights (not committed)
pytest -q                       # 884 tests
pytest -q tests/unit            # 612 of them need no database at all
python scripts/bench_voice.py   # pipeline overhead, with real numbers
ruff check . && mypy
```

The web app's checks, and the end-to-end suite that drives a real browser against the whole stack,
are in [`frontend/README.md`](frontend/README.md).

Without a Docker daemon, `scripts/dev_db.sh start` brings up a local cluster instead (no pgvector,
so it is only sufficient through Phase 4).

## What works today

In the web app you can hold a **spoken or typed** conversation with the mentor, interrupt it by
speaking over it or pressing Stop, and see where each answer came from — its sources and the tools
it used, kept in the session's history. By default it runs against the deterministic fake STT,
TTS and LLM, so the words heard and spoken are placeholders. The answers can be spoken by a real,
local voice (eSpeak NG: robotic, in English, Hindi and Tamil) with
`VAANIOS_TTS_PROVIDER=espeak`, and in the Compose stack with the overlay below. See [What is not
verified](#what-works-today).

**Phase 9 — failure analysis and hardening**
- 17 failure cases, each with the input, the output verbatim and the mechanism
  ([docs/failure_cases](docs/failure_cases/README.md)). Ten are fixed, four accepted as
  limitations, and three open with their next step
- Every dependency taken down in a test, with what the student gets
  ([DEGRADATION.md](docs/DEGRADATION.md)): a model that stalls is given up on after 20 s with an
  apology, a lost voice finishes the answer in text, and a Redis outage costs the counters, not the
  conversation
- Many students on one server ([LOAD.md](docs/LOAD.md)). One process serves about 50 connected voice
  students, with first audio within 0.7 s of a lone student's (p95). Past that, add processes
- The security checklist reconciled item by item ([SECURITY.md §6](docs/SECURITY.md)): security
  headers on the API and the web app, a voice allowance enforced while a connection is open, and a
  cap on how fast audio may arrive. Also blocking dependency audits, and a scan that keeps personal
  data out of the repository
- Found on the way, and fixed: a Redis outage stopped the product; a server process admitted
  fifteen voice students; a cancelled answer lost its record; an unmetered connection. 22 defects
  in all, in [PHASE_9_AUDIT.md](docs/PHASE_9_AUDIT.md)

**Phase 8 — evaluation, experiments, observability**
- Every evaluation run is recorded — config, dataset digest, git SHA, every case — and runs again
  from that record alone: `python -m eval.runner --reproduce RUN_ID`. CI re-runs every committed
  config against its baseline on every push, on a machine that did not record it
- The voice suite: the production voice session, with the real VAD, fed synthetic speech 20 ms at
  a time and measured in audio time — when a question is heard, when its turn ends, whether the
  student is cut off, whether noise becomes a turn. The recognition suite: faster-whisper, nightly
- Experiments registered with their decision rule and a written prediction before either run:
  semantic endpointing **rejected** (227 ms faster, but it cut off students who open with a
  sentence), heading-path prefixing **inconclusive** ([EXPERIMENTS.md](docs/EXPERIMENTS.md))
- One OpenTelemetry trace per voice turn, with its stages, and nothing the student said in it
- The admin dashboard's evaluation runs, experiments and failing cases
- Found on the way, and fixed: the turn detector was never consulted; a question cut off by a pause
  was answered by halves; an interruption landing mid-query broke every later turn. Fourteen
  defects in all, in [PHASE_8_AUDIT.md](docs/PHASE_8_AUDIT.md)

**Phase 7 — the web app**
- The voice session: live state and captions, Stop / Mute / Hang up, a typed fallback, the tools
  the mentor called, the sources it cited, and per-stage latency. The microphone is captured by an
  AudioWorklet (16 kHz, 20 ms frames), and playback is acknowledged from the audio clock, so the
  stored answer is exactly what the student heard — the whole answer, or the prefix they interrupted
- History: every session, each answer with its sources, tools, language and time to first word
- Sign-in keeps the refresh token in an `httpOnly` cookie behind a same-origin auth proxy; page
  script only ever holds the 15-minute access token, and refreshes are serialised across tabs
- An admin dashboard over real aggregates, showing "not measured" wherever no sample exists
- **An end-to-end suite in a real browser** (14 tests): a spoken question and a spoken interruption
  through the real VAD, Stop, typed sessions, sign-in, another student's session, the admin
  dashboard, and every page at phone width. CI runs it against the Docker Compose stack, brought up
  exactly as [Setup](#setup) describes
- Found on the way, and fixed: the VAD could not hear speech at all; completed voice answers were
  stored empty or truncated; the documented Docker setup could not start; citations were never
  stored. Twenty-three defects in all, in [PHASE_7_AUDIT.md](docs/PHASE_7_AUDIT.md)

**Phase 6 — agent tools and memory**
- Seven typed tools — course search, progress, study plans, quizzes, past sessions — offered per
  intent and re-checked at execution, with budgets of 3 rounds, 6 calls and 2.5 s per turn
- Student identity is never a tool argument; mutating tools check ownership themselves
- Two-tier memory: a short-term Redis window with a rolling summary, and long-term profile and topic
  mastery updated by an audited extractor that records every proposed change
- The prompt-injection suite: 19/19 attempted mutating calls blocked, checked against real row
  counts, under a scripted model already persuaded by the injected text

**Phase 5 — RAG**
- Structure-aware Markdown/PDF ingestion: headings define chunk boundaries, and each chunk's full
  heading path (`Unit 5 > Chapter 12 > 12.2 Displacement current`) is prefixed onto the text before
  embedding, and makes citations human-readable. Whether it helps retrieval, this corpus could not
  show (EXP-008: inconclusive)
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
- **Silero VAD v6.2** at **0.13–0.19 ms per 32 ms window** (p50 over two runs of
  `scripts/bench_voice.py` at `fcba6ec`, under 1% of one core). Until Phase 7 it was fed windows
  without the context the model needs, and could not hear speech at all
  ([D7-12](docs/PHASE_7_AUDIT.md))
- A 500 ms audio pre-roll, so an interrupting "Wait, stop" doesn't reach the recogniser as "stop"
- A turn state machine whose 19 legal transitions and all 49 illegal ones are tested
- Multilingual sentence chunking (Devanagari danda, no splitting inside "3.5 kΩ" or "e.g.")
- Nine stage marks persisted per turn

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
VAANIOS_LLM_PROVIDER=fake docker compose --env-file .env -f infra/compose.yaml up --build
curl -N -X POST localhost:8000/v1/sessions/$SID/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Kirchhoff ka voltage law samjhao"}'
```

**What is not verified.** These are the honest boundary of this project today:

1. **No managed voice or recogniser, only local ones.** A local voice speaks answers: eSpeak NG, a
   formant synthesiser, robotic and the same on every run (`VAANIOS_TTS_PROVIDER=espeak`,
   ADR-0018). It says nothing about how a neural or managed voice would sound. A real recogniser
   exists — faster-whisper, for evaluation and local development
   (`VAANIOS_STT_PROVIDER=faster-whisper`) — and has only ever heard synthetic speech: it runs in CI,
   because its weights cannot be downloaded where this was built. The managed streaming recogniser
   the real-time path needs does not exist. `build_stt`/`build_tts` raise for anything they do not
   know, so nothing can silently serve a fake in production. ([M8-01](docs/PHASE_8_AUDIT.md))
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

6. **One browser, and no real phone.** The end-to-end suite runs in Chromium, with phone widths
   emulated; Safari and Firefox are untested, and so is a real device's audio stack.
   ([M7-02](docs/PHASE_7_AUDIT.md))

## Evaluation approach

Independently runnable suites, so a regression can be attributed to a stage rather than to "the
system". Six run today; two more need a live model ([M8-03](docs/PHASE_8_AUDIT.md)):

```
lid · stt · retrieval · agent · injection · voice          (planned: response · e2e)
```

`python -m eval.runner --suite <name>` runs one over its versioned dataset; `--record` keeps the run
— config, dataset digest, git SHA, every case — in `evaluation_runs` and MLflow, and `--reproduce
RUN_ID` runs it again from that record alone. CI checks every committed config against its baseline
on every push (the recogniser nightly, with its downloaded model). Changes that affect AI behaviour
ship as an experiment: two configs differing in one knob, and a decision rule and a prediction
registered before either run, decided and recorded in `experiments`
([EXPERIMENTS.md](docs/EXPERIMENTS.md)). Methodology, including the known weaknesses of WER for
Tamil and romanized Hinglish and the self-preference bias of LLM judges, is in
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
- **Whisper is not a streaming model.** The local adapter transcribes each utterance once, when it
  ends, so it sends no partial transcripts; a chunked pseudo-streaming policy (LocalAgreement) would
  give unstable ones, and is not built. See [ADR-0002](docs/adr/0002-stt-provider-strategy.md).
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
