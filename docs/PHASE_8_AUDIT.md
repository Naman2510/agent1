# Phase 8 Audit — Audit Gate 8

**Reviewed:** evaluation, experiments and observability — run recording and reproduction, MLflow,
committed baselines, the new `voice` and `stt` suites and their datasets, the decision rule and the
experiments decided with it, OpenTelemetry tracing, CI tiers T1–T3, the admin evaluation view — and
the voice-session defects the new suites exposed.
**Date:** 2026-09-27, with D8-15 added 2026-09-29 once CI tier T2 settled it · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus Gate 8's own criteria (ROADMAP.md), each checked by
running something: 813 backend tests against real PostgreSQL and Redis, 40 frontend unit tests, 14
Playwright tests in a real browser, every evaluation config re-run against its committed baseline on
every push, and the recogniser suite on GitHub's runners, where its model can be downloaded.
`ruff`, `mypy`, ESLint and `tsc` clean.

**Outcome:** 15 defects found and fixed, two of them Critical — the turn detector was never
consulted, so the experiment this phase exists to run could not have taken effect; and a
well-timed interruption broke every later turn of a voice session. 6 Major items scheduled, 6 Minor
recorded. Two experiments decided: one rejected, one inconclusive (EXP-013, registered in this phase,
was decided in the next: inconclusive).

**Gate status: PASSED.**

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Every suite reproducible from a recorded config | A run records `(suite, config, dataset digest, git SHA)` in `evaluation_runs`, every case in `evaluation_results`, and the same in MLflow; `python -m eval.runner --reproduce RUN_ID` runs it again from that record and fails unless every metric comes out identical, and refuses when the dataset has changed since (`tests/integration/test_eval_recording.py`). Each committed config's summary is a baseline in `backend/eval/baselines/`, and CI re-runs all ten T1 configs — `lid`, `retrieval` and four ablations, `agent`, `injection`, `voice` and EXP-003's candidate — against them on every push, on a machine that did not record them: exact on every one (first shown in run #33 for retrieval and #36 for voice, whose numbers pass through Silero and ONNX Runtime). `stt` is T2: its first baseline did not reproduce (D8-15); with sampling seeded and the arithmetic pinned, both `stt` configs' baselines are checked on every T2 run, and one has reproduced exactly on a second runner of the same CPU model | pass — across CPU vendors not yet shown (m8-01) |
| At least one experiment concluded `reject` or `inconclusive` | EXP-003, semantic endpointing: **rejected** — 227 ms faster on every question, and three more questions cut off, against a guard that allowed none. EXP-008, heading-path prefixing: **inconclusive** — +0.018 nDCG@10 with an interval spanning zero. Both registered, rule and written prediction included, and committed before either run ([EXPERIMENTS.md](EXPERIMENTS.md)) | pass |
| All suites runnable from one entrypoint | `python -m eval.runner` runs `lid`, `stt`, `retrieval`, `agent`, `injection` and `voice`, by suite, config, recorded run or registered experiment. Of the six suites EVALUATION.md plans, `response` and `e2e` do not exist: both need a live model (M8-03) | partial — see M8-03 |
| MLflow tracking | Every recorded run logs its config, digest and SHA as parameters and its summary as metrics, to a SQLite store (MLflow 3 no longer accepts a file store); tested against a temporary one | pass |
| OpenTelemetry tracing | One trace per voice turn with its stages, plus requests, generation, tools and retrieval (§2); a real OTLP export decoded in a test | pass |
| CI tiers T1–T3 | T1 on every push; T2 (`nightly.yml`) runs `stt` with its downloaded model; T3 (`live.yml`) runs the live adapter check by hand and skips, saying so, without a key. Scheduled and dispatched runs need the default branch (M8-05) | pass |
| EXP-001, EXP-003, EXP-007 written up | EXP-003 decided (rejected). EXP-001 and EXP-007 are written up as **blocked**, with what each needs: EXP-001 a managed ASR key and human speech (the `stt` suite it needs now exists), EXP-007 more than two Hindi queries | pass, as blocked |

---

## 2. Defects found and fixed

### Voice

**D8-02 — The turn detector was never consulted, and the recogniser heard nothing until the turn
was over.** *Critical: it made this phase's central experiment meaningless.* The session handed
the recogniser the whole utterance only after the turn had ended, so every `stt.partial` arrived
once the student had stopped, and during a pause there was no transcript to read. Worse, each
window of a pause *reset* the turn detector instead of consulting it: the VAD gate alone ended
turns, and semantic endpointing — EXP-003's candidate — could not have taken effect whatever its
switch said. Found while designing the voice suite, by reading the code the experiment would
measure. Frames now stream to the recogniser from the moment speech is confirmed, pre-roll first;
the gate reports how long a pause has lasted, and the detector reads the live stable prefix on each
such window. Tests fail without the fix, including two mutations: a detector never consulted, and
one not reset when speech resumes. (776ddab)

**D8-04 — An interruption that landed mid-query broke every later turn.** *Critical.* A voice
connection holds one database session for its whole life. A barge-in cancels the turn's task
wherever it is waiting; when that was a query, asyncpg abandoned the connection mid-protocol,
SQLAlchemy invalidated it, and every later turn on it failed with `turn_failed` until the student
reconnected. The tool loop's `asyncio.shield` did not help: it let the tool call run on while the
cancelled turn wrote its record on the same session, concurrently. Found by D8-03's tests, whose
compressed timing made the interruption land mid-query. `finish_then_cancel` now lets database
work finish before a cancellation proceeds, the question is stored inside the turn's `try`, and a
backstop rolls back a connection found invalidated. Checked by mutation: with neither protection
every turn fails; with the backstop alone only the interrupted turn's record is lost. (0454f38)

**D8-03 — ARCHITECTURE §5.6's continued-thought merge was never implemented.** *Major.* Speech that
resumes within 1.2 s of a turn's commit, before any answer is heard, should continue that question.
The session computed the condition and then set the text to carry forward to `""`: nothing was
carried, no test covered it, and the mentor was asked the second half alone. Now the whole question
is answered and stored once, in the cut-off turn's place; a cough that interrupted the thinking no
longer costs the student their question; and only speech merges, never the stop button or typed
text. (0454f38)

**D8-05 — A recogniser failing mid-sentence ended the connection.** *Major, latent until D8-02.*
Nothing caught a provider error from transcription; with the recogniser now working during speech,
a dropped connection mid-sentence would have escaped `handle_audio` and closed the socket. It is
now an `stt_failed` error frame, and the session listens again without spending a turn. (776ddab)

**D8-06 — A typed question left an utterance being captured, and its transcription running.**
*Minor.* (0454f38)

### Evaluation

**D8-01 — Retrieval's lexical ranking was not deterministic.** *Major: it made a baseline
impossible.* Chunks tied on `ts_rank_cd` came back in whatever order PostgreSQL stored them, so
lexical-only nDCG@10 moved between identical runs. Found by the first attempt to reproduce a
recorded run. Ties now break on the chunk's content hash; a test that stores the same chunks in
two orders fails without it. (53c028f)

**D8-07 — The pre-roll test did not test its claim.** *Minor.* It asserted only that the recogniser
heard something — true with no pre-roll at all. It now asserts the 500 ms before confirmation
arrives too. (776ddab)

**D8-08 — Tests wrote MLflow state into the repository.** *Minor.* MLflow's default store is the
working directory; an autouse fixture now points every test at a temporary one. (239e472)

**D8-09 — The runner reported an unavailable model as a traceback.** *Minor.* A suite that cannot
run here — faster-whisper's weights blocked by the network — now says so, with what it needs, and
exits 2. (ac96111)

### Shipping and documents

**D8-10 — CI went red on a dependency the development machine did not have.** *Major.* CI installs
the newest compatible versions; it resolved SQLAlchemy 2.1.1, which deprecates the `DISTINCT ON`
form the evaluation view used, and the test configuration turns deprecations raised from our code
into errors. Three tests failed in CI (run #38) and passed here, on 2.0.54. The query now uses a
window function both versions accept, and the development environment is on 2.1.1. (f365c5d)

**D8-11 — A failed schema dump emptied the committed schema.** *Minor.* `scripts/dump_schema.sh`
redirected straight into `db/schema.current.sql`; it now writes aside and moves into place on
success. (f2e6154)

**D8-12 — The schema documents said 17 of 20 tables after migration 0006 made it 20.** *Minor.*
(f2e6154)

**D8-13 — The API described itself as "Phase 1 … no voice loop, agent, or RAG yet".** *Minor.* In
every OpenAPI document since Phase 1. (df8dc20)

**D8-14 — ADR-0014's tracing did not exist.** *Major.* The accepted observability design — spans
per stage, with the marks as events — had no code behind it at all. Now: a voice turn is one trace,
from the end of speech to the end of the turn, with which rule ended the utterance and the outcome;
generation, tool calls and retrieval inside it; every request a span named by its route template.
Nothing the student said is ever an attribute, and a test scans every span of a turn for it. Off by
default; console or any OTLP collector when configured. (df8dc20)

**D8-15 — The `stt` baseline did not reproduce on a second runner.** *Major.* T2 wrote the first
baseline (ac96111, WER 0.4465) and the next run, on another runner, got 0.4182 — Hindi 1.383 then
1.255. Two causes, both measured on a Whisper-shaped CTranslate2 model (the real weights cannot be
downloaded here): Whisper's temperature fallback samples, seeded from the operating system, and
`set_random_seed` cannot reseed a model that has already sampled; and CTranslate2 and MKL choose
their arithmetic by CPU — four instruction sets, four encoder outputs. Each utterance is now decoded
by a seeded model of its own, the arithmetic is pinned before either library starts (CTranslate2 at
AVX2, MKL throughout, MKL's reproducible mode) and recorded in the summary, and T2 logs the CPU and
the kernels chosen. The language-hint baseline then reproduced exactly on a second runner — the same
CPU model (AMD EPYC 7763), so across vendors it is not yet shown (m8-01). FC-006. (bdcad75, f94fccd)

*Added 2026-09-30, in Phase 9:* the first Intel runner (4b3159a) reproduced neither baseline. One
cause, not covered by the pins above, is found: oneDNN inside CTranslate2 chose AVX-512 convolution
kernels there. It is now pinned. The libraries promise the same numbers only on the same CPU
model, so a baseline is now enforced on the model that computed it and compared on others.
PHASE_9_AUDIT.md (D9-21) and FC-006 have the rest.

Severity: 2 Critical (D8-02, D8-04), 6 Major (D8-01, D8-03, D8-05, D8-10, D8-14, D8-15), 7 Minor. All
fixed; each Critical and Major defect is covered by a test or a CI check that fails without the fix.

---

## 3. Major findings (scheduled)

**M8-01 — Still no run against a real LLM or TTS, so no full-stack latency.** Carried from M7-01.
The recogniser is real now (faster-whisper, in T2), but the answers are still the scripted model's
and the audio the fake synthesiser's, so time to first audio, LLM time to first token and TTS time
to first byte have no number (EVALUATION.md §5.4). T3 runs the adapter's live smoke test as soon
as an `ANTHROPIC_API_KEY` secret exists. *Scheduled:* Phase 9, with the provider-failure drills.

**M8-02 — Every number is on self-authored or synthetic data.** The language set, the retrieval
corpus and its labels were written by the pipeline's author; the voice and recognition sets are
eSpeak's. The synthetic Hindi is not even recognised as Hindi (EVALUATION.md §3), which says more
about the synthesiser and about language identification than about Hindi speakers. *Blocking
for:* any claim about real students. *Scheduled:* the consented human slice in DATASET.md, before
any user test.

**M8-03 — The `response` and `e2e` evaluation suites, and the LLM judge, do not exist.** Both suites
need a live model; the judge needs a human-labelled calibration set (EVALUATION.md §5.3). The
tables that would hold them stay empty. *Scheduled:* after M8-01.

**M8-04 — The voice suite measures endpointing, not barge-in.** Barge-in detection latency and
false barge-ins (noise or an acknowledgement stopping the mentor) have no cases; the recogniser
stand-in's 300 ms lag is an assumption the EXP-003 result depends on; and the turn detector's
completeness test is still terminal punctuation (EXP-012 registers the next hypothesis, deliberately
not tested on the data that suggested it). *Scheduled:* Phase 9 failure analysis.

**M8-05 — The scheduled and on-demand tiers need the default branch.** GitHub schedules and
dispatches a workflow only from the default branch, which this work has not reached: until it is
merged, T2 runs only on pushes that change what it measures, and T3 cannot be started.
*Scheduled:* on merge; nothing to change in the workflows.

**M8-06 — Gate 7's carried items stand.** WebKit, Firefox and real phones (M7-02); untuned VAD
thresholds (M7-03); security headers and the checklist (M7-04, Gate 9's criterion); quiz-in-progress
state (M7-05). None was in this phase's scope. *Scheduled:* Phase 9.

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m8-01 | Cross-machine reproducibility rests on floating point | Silero (ONNX Runtime) and the TF-IDF/SVD embedder (scikit-learn) matched exactly on GitHub's runners, but a CPU with other vector instructions could move a probability across a threshold by one 32 ms window — D8-15 is that, for the recogniser, and its pins are shown only on AMD runners so far. If a baseline check fails with no code change, compare runner CPUs (T2 logs them) before suspecting a regression |
| m8-02 | `stt` runs are not in `evaluation_runs` or MLflow | T2 has no database; its record is the committed baseline and the run's log and artifact. Adding a PostgreSQL service to T2 would record them, in a database that disappears with the runner |
| m8-03 | Speech-recognition failures are still "not measured" on the dashboard | They now reach the student as an `stt_failed` frame and the log, but nothing counts them |
| m8-04 | The OTLP path is tested against a local receiver, not a real collector | No collector runs in the Compose stack, by design (ARCHITECTURE §14) |
| m8-05 | The registered prediction has no column | It lives in the experiment's committed TOML, at the git SHA both runs record |
| m8-06 | Dependencies float in CI | The cost is D8-10. Accepted, with the development environment kept current; a lock file is the alternative if breakage repeats |

---

## 5. Dimensions reviewed with no finding above Minor

**Architecture consistency.** Where the code contradicted the documents, the code was brought to
them: the recogniser now hears the utterance as §4 and §5.5 describe (D8-02), §5.6's merge exists
(D8-03), §5.7's "cancellation waits for in-flight tool calls" is now what happens (D8-04), and
ADR-0014's spans exist (D8-14). Each fix added an "as built" paragraph to its section.

**Unnecessary complexity.** The evaluation layer is one runner, one recording module, one decision
module and a module per suite. The decision rule is a seeded bootstrap in 50 lines, not a
statistics package. The voice suite drives the production session instead of re-implementing its
logic, so what it measures cannot drift from what ships. The synthetic dataset is assembled at run
time from 66 parts, not stored as 48 finished recordings.

**Technology compatibility.** MLflow 3 (SQLite store), OpenTelemetry 1.4x with OTLP over HTTP,
faster-whisper 1.2 with CTranslate2 int8, eSpeak NG 1.51, SQLAlchemy 2.0 and 2.1 (D8-10). FastAPI
0.141 includes routers lazily, which hides a route's full template; the request span rebuilds it
from public values and never guesses.

**Scalability.** The recogniser now runs during speech, one streaming task per utterance, whose
queue is bounded by the 30 s utterance cap. Tracing is the API's no-op unless an exporter is
configured. faster-whisper loads once per process.

**External dependencies.** New Python packages: OpenTelemetry (base; the exporter imported only
when configured) and faster-whisper (the `voice-local` extra, never in the production image). New
downloads: faster-whisper's weights, in T2 only. None is reachable from this development
environment's network, which is why the recogniser's numbers come from CI.

**Security.** Traces are a new place data can go, so nothing a student said is an attribute —
utterances, queries, tool arguments — and a test scans every span of a turn for it. The evaluation
endpoints are admin-only (tested) and read-only; the failure browser shows evaluation cases, not
student data. The synthetic audio's exception to the repository's "no `.wav`" rule is scoped to two
folders, so recordings of people still cannot be committed by accident.

**Testing strategy.** This phase's two Critical defects were found by building an evaluation, not by
tests: D8-02 by reading the code an experiment would measure, D8-04 by the tests for D8-03. Every
fix in the voice session was mutation-checked — reverted in place to confirm its test fails — and
the voice suite itself is tested through the real VAD. The phase's recurring lesson is a
consequence of Phase 7's (a check counts only where it runs): a check is only as good as what it
compares against. Retrieval could not have a baseline until it was deterministic (D8-01), and a
dependency CI resolves differently from the development machine is a comparison nobody made
(D8-10).

**Evaluation strategy.** Every measured number in EVALUATION.md is now a recorded run, reproducible
from its record, checked in CI on every push (T1) or every night (T2), and paired with what it does
not show. The experiment program is honest in the way ROADMAP's gate asks: one idea rejected despite
a large win on its headline metric, one inconclusive at the size of this data, two blocked and said
so, and one follow-up registered but deliberately not tested on the data that suggested it.

---

## 6. Gate decision

**PASSED.** Phase 9 (failure analysis and hardening) may begin.

Carried forward:
1. A live LLM and TTS, and full-stack latency (M8-01; M7-01 before it).
2. Human, consented speech and course material (M8-02; M7-03 and the dataset gap from Gates 4–6).
3. The `response` and `e2e` suites and a calibrated judge (M8-03).
4. Barge-in cases in the voice suite; EXP-012 on fresh data (M8-04).
5. Gate 7's items: browsers and phones, VAD tuning, security headers and the checklist, quiz state
   (M8-06).
