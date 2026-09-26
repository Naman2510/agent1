# Phase 7 Audit — Audit Gate 7

**Reviewed:** the web app — sign-in and its auth proxy, the session list and history, the voice
session, the typed session, the admin dashboard — and the backend work it needed: the dashboard's
aggregates, the voice socket's activity and citation frames, turn completion on playback drained,
citations stored with answers, and language routing for typed turns. Also the Docker images, the
Compose stack, CI, and the new end-to-end suite.
**Date:** 2026-09-26 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus Gate 7's own criterion (ROADMAP.md), each checked by
running something. 725 backend tests at 97% line coverage against real PostgreSQL and Redis; 35
frontend unit tests; and 14 Playwright tests in a real Chromium against the real backend, with the
real Silero VAD and a microphone playing recorded speech — run here from source, and in CI against
the Docker Compose stack built exactly as the README says (this sandbox has no Docker daemon).
`ruff`, `mypy` (now including `backend/scripts/`), ESLint and `tsc` clean. CI passed on every job
for the first time since Phase 5 in run #28, and has stayed green since (#29, the first with the
Compose stack and the browser suite; #30).

**Outcome:** 23 defects found and fixed, three of them Critical — no spoken turn could ever begin,
the production image could not start, and the documented configuration could not start the
backend. 5 Major items scheduled, 6 Minor recorded.

**Gate status: PASSED.**

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| No hardcoded metrics anywhere in the UI | Every figure on screen comes from the API: the dashboard from `GET /v1/admin/health`, whose fields are all real queries (`tests/integration/test_admin_dashboard.py`); the voice panel's latency from the server's `metrics` frame; the transcript's from stored `latency_ms`. A search of `frontend/src` for literal figures in markup finds none. Before this phase the endpoint itself was the offender (D7-02). The E2E admin test checks the counts move with activity it has just created | pass |
| "Not measured" where no run exists | An average with no samples arrives as `"not_measured"` and renders as "— Not measured." with the reason, never as 0; a count is always a real number, including a real zero. E2E: speech-recognition failures, which nothing records, read "Not measured"; average time to first token becomes a measurement once a timed turn exists | pass |

The phase's deliverables (ROADMAP): the voice session UI with transcript, language indicator (on
each message; see m7-02), tool activity, citations and latency HUD; history; and the dashboard over
real aggregates. Tool activity and citations appear live and in history — the latter only since
D7-21 fixed their storage.

---

## 2. Defects found and fixed

### Voice

**D7-01 — Mid-turn failures never reached the client.** *Major.* `VoiceSession._run_turn` caught
only cancellation. Any other failure — concretely the spend cap refusing a turn before its first
token — escaped a detached task, and the session simply went quiet: no error frame, nothing to tell
a slow answer from a dead one. The turn now fires the state machine's provider-failure transitions
(specified and unit-tested in Phase 3, never driven), sends an `error` frame and returns to
listening. (98ebd59)

**D7-03 — A completed voice answer was stored as a snapshot of playback.** *Major.* Wiring the
`rag.citations` frame exposed it. A finished turn stored `ledger.spoken_prefix()` as of the moment
*generation* ended — an empty string before the first playback acknowledgement, a truncated answer
after it — marked uninterrupted, with the rest discarded. The next turn's context lost the mentor's
own reply, and citation resolution and memory extraction ran on the fragment. A turn now stays in
SPEAKING until acknowledgements show playback drained (ARCHITECTURE §4.1), bounded by the unplayed
audio plus a grace, and a settled turn stores what was generated.
`test_a_completed_turn_stores_the_whole_answer_not_a_snapshot_of_playback`. (eae0266)

**D7-04 — The tail of an answer could not be interrupted.** *Major.* The same root: the session was
back in LISTENING while the last seconds still played, so a barge-in there was ignored and the
mentor talked over the student. Fixed by the same change;
`test_the_tail_of_an_answer_is_still_interruptible_after_generation_ends`.

**D7-05 — The playback ledger measured 24 kHz audio at the 16 kHz capture rate.** *Major.* Every
duration was overstated 1.5×, so an interrupted answer's stored prefix claimed words the student
never heard. The ledger now carries its sample rate. (eae0266)

**D7-06 — Stored prefixes glued sentences together** ("hai.Doosra"). *Minor.* The chunker dropped
the whitespace between sentences; chunks now carry their raw span, so a stored prefix is a true
prefix of the answer. (eae0266)

**D7-07 — Citation markers were spoken.** *Major: every cited answer.* The model cites as `[1]`, and
the synthesiser read the number aloud mid-sentence. Speech now drops exactly what the citation
extractor finds; the stored text keeps the markers. (860222c)

**D7-10 — The client's two protocol duties were unwritten.** *Major.* Microphone frames sent while
the mentor is thinking or speaking must carry `turn_id + 1`, or everything between a barge-in's
turn bump and the client hearing of it — the interrupting question itself — is fenced out. And
`played_ms` must come from the audio clock, net of output latency, per turn: the Phase 3 test page
reported the context's absolute clock, which claims a whole answer was heard the moment it arrived
(M3-05). Both are now in ARCHITECTURE §10, implemented in the client, and unit-tested.
(6ef7d0a, cc20c8f)

**D7-12 — The Silero VAD could never hear speech.** *Critical.* Silero v5 and later score each
512-sample window together with the 64 samples before it. The wrapper passed bare windows, and the
model then stays near zero: across a spoken sentence it peaked at 0.13, never reaching the 0.5
threshold. No spoken turn could ever have begun. It went unseen because every Silero test was
negative (silence, noise) and the state-machine tests use a scripted detector — and Phase 3's
"Silero cannot hear synthetic speech" was this bug, misdiagnosed (corrected in PHASE_3_AUDIT §5).
Found in a real browser with a fake microphone. The wrapper now feeds the context; a committed
speech fixture (`datasets/v1/voice/fixtures/`, synthetic and labelled so) backs positive tests.
(7bf060e)

### Security

**D7-08 — Rate limits trusted a caller-supplied `X-Forwarded-For`.** *Major.* The anonymous limit
keyed on the header's leftmost address from any caller, so rotating it gave every login attempt a
fresh bucket and the credential-stuffing limit never engaged. The key is now the peer uvicorn
reports, which honours the header only from `FORWARDED_ALLOW_IPS`. (4cefa3d)

**D7-09 — Voice sockets outlived their credentials.** *Major.* ARCHITECTURE §10 promised that
revoking a refresh-token family closes live voice connections; nothing did, and `session.reauth`
validated a token without renewing or bounding anything, so a revoked account kept talking for the
rest of the hour. A socket now lives only as long as its newest token (closing with 1008 "credential
expired"), and `session.reauth` — for the same user only — renews it. (6ef7d0a)

**D7-16 — Token refresh shared the credential-stuffing bucket.** *Major: availability.*
`/auth/refresh` used the 10-per-minute per-address anonymous bucket, and the web app refreshes on
every page load, so a few students behind one campus NAT would have locked each other out. Refresh
has its own bucket, 60 per minute per address. (f2b5d60)

### Data and API

**D7-02 — The dashboard's data source was mostly hardcoded.** *Major: Gate 7's own criterion.*
`GET /v1/admin/health` returned one real number and four literal `"not_measured"` strings. Every
field is now a real query — counts, tool usage by outcome, failures, time to first token, mastery,
memory updates. (421d7ed)

**D7-11 — A request's writes committed after its response.** *Major.* FastAPI runs a `yield`
dependency's teardown after the response by default, so a client could read a 201 before the row
existed. In the browser, registration's follow-up request raced the commit and signed the new
student straight back out; and a commit that failed would have been reported as a success. The
commit now precedes the response; streaming routes commit inside their stream.
`test_commit_before_response`. (5dfb21a)

**D7-19 — Every session read "0 questions".** *Minor.* `sessions.turn_count` had a column, an API
field and a place in the UI, and nothing wrote it. It now moves with each student message, in that
message's transaction; migration 0004 backfilled existing sessions. Found by the first E2E test.
(05f774f)

**D7-21 — Citations were never stored.** *Major: a Phase 7 deliverable, and the MVP line's
"inspectable citations".* They were resolved each turn, sent once over the voice socket, and lost:
history could not say where an answer came from, and a typed answer never said so at all. Typed
turns also lacked tool activity. Citations are now stored with the answer (migration 0005), returned
with history and in the typed stream's `done` event, and shown in the transcript. (fcba6ec)

**D7-22 — Typed turns skipped language routing.** *Major.* They were labelled by script alone, so
romanized Hindi was stored as English, and the mentor got no instruction about which language to
answer in. Typed turns now go through the same router; its state is rebuilt by replaying the
session's earlier questions (the router is pure), so an explicit "hindi mein" holds across requests
as it does over voice. (fcba6ec)

**D7-23 — The reference documents described Phases 0 and 1.** *Minor.* `docs/API.md` was still the
Phase 0 plan — endpoints never built, cursor pagination the API never had — and the OpenAPI drift
check it promised was never built. `db/schema.current.sql` held Phase 1's 8 tables;
`docs/SECURITY.md` said no control was implemented; ARCHITECTURE's layout and deployment sections
showed directories and services that do not exist, and its tool loop said "parallel" after Phase 6
made it sequential. All corrected. `docs/openapi.json` is now committed, and a test fails when the
API and it disagree. Also here: `scripts/bench_voice.py`, which the README tells people to run,
crashed after D7-05, because nothing type-checked `scripts/`; CI now does.

### Shipping: images, configuration, Compose, CI, phone

**D7-13 — There was no way to make an admin.** *Minor.* `promote_to_admin` existed and nothing
called it, so the dashboard was unreachable short of editing the database. `scripts/promote_admin.py`
wraps it; there is deliberately no HTTP route. (a0b13a4)

**D7-14 — The production image could not start.** *Critical.* Six packages the running server
imports (regex, scikit-learn, scipy, numpy, pypdf, onnxruntime) lived only in extras the image does
not install, and the image shipped without the VAD's weights. It went unseen because every test
environment installs the extras, and because CI had been red since Phase 5 — mypy could not resolve
the same packages — so no job after the unit tier had run in two phases. They are base dependencies
now; the weights are fetched at build time from a pinned tag and checked against a SHA-256; and a
guard test imports the server with every extra-only package blocked. (d7d98ce)

**D7-15 — The documented Docker setup could not work.** *Major.* Compose reads `.env` beside the
compose file, so the README's command failed on a missing secret. The LLM provider and API key never
reached the backend, so the README's "fake provider" command silently used Anthropic. And every
other `.env` setting was ignored — a monthly spend cap set there enforced nothing. Compose now takes
`--env-file`, passes `.env` to the backend and migration containers, and reserves the frontend's
fixed address, which the backend trusts for forwarded client addresses. (d7d98ce, 9bc0032)

**D7-17 — The documented configuration could not start the backend.** *Critical.*
`VAANIOS_CORS_ORIGINS=http://localhost:3000`, exactly as `.env.example` and `compose.yaml` set it,
failed `Settings()`: pydantic-settings decodes a list field from the environment as JSON before the
comma-splitting validator ever runs. The test claiming to cover the value passed it as a keyword
argument, which skips that decoding. The empty `VAANIOS_MONTHLY_SPEND_CAP_USD=` that `.env.example`
documents as "no cap" failed too. Both fixed; the tests now go through the environment, and one
loads `.env.example` itself, so a documented value that cannot start the app fails the suite.
(8020848)

**D7-18 — CI proved less than it claimed.** *Major: process.* With the unit job green again, the
backend job ran for the first time since Phase 5, and failed: CI never fetched the VAD's weights, so
ten voice-socket tests failed and eight Silero tests had been skipping — the D7-12 fix had never been
tested in CI. The image smoke test had never run, and would have failed (no database URL). And the
runtime-dependency guard passed only on a machine with a `backend/.env`. CI now fetches the pinned
weights, absent weights fail rather than skip under CI, the image smoke starts the image with
`.env.example`, and the guard runs in an empty directory. (90057a4, 35a0041)

**D7-20 — On a phone, the controls hid the voice status.** *Major: most students will be on phones.*
At 390 px, Stop, Mute and Hang up squeezed "Speaking" and "Listening — ask anything" to zero width.
The row now wraps. Found by the E2E phone-width test. (339129c)

Severity: 3 Critical (D7-12, D7-14, D7-17), 16 Major, 4 Minor. All fixed, each covered by a test
or a CI check that fails without the fix — for the Compose findings (D7-15), the CI job that brings
the stack up and drives it in a browser.

---

## 3. Major findings (scheduled)

**M7-01 — Nothing has run against a real model provider.** Carried unchanged from M2-01, M3-03 and
M6-02. The E2E suite drives the real capture path, socket, VAD, persistence and UI, but the words
are the fake STT's, the answers the scripted LLM's, and the audio the fake TTS's silence.
*Blocking for:* any claim about recognition, answer quality, voice quality or time to first audio.
*Scheduled:* a real STT and TTS adapter, and `scripts/smoke_llm.py` with a credential; Phase 8
measures latency.

**M7-02 — One browser, and no real phone.** The suite runs in Chromium, with phone widths emulated.
Unverified: Safari — its AudioWorklet and autoplay behaviour, and whether it keeps a `Secure` cookie
on `http://localhost` in the Compose setup (Chromium does: CI runs the production-mode web app over
plain HTTP) — Firefox, and a real device's audio stack (Bluetooth latency, the OS's echo
cancellation). *Scheduled:* WebKit and Firefox projects in the Playwright suite in Phase 9, and a
manual pass on a real Android phone and iPhone before any user test.

**M7-03 — The VAD's thresholds are library defaults, untuned on human speech.** The only speech
fixture is synthetic (espeak-ng), because no consented human recording exists here. *Scheduled:*
tune on the first consented recordings (DATASET.md), keeping the E2E recordings as a floor.

**M7-04 — The web app sends no security headers, and the SECURITY.md checklist is unreconciled.**
No Content-Security-Policy, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors` or
`Permissions-Policy: microphone=(self)`. The checklist stands as Phase 0 left it (its claim that
nothing is implemented is corrected). *Scheduled:* Gate 9's criterion — every item ticked with its
evidence or accepted with a reason; headers in `next.config.ts`, with a nonce-based CSP through the
proxy as the Next.js guide describes.

**M7-05 — M6-01 is still open.** Phase 6's audit sequenced "a quiz is in progress" session state
alongside this phase; it was not done. A bare quiz answer ("5 ohms") can still fail to reach
`update_student_progress`. Carried forward.

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m7-01 | The barge-in grace wait sits after the interrupted turn is stored | `_barge_in` cancels the turn, whose cleanup stores the spoken prefix, and only then waits `ack_grace_ms` for a last acknowledgement — which can then improve the log line but not the record. The stored prefix can under-count by up to one acknowledgement interval (≤ 200 ms of audio), never over-count. If it matters: wait for the final acknowledgement, bounded, before cancelling, at the cost of up to that grace in discarded generation |
| m7-02 | The live voice panel has no language indicator | The routed language shows on each message in the transcript as soon as the turn ends. The live `stt.final` frame carries only the recogniser's hint, which the router deliberately overrides — recognisers label romanized Hindi as English — so showing it live would be wrong in exactly the case that matters. Showing the routed language live needs it added to a frame |
| m7-03 | The spoken E2E tests depend on real time | The fake microphone plays in real time, so they have margins, not guarantees: the interruption starts about 1.3 s after the question ends, against a ~2.2 s answer. They have passed on every run, here and in CI; if one flakes, widen the recording's gaps (`frontend/e2e/support/audio.ts`) rather than add retries |
| m7-04 | No component-test harness in the frontend | Vitest runs in Node; rendering is covered by the E2E suite instead, including a stubbed-response test for sources and tools whose shape the backend's tests pin. Accepted |
| m7-05 | A frontend newer than its backend breaks the transcript | Seen in development, against a backend that predated migration 0005: messages without `citations` crash the transcript. The images and Compose ship both halves together; a split deployment would need ordering or tolerant parsing |
| m7-06 | Compose waits up to 30 s for the backend's first health check | The image's `HEALTHCHECK` has no `--start-interval` (Docker 25 and later only), so the web app starts up to 30 s after the backend is ready. Accepted for compatibility |

---

## 5. Dimensions reviewed with no finding above Minor

**Architecture consistency.** The web app keeps ARCHITECTURE's split: every provider call is
server-side, and the browser talks only to the backend (the API and the voice socket) and to its own
auth proxy. Where the code contradicted the documents — the socket lifetime §10 promised, §4.1's
playback-drained rule — the code was brought to the documents. Where the documents were wrong — the
repository layout, services that do not exist, the tool loop's execution order — the documents were
corrected (D7-23).

**Unnecessary complexity.** No state library, data-fetching library or component library: a
47-line `useLoad`, `useSyncExternalStore` over the voice client, and ten component files. The
auth proxy is four route handlers. The end-to-end harness is one configuration with two modes —
start the stack from source, or drive a running one — rather than two harnesses.

**Technology compatibility.** Next.js 16 (App Router, standalone output) with React 19 and
Tailwind 4, following the version's own documentation where it departs from earlier releases.
Playwright is pinned to the browser build available here (1.56.1, Chromium 141), and Silero to its
v6.2 tag and checksum. Python dependencies are not pinned and CI installs the newest compatible
versions, which is why the OpenAPI check compares the contract rather than the rendered JSON.

**Scalability.** Unchanged from Gate 3: a voice session is sticky to one backend process
(ARCHITECTURE §15). History reads a session's messages and its tool calls in two queries, the
latter on a new `tool_calls (session_id, turn_index)` index, which also serves cascading deletes.

**External dependencies.** No new runtime service. Two new build-time downloads: the Silero weights
(pinned, checksummed) and, in CI only, Playwright's Chromium.

**Security.** Three findings (D7-08, D7-09, D7-16), and one new surface, the auth proxy: the refresh
token never reaches page script (E2E checks the cookie is `httpOnly` and absent from
`document.cookie`), cross-site requests are refused, and only the rightmost forwarded address is
passed on. E2E also checks that a student cannot open another's session and that a failed sign-in
does not reveal whether the account exists. Open: M7-04.

**Testing strategy.** Most of this phase's defects were found by running the whole system — a real
browser, a real image, the documented commands — not by unit tests: D7-11, D7-12 and D7-20 in the
browser; D7-19 by the first E2E test; D7-14, D7-17 and D7-18 by making CI actually run. The lesson
repeated through the phase is that a check only counts where it runs: a test that passed because of
the developer's `.env` (D7-17, D7-18), a suite that skipped when its input was absent (D7-18), a CI
job that never ran because an earlier one was red (D7-14). Each is closed by making the check run
in the environment it claims to cover — ending with the end-to-end suite running against the
Compose stack itself.

**Evaluation strategy.** This phase adds no eval suite and makes no new quality claim. The one
number it touches, Silero's cost per window now that it receives its context, was re-measured (p50
0.13–0.19 ms over two runs of `scripts/bench_voice.py` at `fcba6ec`) rather than carried over from
Phase 3, where it was measured on the wrong input.

---

## 6. Gate decision

**PASSED.** Phase 8 (evaluation, experiments, observability) may begin.

Carried forward:
1. A real STT and TTS adapter, and a live LLM smoke run (M7-01; also M2-01, M3-03, M6-02, M6-04).
2. Real, consented speech and course material (M7-03, and the dataset-independence gap from Gates
   4–6).
3. "Quiz in progress" session state (M7-05, i.e. M6-01).

New from this gate:
4. WebKit and Firefox in the end-to-end suite, and a pass on real phones (M7-02).
5. Security headers and the checklist reconciliation, at Gate 9 (M7-04).
