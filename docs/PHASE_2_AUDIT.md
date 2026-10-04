# Phase 2 Audit — Audit Gate 2

**Reviewed:** the provider layer (six interfaces, fakes, registry), the Claude adapter, prompt
assembly, the usage/spend ledger, the streaming text turn, and its SSE endpoint.
**Date:** 2026-09-18 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions, plus the Gate 1 carry-forward (D-01's generalisation), each
checked by running something.

**Outcome:** 2 defects found and fixed, 7 Major items scheduled, 4 Minor recorded.
**Gate status: PASSED WITH ONE CRITERION DEFERRED.** Two of three Gate 2 criteria are met; the
third — a verified prompt-cache hit — cannot be met without a live credential and is carried into
Phase 3 as M2-01/M2-04 rather than being marked complete.

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Swapping a provider requires no application change | `test_the_same_service_code_runs_against_different_providers` runs the identical turn service against two provider instances with no branching; the registry resolves all six kinds from config alone; `test_an_unknown_provider_fails_loudly` proves a misconfiguration is not silently served by a fake | pass |
| Cost per turn recorded | `messages.token_usage` carries input/output/cache tokens, the model id, and `estimated_cost_usd`; asserted in `test_both_messages_are_persisted_with_usage_and_timings`; the SSE `done` event reports the same | pass |
| Cache-hit test passing | **Deferred.** The application-side half passes: a breakpoint is requested on stable content only, nothing volatile sits inside the cached prefix, and the prefix is byte-identical across turns. Whether the *provider* then serves a hit is unverifiable without a credential — see M2-04 | deferred |

164 tests (89 of them with no database at all), 94% coverage, `ruff`, `ruff format` and `mypy`
clean. Verified by running: the full suite, the unit suite against a deliberately broken database
DSN, and a live uvicorn streaming a turn over SSE and persisting both messages.

---

## 2. Defects found and fixed

### D2-01 — A configuration value existed but never reached the request
**Severity: medium.** `llm_history_turns` was defined, documented, and exported in
`.env.example`, and `ConversationService.stream_turn` ignored it — it called `self.history(session_id)`
and took the helper's default of 20. Setting it would have changed nothing, and the per-turn token
cost would not have responded to the knob meant to control it.

The first test passed while the bug was live, because it tested `history()` directly rather than
the turn. The replacement asserts against `llm.last_request.messages`, i.e. what the provider
actually received. That distinction — assert on the request, not on the helper — is the
generalisable lesson, and it is the same shape as Gate 1's D-02 (test the thing that ships).

### D2-02 — Tier-T0 CI was not actually hermetic
**Severity: medium.** An autouse truncate fixture depended on the database engine, so *every*
test — including pure unit tests of pricing arithmetic and script detection — required a running
PostgreSQL. The claim in EVALUATION.md §6 that T0 is fast and hermetic was false in practice, and
it surfaced as 61 errors the moment the local cluster was recycled.

**Fix:** database fixtures moved to `tests/integration/conftest.py`. **Verified**, not assumed: the
unit suite now passes with `VAANIOS_TEST_DATABASE_URL` pointed at a non-existent host.

### Gate 1 carry-forward: security actions on error paths
D-01 in Phase 1 was a revocation discarded by transaction rollback. Phase 2 was reviewed for the
same shape. The spend cap raises *before* writing, so there is nothing to lose; the turn's
accounting writes happen in a `finally` and are committed by the route on the success path and
rolled back on the failure path, where nothing had been written. **No new instance found.** The
pattern is now on the review checklist for each phase.

---

## 3. Major findings (scheduled)

**M2-01 — The Claude adapter has never run against the live API.**
No credential existed in the environment where it was written, so the entire live path is unproven:
request acceptance, streaming event shapes, cache behaviour, refusal handling and the beta
fallbacks parameter. What *was* verified: every parameter the adapter sends exists in the installed
SDK's signatures (`anthropic` 1.6.0) — `thinking`, `output_config`, `system`, `tools`, `betas`,
`fallbacks`, `messages.stream`, `beta.messages.stream`, `count_tokens` — checked by introspection,
not by recollection. `scripts/smoke_llm.py` is the live check and runs five assertions.
*Blocking for:* any claim that the system talks to Claude. **Phase 3 must run the smoke script
before the voice loop is demonstrated.**

**M2-02 — The streaming route commits through the request-scoped session inside the response body.**
The SSE generator runs after the endpoint returns, so it relies on FastAPI's dependency teardown
ordering relative to `StreamingResponse`. It works — verified on a real uvicorn, with rows read
back afterwards — but it is a dependency on framework internals, and a FastAPI upgrade could move
it. The turn service should own a dedicated session for the streamed portion. Guarded meanwhile by
`test_both_messages_are_persisted_with_usage_and_timings`, which would fail loudly. *Scheduled
Phase 3*, when the WebSocket path needs its own session lifecycle anyway.

**M2-03 — The spend cap is check-then-act.**
Concurrent turns can overshoot the ceiling by roughly the cost of the turns already in flight. A
hard guarantee would need a reservation and an extra round trip per turn. Documented in the
method's docstring; acceptable for a monthly budget. *Revisit* if the overshoot is ever material.

**M2-04 — Prompt caching is unverified, and may be silently inert.**
Two separate problems. First, only a live call can show a cache read. Second, the minimum cacheable
prefix on `claude-opus-5` is 512 tokens, and the persona alone is plausibly below it — in which
case a breakpoint does nothing at all, with no error, only a bill. The adapter now reports this
case (`cache_breakpoint_ineffective`, logged at WARNING) rather than leaving it invisible, and the
smoke script deliberately pads the prefix so the check is meaningful. *Scheduled Phase 3.*

**M2-05 — The refusal fallback path is untested end to end.**
`fallbacks` and `betas` are accepted by the SDK signature and the array form is the documented
Python shape, but the behaviour on an actual policy decline is unverified. The adapter degrades to
the plain endpoint on a `TypeError` and logs it, so a wrong guess costs the fallback rather than the
turn. *Scheduled Phase 3* (smoke script).

**M2-06 — No retry policy of our own.**
The SDK retries connection errors, 408/409/429 and 5xx twice. A voice turn has a latency budget
that a retry can blow, and `ProviderError.retryable` is currently informational — nothing consumes
it. *Scheduled Phase 3*, where the turn state machine can decide between retrying and apologising.

**M2-07 — Costs are list-price estimates, never reconciled.**
`app/core/pricing.py` is hand-transcribed, and every derived figure is named
`estimated_cost_usd` for that reason. Nothing has been checked against an invoice, and an
unrecognised model raises rather than counting as zero. *Scheduled Phase 9:* reconcile one month
of estimates against actual billing and record the error.

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m2-01 | The SSE stream sends no heartbeat, so a proxy may time out a slow turn | Add a comment event if a real deployment shows it; the voice path uses a WebSocket anyway |
| m2-02 | `app/providers/vector/base.py` reports 0% coverage | Accurate — it is an interface with no implementation until Phase 5. Left visible rather than excluded |
| m2-03 | `llm_effort=medium` is an unmeasured default | Explicitly a starting point; EXP-004 decides it |
| m2-04 | The Phase 2 language tag calls romanized Hindi "en" | Intended and asserted by a test that documents the limitation; the real router is Phase 4 (ADR-0011) |

---

## 5. Dimensions reviewed with no finding above Minor

**Security.** Retrieved context is passed as a delimited user-role block and never in the system
prompt — asserted with an injection string that would be an instruction if placed wrongly. The turn
endpoint scopes to the session's student and returns an indistinguishable 404 for absent and
foreign sessions. Turns take the AI rate-limit class, not the generous read class. The prompt
assembler *refuses* to mark a block cacheable if it contains a timestamp or UUID, which is a
cost bug rather than a security one but has the same "silent" character.

**Architecture consistency.** The Phase 0 design is being honoured where Phase 2 touches it:
capabilities are declared rather than assumed (ADR-0016), the no-op reranker announces that it does
not rerank so telemetry cannot mistake a pass-through for a rerank (ADR-0007), the embedding fake
reproduces e5's query/passage asymmetry so a prefix mismatch is reproducible (ADR-0006), and
thinking deltas are dropped before they can reach a TTS stream.

**Unnecessary complexity.** The interfaces exist because each has a named competing
implementation. No adapter was written for a provider that is not yet chosen: `build_stt` and
`build_tts` raise for anything but the fake, rather than shipping a half-guess.

**Testing strategy.** Two deliberate choices. The adapter is driven by a stub SDK client, so the
tests assert the request we build and how we read a response — the only part that is ours. And the
interrupted-turn invariant (Gate 0 finding C-03) is tested now, before barge-in exists, so Phase 3
inherits a tested invariant instead of discovering it.

---

## 6. Gate decision

**PASSED, with the cache-hit criterion deferred to M2-04.** Phase 3 (the voice loop) may begin as
soon as **C-05(b)** from [Gate 0](PHASE_0_AUDIT.md) is answered — the remainder of the truncated
specification, or confirmation that the reconstructed roadmap stands. That is still the only
blocking item.

First task in Phase 3, before any voice work: run `scripts/smoke_llm.py` against a real credential
and record the result. Until it passes, the system's ability to talk to Claude is a claim about
code, not an observation.
