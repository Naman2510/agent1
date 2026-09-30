# Phase 9 Audit — Audit Gate 9

**Reviewed:** failure analysis and hardening. That covers the failure cases, each dependency taken
down in turn, many students on one server, the security checklist item by item, and the defects
all four exposed, including three that CI found in this phase's own changes.
**Date:** 2026-09-30 · **Reviewer:** implementing engineer (self-audit).
**Method:** Gate 9's four criteria (ROADMAP.md) and the eight Gate dimensions, each checked by
running something:

- 862 backend tests (97% line coverage) against real PostgreSQL and Redis, on the CI dependency
  versions.
- 42 frontend unit tests, and 14 Playwright tests in a real browser under the new content policy.
- The ten tier-T1 evaluation configs against their baselines, and the migration round trip.
- A load harness driving up to 100 simultaneous voice students, with the server profiled at 50.
- The recogniser's tier-T2 runs on GitHub's runners.

`ruff`, `mypy`, ESLint and `tsc` are clean. CI's results are part of the evidence, and reading them
late is itself a finding (D9-22).

**Outcome:** 17 documented failure cases (10 fixed, 3 accepted, 4 open) and every dependency's
failure tested. One server process was measured at 1 to 100 students and serves about 50. The 29
security items are reconciled: 26 done in full, and 3 done except for a part accepted with its
reason. 22 defects were found and fixed, three of them Critical: a Redis outage stopped the
product, one lost database connection lost the session, and a process admitted only fifteen voice
students. Most were found by building what the criteria asked for. Three were found by CI, in this
phase's own work (D9-19 to D9-21), after its results had gone unread for a day (D9-22). One of
those is fixed only in part: the recogniser's baselines did not reproduce on the first Intel
runner (D9-21, FC-006).

**Gate status: PASSED** (§6).

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| At least eight documented failure cases with root causes and fixes | `docs/failure_cases/`, 17 cases, each with the input, the actual output verbatim, the mechanism, and the fix or why not: 10 fixed, 3 accepted as limitations with the reason, 4 open with their next step (FC-002, FC-005, FC-006, FC-014). Categories: language detection, retrieval, speech recognition, hallucination (FC-005's invented English), degradation, latency, interruption, load, cost control. Wrong tool selection and TTS pronunciation cannot be filed honestly without a real model and a real synthesiser (the index says so) | pass |
| Load behaviour under concurrent sessions | `docs/LOAD.md`: one server process with real PostgreSQL, Redis and Silero VAD, and a paced fake model, at 1–100 simultaneous voice students. Before the fixes: fifteen students, then handshake timeouts (FC-015). After: 50 students, 150 of 150 turns, first audio p50/p95 2.2/2.6 s against 1.9 s for one student; saturated at 75. A profile shows the VAD taking most of the CPU; sharing one model cut CPU at 50 students from 94% to 78%, and memory from 881 to 395 MB. What was not measured is stated (real providers, several processes, long sessions) | pass: one process; real providers not measured (M9-01) |
| Graceful degradation when each provider fails | `docs/DEGRADATION.md`: the language model, recogniser, synthesiser, embeddings, reranker, any tool's provider, Redis and PostgreSQL, each taken down in a test that asserts what the student gets and what is recorded. Three rules decide each row; nine rows were broken when first tested and are fixed (D9-01 to D9-08) | pass |
| Every security checklist item done or explicitly accepted with a reason | `docs/SECURITY.md` §6: all 29 items with a state and evidence. 26 are done in full. The other three are done except for one part each, accepted with the reason: no parse timeout for documents (no upload path exists), TLS termination left to the deployment (the application refuses non-TLS origins and sends HSTS), and base images pinned by version, not digest. Reconciling built the missing headers and found three controls broken or absent (D9-15 to D9-17) | pass |

---

## 2. Defects found and fixed

### Degradation (44af157)

**D9-01 — A Redis outage stopped the product.** *Critical.* Every priced turn ended in an error
after it had been answered, when the spend counter's write failed. A spend cap refused every turn,
no voice connection could open (the allowance check), and readiness went 503, which would take
every instance out of rotation. Redis holds only controls and a cache, so each control now fails
open, loudly, and readiness reports `degraded` with a 200. FC-007.

**D9-02 — A stalled model kept a voice student in silence for up to a minute and a half.**
*Major.* The SDK's 30 s read timeout times three attempts. `StallGuard` gives up after 20 s without
an event, and the student hears the apology. FC-008.

**D9-03 — A recogniser that never returned a final transcript froze the session.** *Major.* The
wait was unbounded and sat on the connection's receive path, so the session stopped hearing
anything, the next question included. It is now bounded at 10 s, and the student is asked to
repeat. FC-009.

**D9-04 — When the voice failed, the answer's text stopped too.** *Major.* The turn ended in
`turn_failed`. The answer now continues as text, with one `tts_failed` notice. FC-010.

**D9-05 — One database connection dropped by the server failed every later turn.** *Critical: the
session was unusable until the student reconnected.* This is D8-04's class by a second route, a
restart or failover. The recovery backstop, which ran only after a cancelled turn, now runs after
any failed turn and rolls back a transaction that can only be rolled back. FC-011.

**D9-06 — An embedding outage made every sourced answer an apology.** *Major.* The error escaped
the tool, and so did any `ProviderError` inside a tool. Retrieval now falls back to the lexical
arm, and a tool whose provider is down is an error the model can answer around. FC-013.

**D9-07 — PostgreSQL unreachable was an unhandled 500.** *Minor.* It is now `503
service_unavailable` with `Retry-After`, naming nothing.

**D9-08 — An apology after half an answer was glued to its last word, and spoken that way**
("voltages aroundSorry"). *Minor.* A word break now comes first.

### Measurement (2f42af8, abdb3cc)

**D9-09 — Speech end was stamped when the gate decided, not when the student stopped.** *Major.*
Every turn-end and first-audio number was measured from the end of the silence wait. That
understated them by the largest stage in the budget, about half a second. The gate now reports how
long the pause had lasted, and the mark is backdated by it (`turn_end_ms == 512` in the test).

**D9-10 — Password hashing ran on the event loop.** *Minor.* At the production cost that is about
20 ms per login or registration, during which no voice session on the process hears or says
anything. It now runs on a thread (argon2-cffi releases the GIL), and a test counts the loop's
ticks during three hashes.

### Load (8950d68)

**D9-11 — A server process admitted fifteen voice students; the sixteenth timed out connecting.**
*Critical.* Fifteen is the database pool. Each connection's pre-accept lookups held a pooled
connection until its first turn committed, and each turn held one through the model's answer and
the whole playback. The handler now commits before accept, and a turn hands its connection back
before every wait on a model. FC-015.

**D9-12 — An answer being recorded when its turn was cancelled was lost.** *Major.* A barge-in or
a closing connection that landed during the answer's final write cut it off mid-flush or
mid-commit. That write was the one in a turn that D8-04's `finish_then_cancel` did not cover. Under
load, after D9-11's fix, the write waits for a pooled connection, which made the window large: 10
and 7 broken transactions in two runs at 100 students. The record, its commit, its cost and the
memory tasks it starts are now one unit. FC-016.

**D9-13 — After a rolled-back turn, the connection's audio went unmetered.** *Major.* The rollback
expired the student's row, and the close read the id from it (`MissingGreenlet`): ten times at 100
students, and the voice allowance missed each connection's audio. FC-017.

**D9-14 — Every connection loaded its own copy of the VAD model.** *Major.* Each copy cost 9.7 MB
and 36 ms of the event loop, and fifty copies of the same weights competed for the CPU's caches.
The profile put the VAD at 71% of a core at 50 students. One ONNX session per process now serves
every connection, since the model holds no state. At 50 students first audio went from p50/p95
4.1/9.6 s to 2.2/2.6 s.

### Security (9374a6a)

**D9-15 — The daily voice allowance was enforced only at connect.** *Major: it is the control that
bounds voice spend.* A connection opened with a minute left could talk for its hour, and any
number of connections could be open at once. Usage is now metered every 5 s of audio, and the
connection that crosses the allowance is ended.

**D9-16 — Nothing limited how fast audio could arrive.** *Major.* Every 32 ms of audio costs a
VAD run on the event loop that all of a process's students share (D9-14), so one client sending
faster than real time degraded everyone else. Audio may now run at most 10 s ahead of the
connection's age.

**D9-17 — A control frame with a field of the wrong type ended the session.** *Minor.* The typed
accessor's error escaped the handler. It is now reported as `bad_control`, like a malformed frame,
and the conversation goes on.

**D9-18 — No security headers** (carried from Gate 7). *Major.* The API now sends `nosniff`,
`no-referrer`, `DENY`, `no-store` and a deny-all content policy on every response, HSTS in
production, and the same on unhandled 500s. Starlette answers those outside every middleware, and
the test found them bare. The frontend sends a content policy (scripts from its own origin,
connections to itself and the API, no framing), a `Permissions-Policy` that allows only the
microphone, and HSTS where TLS is served. The end-to-end suite passes under it.

### Found by CI (60b137c, b714d3f, d7f415e)

**D9-19 — FastAPI 0.142 began instrumenting itself.** *Major.* Released between two CI runs, it
added a second server span to every request whenever a tracer provider is installed. Given the
standard `OTEL_*` variables, it would also add OTLP exporters of its own, and its logs record
exception messages and validation failures, which SECURITY.md §5 keeps out of telemetry. It is
turned off in `create_app`, with FastAPI pinned to 0.142 or later for the switch. A test sets
`OTEL_EXPORTER_OTLP_ENDPOINT`, starts the application and finds nothing configured. Reproduced
locally by installing CI's versions.

**D9-20 — D9-11's fix broke the evaluation suites' isolation.** *Major, and introduced by this
phase.* The tool loop committed after each call, inside the transaction the agent and injection
suites never commit, so the first suite's actor was kept and the second could not create its own.
Committing is now the caller's decision (`run_agent_turn(after_tool_call=...)`): the conversation
service passes its release, and the suites pass nothing. Tests cover both sides.

**D9-21 — The recogniser's baselines did not reproduce on an Intel runner.** *Major; fixed in
part.* The first Intel runner T2 had (Xeon Platinum 8573C, AVX-512) matched neither baseline
written on the AMD EPYC 7763, with the same library versions and the same reported kernels.
English WER was 0.1273 against 0.1227, and EXP-013's gain +0.047 against +0.073, with the same
decision. One cause was found: oneDNN, inside CTranslate2, runs the encoder's convolutions with
kernels of its own choosing, AVX-512 on that machine. It is now pinned to AVX2. Whether that was
the only cause is not yet shown (§3, M9-04). FC-006 is reopened.

**D9-22 — CI's results were not read for a day.** *Major (process).* Four pushes went out while
CI was red: first on D9-19, then, behind it, on D9-20 and on the personal-data scan matching its
own sample strings once committed. T2's Intel failure (D9-21) waited just as long. Each fix was
verified locally before being pushed, but locally is not where these failed: CI had newer
dependencies and a different CPU. CI's result is now checked after every push. The dependencies
are pinned (`backend/constraints.txt`, 41680ba), which is the step Gate 8 committed to if
floating versions broke CI again (m8-06).

Severity: 3 Critical (D9-01, D9-05, D9-11), 15 Major, 4 Minor. All are fixed, D9-21 in part.

---

## 3. Major findings (scheduled)

**M9-01 — Still no real provider in the loop.** Carried from M8-01. Answers come from the scripted
model and audio from the fake synthesiser. The real recogniser runs only in T2, on synthetic
speech. So first-audio time, the providers' own latency and limits under load, and two failure
categories (the mentor's hallucinations, pronunciation) have no measurement. *Blocking for:* any
latency claim, and load planning beyond "our server". *Scheduled:* the first run with an API key
(tier T3 exists and runs when one does).

**M9-02 — Every number is on synthetic or self-authored data.** Carried from M8-02. *Blocking
for:* any claim about real students. *Scheduled:* the consented human slice (DATASET.md).

**M9-03 — The `response` and `e2e` suites and a calibrated judge do not exist.** Carried from
M8-03.

**M9-04 — The recogniser's baselines across CPU vendors.** D9-21's pin removes one demonstrated
cause. Whether it is the only one waits on the next Intel runner, and until then T2 fails there.
If it still differs, MKL's COMPATIBLE mode is next (documented as vendor-independent, and slower),
then a stated tolerance. FC-006.

**M9-05 — Capacity past one process is designed, not measured.** One process serves about 50
students. Beyond that the design is more processes behind session-sticky routing (ARCHITECTURE
§15), which is neither built into the Compose stack nor load-tested. Two unmeasured options could
raise the per-process number: batching the VAD across connections, and skipping it on digital
silence (which needs the voice suite re-run).

**M9-06 — The frontend's content policy allows inline scripts.** A nonce would stop an injected
inline script too, but it needs every page rendered per request. It is accepted because the app
renders no HTML from data. *Revisit:* before any feature that does.

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m9-01 | The load numbers come from a 4-vCPU container shared with the load client, and vary near saturation: at 50 students, p50 3.2 s in one run and 4.1 s in another, before the VAD fix | Stated in LOAD.md: one run per level is an indication, not a figure to plan by |
| m9-02 | In the load test the intent call and the memory extractor went to the unpaced default fake | Stated in LOAD.md. It shortens waits, and does not change what the server does |
| m9-03 | The unhandled-error handler sends the security headers itself, because Starlette answers those outside every middleware | Tested. A new handler outside the middleware stack would need the same |
| m9-04 | The personal-data scan finds shapes (addresses, Indian mobile, Aadhaar and PAN numbers), not names or voices | It keeps synthetic datasets synthetic. The consented human slice will need its own review (DATASET.md) |
| m9-05 | The gitleaks pre-commit hook is opt-in | CI scans the whole history on every push, so that remains the control |
| m9-06 | The profile and the VAD cost figures come from one machine, and the VAD's cost per window was 0.12 ms on 18 September and 0.22 ms on 30 September, with what changed not isolated | Both recorded (ARCHITECTURE §9.1, LOAD.md) |

---

## 5. Dimensions reviewed with no finding above Minor

**Architecture consistency.** Where load or failure showed the design's gaps, the design gained
the missing piece rather than an exception. A turn's database work now follows the rule that a
connection is held only while it is querying (D9-11), which is why a tool loop that commits for
its caller was wrong (D9-20). §9.1 now points at LOAD.md for what the VAD costs under load. §15's
"many sessions across workers" now has a measured number per worker.

**Unnecessary complexity.** Degradation is handled at each boundary by the component that owns it,
not by a framework. `StallGuard` is a 53-line wrapper around the model provider. The load harness is one script that starts the real
application. The security headers are one small ASGI middleware, a pure one so streamed answers
pass through unbuffered.

**Technology compatibility.** FastAPI 0.142's native telemetry (D9-19). Starlette 1.7 and
OpenTelemetry 1.45 were verified with the whole suite. oneDNN 3.1.1 inside CTranslate2 4.8.2
picks its own instruction set (D9-21). Next.js 16's header configuration was used as its bundled
documentation describes.

**Scalability.** LOAD.md, and M9-05.

**External dependencies.** No new runtime dependency. py-spy was used for the profile and was not
added. Every Python dependency is now pinned (`constraints.txt`); pip-audit and `npm audit` block
CI.

**Security.** §6 of SECURITY.md, item by item. Two of this phase's defects were cost controls
(D9-13 and D9-15), and one was a denial of service by a single client (D9-16).

**Testing strategy.** Every code fix has a test that fails without it, checked by reverting the
fix. The exception is D9-21's pin, whose evidence is the local probe and, still to come, the next
Intel runner. Two tests were made to fail fast instead of hanging when their fix is reverted.
What CI caught (D9-19 to D9-21) was not a gap in the tests but in the environment they ran in:
newer dependencies, and another CPU.

**Evaluation strategy.** The recogniser's reproducibility is recorded as it stands: exact on one
CPU model, not yet across vendors (M9-04). EXP-013's two runs are both recorded: the decision is
the same, and the size of the gain depends on the machine.

---

## 6. Gate decision

**PASSED.** Every criterion is met with its evidence, and every item on the security checklist is
done or accepted with a reason. Phase 10 (optional fine-tuning) may begin.

Carried forward:
1. A real LLM, recogniser and synthesiser in the loop, and full-stack latency (M9-01).
2. Human, consented speech and course material (M9-02).
3. The `response` and `e2e` suites and a judge (M9-03).
4. The recogniser's baselines across CPU vendors (M9-04, FC-006).
5. Capacity past one process (M9-05); a nonce-based content policy (M9-06).
