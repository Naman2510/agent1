# Phase 6 Audit — Audit Gate 6

**Reviewed:** the seven agent tools with typed inputs, authorization, and budgets; the agentic
tool-calling loop (ADR-0009); `IntentGate` and its allowlist table; two-tier memory — the
short-term Redis window with rolling summary, the long-term `student_profiles`/`student_topics`
store, and the async `MemoryExtractor` with its `memory_events` audit trail; the prompt-injection
defense suite; and the agent (tool-use) evaluation suite.
**Date:** 2026-09-21 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus Phase 6's own three gate criteria (ROADMAP.md), each
checked by running something real — a real PostgreSQL database, a real Redis (via `fakeredis` in
the unit tier, a real server in integration), and the real orchestrator/executor — never asserted
from reading the code. 687 tests, 96% coverage on `app/` (92% including `eval/`, where
`eval/runner.py`'s CLI entrypoints are exercised by real runs against a live database rather than
by unit tests — the same carve-out Phase 4 and Phase 5 made for their own runners). `ruff` and
`mypy` clean.

**Outcome:** 7 defects found and fixed (one of them — a missing authorization check — the most
security-significant finding of this phase), 5 Major items scheduled, 4 Minor recorded.

**Gate status: PASSED.**

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Agent suite passing with gated-vs-ungated numbers | `datasets/v1/agent/scenarios.jsonl` (14 scenarios), `eval/suites/agent.py`. Allowlist coverage 14/14, pipeline completion 10/10 with 0 forbidden-tool leaks, gate-earns-its-place 5/5 probes. Full table and honest scope statement in [EVALUATION.md §5.1](EVALUATION.md) | pass |
| Injection suite shows zero mutating calls | `datasets/v1/agent/injection_cases.jsonl` (16 cases, 19 attempted calls), `eval/suites/injection.py`. 19/19 blocked, 0 executed, cross-checked against real Postgres row counts across every mutating table | pass |
| A memory delta is traceable end to end | `test_a_memory_delta_is_traceable_end_to_end_from_a_real_turn` (`tests/integration/test_memory_extractor.py`): a real `ConversationService.stream_turn` call, through the background extraction task, to a `student_topics` mastery update and a `memory_events` row referencing the exact session and message that produced it | pass |

Also verified: tool budgets (3 rounds / 6 calls / 2.5 s wall-clock) are enforced and degrade to a
spoken outcome rather than a stack trace; every tool input model forbids extra fields, so identity
can never arrive as a model-supplied argument (ARCHITECTURE §8.4); a turn's tool calls execute
sequentially even though the request that produced them is batched (`AsyncSession` is not safe for
concurrent coroutine use — see D6-01); and every Phase 2/3 conversation test still passes unchanged
against a `ConversationService` built without any Phase 6 dependency, proving the opt-in contract
holds.

---

## 2. Defects found and fixed

### D6-01 — Concurrent tool execution corrupted a shared database session
**Severity: major.** ADR-0009 calls for executing a round's tool calls "in parallel." The first
implementation did exactly that with `asyncio.gather()` over calls sharing one `ToolContext.db`.
A real test issuing two tool calls in one round crashed with
`sqlalchemy.exc.InvalidRequestError: Session is already flushing` — `AsyncSession` is not safe for
concurrent coroutine use, and one request-scoped connection could not provide true concurrency
regardless. Found by a real two-tool-call test, not by inspection.

**Fix:** a round's tool calls execute sequentially (each still individually `asyncio.shield`-ed
against cancellation, per Gate 0 finding C-04). ADR-0009's "one message" requirement is satisfied at
the message-batching level — every result from a round still returns to the model as one turn —
without needing concurrent execution the database connection could not have safely provided anyway.

### D6-02 — The intent allowlist was enforced at offer-time only, not at execution
**Severity: major — the load-bearing security rule of the whole agent (ARCHITECTURE §8.4), found
before it shipped rather than after.** `IntentGate`'s allowlist controlled which tool *schemas*
were sent to the model, but nothing stopped `execute_tool_call` from running a tool by name if one
was requested anyway. A strict JSON schema makes a model asking for an unoffered tool rare, but
rare is not impossible — a tool reachable only because the request happened not to include its
schema is not actually gated. Found while writing orchestrator tests, before any external review.

**Fix:** `execute_tool_call` takes `allowed_tool_names` and independently checks it, rejecting with
`NOT_ALLOWED_MESSAGE` and a `ToolStatus.REJECTED` audit row regardless of what the request offered.
This is now the mechanism the entire injection suite (§below) exercises 14 of its 16 cases against.

### D6-03 — `IntentGate.classify()` had no error handling of its own
**Severity: major.** Every other LLM call in `ConversationService` degrades to `FAILURE_REPLY` on a
`ProviderError`; the classification call, added when tools were wired into the live app, had no
such handling — a provider hiccup during classification would crash the whole turn instead of the
graceful degradation every other call already gets. Found by running the full suite after wiring
Phase 6 into the live application, not by inspecting the new code path in isolation.

**Fix:** `classify()`'s stream loop is wrapped in `try/except ProviderError: return DEFAULT_INTENT`
— a classifier hiccup now costs some tool precision, never the turn.

### D6-04 — `update_student_progress` was registered, tested, and unreachable
**Severity: major.** ARCHITECTURE §8.2's own tool-gating table never assigned
`update_student_progress` to any intent's allowlist — every other tool in the registry appeared in
at least one row, this one in none. The tool existed, had a full handler, and was unit-tested at
the handler level (`tests/integration/test_agent_tool_handlers.py`), but no real conversation could
ever reach it: `generate_quiz`'s own description tells the model to "call
`update_student_progress` with the result," a call the live allowlist would refuse regardless of
what the model did. This was not code drifting from the spec — the spec's own table had the gap
from the start, and the code faithfully implemented it.

**Fix:** `QUIZ_REQUEST`'s allowlist now includes `update_student_progress`, and the classifier's own
description was broadened to cover reporting or answering quiz questions already asked, not only
asking to be quizzed. ARCHITECTURE.md §8.2 and `test_intent_gate.py`'s verbatim-spec test were
updated together. **Not fully closed** — see M6-01.

### D6-05 — A background task could reference a message row before it was committed
**Severity: major — caught by a real foreign-key constraint, not by inspection.** `MemoryExtractor`
runs off the critical path on its own database session (deliberately, since sharing the
request-scoped session across concurrent coroutines is exactly D6-01). It writes a `memory_events`
row with a foreign key to the assistant message that triggered it. `ConversationService` persisted
that message on its own, request-scoped session and — before this fix — left committing it to the
request's outer transaction scope, which for a streaming response could still be open by the time
the independently-connected background task tried to insert. A real test without any artificial
delay hit `ForeignKeyViolationError: insert or update on table "memory_events" violates foreign
key constraint` deterministically, because nothing in the test ever committed the outer session.

**Fix:** `ConversationService` commits immediately after persisting the assistant turn, before
spawning any background work — every session it is built with sets `expire_on_commit=False`, so
nothing already loaded needs a re-fetch afterward. This also makes the "what is stored is what the
user actually received" invariant (module docstring, Gate 0 finding C-03) durable at the earliest
safe point rather than deferred to a transaction scope that a genuinely cancelled request might
never reach.

### D6-06 — Two prompt-injection defense claims in the agent scenario dataset were backwards
**Severity: minor — a dataset-authoring bug, not a code bug, but caught the same way a code bug
would be: by running it, not by proofreading it.** `agent-009` and `agent-014` (`scenarios.jsonl`)
listed `create_study_plan` as "forbidden" under the `study_plan` intent while checking that a
read-only request doesn't need it. `create_study_plan` is legitimately in `STUDY_PLAN`'s allowlist
(correctly — see `agent-008`), so the claim was simply wrong: `check_allowlist_coverage`, run for
real against the live `INTENT_TOOLS` table, failed both scenarios immediately.

**Fix:** both scenarios' `forbidden_tools` lists were corrected and their notes rewritten to state
what they actually demonstrate (a call being unnecessary for one task is a different fact from a
call being excluded by the gate). Left in `datasets/v1/MANIFEST.yaml`'s `agent_scenarios` notes as
a concrete instance of `agent_scenarios_bias`: the same person who writes an allowlist and the
scenarios meant to check it can get a claim about that allowlist wrong, and only running the check
against the real table catches it.

### D6-07 — A ruff formatter-version drift left seven Phase 4/5 files failing `ruff format --check`
**Severity: minor — a process gap, not a functional defect.** `ruff format --check .` had never
been run as part of this project's pre-commit verification loop, only `ruff check .` (lint).
Seven files from Phase 4/5, never touched this phase, had drifted from the installed formatter's
current output (the project pins `ruff>=0.8`, a loose bound, and the formatter's line-wrapping
rules for chained calls have changed across minor versions in that range).

**Fix:** `ruff format .` applied — purely cosmetic, verified by a full test-suite re-run showing no
behavioural change — and `ruff format --check .` is now part of this phase's own verification
sequence, same standing as `ruff check .` and `mypy`.

---

## 3. Major findings (scheduled)

**M6-01 — The quiz-answer reachability fix (D6-04) is partial, not complete.**
`IntentGate.classify()` is single-utterance and stateless by design (`test_classification_sends_
only_the_utterance_no_tools_offered` — the classifier must not see conversation history any more
than it must be able to call a tool). A bare quiz answer ("5 ohms") carries no lexical signal that
would make a classifier trained on the current prompt tag it `quiz_request`, so `update_student_
progress` can still be unreachable on the specific turn where a student answers a quiz question,
even after D6-04. *Blocking for:* reliable quiz grading across a full quiz-then-answer exchange.
*Scheduled:* session-level "a quiz is open" state that overrides the gate while one is pending —
naturally sequenced alongside Phase 7's frontend work, which already needs to surface tool activity
per turn.

**M6-02 — No real Anthropic API key exists in this sandbox; two new suites inherit Phase 4/5's
STT/TTS limitation.** The agent eval suite and the injection suite both measure real mechanisms
(allowlist coverage, pipeline execution, executor-level authorization) against a *scripted* model,
because there is no credential to call a real one. Neither suite can say anything about whether
gating helps or hurts a real model's tool-selection accuracy (the actual question ARCHITECTURE
§8.2 asks), or whether a real model would even produce the argument shapes these suites assume an
already-persuaded model would. Recorded in full in `datasets/v1/MANIFEST.yaml`'s
`agent_scenarios_bias` and `agent_injection_bias`. *Blocking for:* any claim about real
tool-selection accuracy or real injection resistance. *Scheduled:* carried forward from Gate 4/5,
unchanged — `scripts/smoke_llm.py` with a real credential remains the prerequisite for all three
(this and the two below).

**M6-03 — `MemoryExtractor` never regenerates `student_profiles.digest`.** The extractor applies
`preference_signals` to `explanation_style` and `learning_preferences`, and `topic_signals` to
`student_topics` via EWMA — but nothing writes the free-text `digest` field `assemble()` renders as
"what you already know about this student." ARCHITECTURE §12's own JSON example for extractor
output does not include a digest field either, so this is not a drift from spec, but it does mean
the digest a long-running student accumulates is, today, whatever it started as. *Scheduled:*
define what should populate it (a periodic summarization pass over recent `memory_events`, most
likely) once real conversations exist to summarize meaningfully.

**M6-04 — `LLMRequest.tool_choice` is not actually enforced by anything in this sandbox.**
`MemoryExtractor` sets `tool_choice` to force `propose_memory_deltas`, translated to Anthropic's
`{"type": "tool", "name": ...}` shape in the adapter — but the only provider ever exercised here,
`FakeLLMProvider`, replays whatever a test script gives it regardless of what was requested. Output
is validated in Python specifically because this guarantee cannot be assumed (`memory_extractor.py`'s
own module docstring says so). *Scheduled:* re-verify against a real Anthropic call once a
credential exists — `tool_choice`'s wire format is written to the SDK's documented shape but has
never round-tripped through a real API response.

**M6-05 — The short-term window's rolling-summary fold pays a full LLM call on every turn of a long
session, once the window is full.** Once a session exceeds `llm_history_turns` (20) messages,
folding a new turn into the window overflows it by the size of that turn on every subsequent turn
— an accepted, documented tradeoff (`memory_window.py`'s module docstring), mitigated by running
off the critical path, but not free: a long tutoring session now costs one extra cheap LLM call per
turn indefinitely, not just once. *Scheduled:* revisit if real usage shows this material to cost or
latency (Phase 8's cost/latency measurement is the natural place to check).

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m6-01 | A hidden async-scheduling race: tests asserting on `FakeLLMProvider.requests[-1]`/`.last_request` could observe a background task's (IntentGate's, then later the window-fold's and MemoryExtractor's) request instead of the real conversational turn's, depending on cooperative-scheduling order | Fixed by filtering to real mentor requests via a shared `_mentor_requests()` helper (matches on the persona text in `system[0]`) rather than by position — robust regardless of how many auxiliary calls interleave or in what order |
| m6-02 | A test-fixture teardown race: `test_a_cancelled_turn_does_not_cancel_an_in_flight_tool_call` returned once its handler completed, letting the executor's trailing DB flush race the `db_session` fixture's own rollback on the same session | Fixed with a documented grace-period `await asyncio.sleep(0.1)` in the test; not a production bug, since production has no equivalent same-session teardown-during-flush scenario |
| m6-03 | `mypy app tests` (run as extra diligence beyond the project's own `mypy app eval` scope) surfaces ~130 pre-existing "unused type: ignore" errors across the test suite, unrelated to this phase's edits | Confirmed as tooling debt from `disallow_untyped_defs=false` on `tests.*` making old `# type: ignore[no-untyped-def]` comments unnecessary, not a Phase 6 regression; left as-is since `tests/` is deliberately outside the project's own mypy `files` scope (`pyproject.toml`) and cleaning it project-wide is unrelated to this phase's work |
| m6-04 | The EWMA `confidence` field grows at the same fixed `+0.1`-per-observation rate regardless of whether the evidence came from a graded quiz (`alpha=0.3`) or an inferred conversational signal (`alpha=0.1`) | Verified as intentional, not a bug: both paths call the same `StudentTopicRepository.apply_ewma`, so `confidence` (how much evidence backs the estimate) and `alpha` (how much a given sample moves it) are deliberately separate concerns, guaranteed consistent by sharing one method rather than by two implementations agreeing |

---

## 5. Dimensions reviewed with no finding above Minor

**Architecture consistency.** The shipped system matches ADR-0009 (the hand-written loop, not a
framework) and ADR-0012 (two-tier memory, explicit audited extraction) exactly, including the
specific tradeoffs both ADRs accepted in advance — non-forced tool choice for the main loop,
EWMA-not-replacement for mastery, `memory_events` as the falsifiability mechanism. Where the
*code's* faithful implementation exposed a gap in the *spec itself* (D6-04), the spec was corrected
alongside the code rather than left to drift further from an already-flawed table.

**Unnecessary complexity.** `app/core/background.py` is 15 lines because that is what a correct
fire-and-forget task needs (a strong reference, a done-callback, a way for tests to drain) — no
task queue, no retry policy, nothing speculative. The short-term window's rolling summary was
scoped to exactly what ADR-0012 specifies (verbatim turns plus a summary of the rest) rather than
extended with a fancier compaction scheme not asked for anywhere.

**Security.** D6-02 is the headline finding of this phase precisely because it is a security
boundary; closing it before any external review, and then building a 16-case, 19-attempted-call
suite that exercises exactly that boundary under a worst-case scripted model (19/19 blocked,
cross-checked against real row counts, not just the executor's own reported status), is this
phase's clearest instance of the project's stated posture: authority never comes from the model,
verified rather than assumed.

**Testing strategy.** Three of this phase's seven defects (D6-01, D6-03, D6-05) were found by
running the *full* test suite or a *real* multi-call scenario after wiring, not by testing new code
in isolation — each is a defect that only exists at an integration seam (concurrent execution
sharing a resource, a new call added to an existing flow, two independently-connected sessions
racing a commit) invisible to a unit test of either side alone. D6-06 extends the same discipline
to dataset authoring: a scenario file is data that can be wrong, and the fix was to run it against
the real system, not to reread it more carefully.

**Evaluation strategy.** Both new suites this phase (agent, injection) are explicit, in their own
module docstrings and in EVALUATION.md/SECURITY.md/MANIFEST.yaml, about the one thing they cannot
measure without a real model — and design around that limitation by measuring the mechanical
guarantee (does gating change execution, does the executor block an already-successful injection)
rather than fabricating a number that would imply more. This is the same discipline Phase 5 applied
to the zero-vector/NaN retrieval bug: an honest smaller claim over a flattering larger one.

---

## 6. Gate decision

**PASSED.** Phase 7 (frontend & dashboard) may begin.

Carried forward, unchanged in priority from Gate 5:
1. Run `scripts/smoke_llm.py` with a credential — still the prerequisite for M6-02, M6-04, and
   Gate 4/5's original two items (a real ASR/TTS adapter, and TTFA measurement) alike.
2. Collect real speech and real course material — unchanged; three datasets (LID, retrieval, and
   now the agent scenarios' self-authored bias, M6-02) share the same author-independence gap.

New from this gate:
3. Session-level "quiz in progress" state, to close M6-01 properly rather than the partial fix in
   D6-04.
4. A digest-regeneration mechanism for `student_profiles.digest` (M6-03), once real conversations
   exist to summarize.
