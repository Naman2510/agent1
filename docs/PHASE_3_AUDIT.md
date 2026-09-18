# Phase 3 Audit — Audit Gate 3

**Reviewed:** the voice loop — turn state machine, WebSocket protocol, VAD, turn detection,
pre-roll buffer, sentence chunker, playback ledger, barge-in, the WS endpoint, and the browser
demo client.
**Date:** 2026-09-18 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus the Phase 3 gate criteria, each checked by running
something. 353 tests, `ruff`, `ruff format` and `mypy` clean.

**Outcome:** 4 defects found and fixed, 7 Major items scheduled, 5 Minor recorded.
**Gate status: PASSED, with the provider-dependent half of the phase explicitly unverified.**

**Standing assumption:** the source specification was truncated mid-Phase 1 and has not been
supplied since. On instruction to proceed with full autonomy, the reconstructed roadmap is treated
as authoritative from here on. Gate 0's C-05(b) is therefore **closed as accepted**, not resolved —
if the original phases differ, the difference will show up as rework.

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Full state-transition test matrix | `test_voice_state.py`: 19 legal transitions asserted individually, and the **exhaustive complement of 49 illegal (state, trigger) pairs** asserted to raise | pass |
| Stale `turn_id` frames dropped | Fencing tested at three levels: the machine (`accepts_frame`), the session (`dropped_frames` after a real in-flight barge-in), and the client (the demo page discards audio below its current turn) | pass |
| Stored assistant text equals the spoken prefix | `test_barge_in_stops_playback_and_stores_only_what_was_heard` interrupts a turn **in flight** and asserts the stored text is a strict, non-empty prefix of the generated answer, with the tail in `unspoken_remainder`; `test_an_interruption_before_any_audio_plays_stores_nothing_as_heard` covers the zero case | pass |
| Nine stage marks persisted | `messages.latency_ms` carries the derived durations; asserted in `test_a_completed_turn_persists_both_messages_with_stage_marks` and reported to the client as a `metrics` frame | pass |
| First real latency numbers recorded | `scripts/bench_voice.py`, results in [ARCHITECTURE §9.1](ARCHITECTURE.md). **Not TTFA** — see M3-01 | partial |

Also verified: a real WebSocket handshake with subprotocol authentication, refusal of a missing
credential / forged token / another student's session / an unknown session before `accept`, and
malformed-frame handling that reports and continues rather than dropping the conversation.

---

## 2. Defects found and fixed

### D3-01 — The pre-roll buffer silently disabled the short-utterance guard
**Severity: medium.** The guard compared the buffered audio length against `min_speech_ms`, and the
500 ms pre-roll is prepended to every utterance — so the check passed unconditionally. Worse, the
guard was *also_ redundant: the VAD only announces speech after `min_speech_ms`, so any announced
utterance clears that bar by construction.

Two fixes: measure the VAD's confirmed speech run rather than the buffer, and introduce a separate,
higher `min_utterance_ms` (400 ms) for "long enough to be a question". Without it a 300 ms "hmm"
became a turn, with an LLM call and a bill attached. The backchannel stoplist R-08 promised was
implemented at the same time, matched on the transcript rather than the audio because "haan" and
"haan, lekin…" are acoustically similar and semantically opposite.

Caught by a test that expected a discard and got a turn.

### D3-02 — A chunk cancelled mid-synthesis had its text recorded nowhere
**Severity: high.** The playback ledger registered a chunk only once its audio was fully generated.
When a student interrupted during synthesis, that chunk's text appeared neither as heard nor as
unheard — it vanished from the record entirely. This is the same defect class as Gate 0's C-03: the
stored conversation stops matching reality.

**Fix:** chunks are registered when synthesis *starts* (`begin_chunk`) and grown as audio arrives
(`extend_chunk`). Caught only because the barge-in test was rewritten to interrupt a turn genuinely
in flight — the earlier version interrupted after the turn had finished and would never have found
it.

### D3-03 — `encode_control`'s parameter name collided with the `message` payload field
**Severity: medium, and badly placed.** `encode_control(message_type, **payload)` was originally
`encode_control(message, ...)`, so `encode_control(ERROR, code=..., message=...)` raised
`TypeError: got multiple values for argument 'message'` — on the **error path only**, i.e. exactly
when something had already gone wrong. Every malformed-frame response was a 500 in disguise.

**Fix:** renamed to `message_type` across the protocol, the `Transport` interface, both
implementations and the test double.

### D3-04 — `_barge_in` assumed it was called from an interruptible state
**Severity: low (defensive).** Called from a non-interruptible state it fired `SPEECH_START`
followed by `CANCELLATION_COMPLETE`, and the second transition is illegal from `USER_SPEAKING` —
corrupting the machine rather than doing nothing. The call sites all guarded correctly, so this was
only reachable by a race, but a state machine that can be corrupted by a race is not a state
machine. Now inert outside `THINKING`/`SPEAKING`, with a test.

---

## 3. Major findings (scheduled)

**M3-01 — There is still no TTFA number, and what was measured must not be mistaken for one.**
The benchmark uses deterministic fakes for ASR, LLM and TTS, so it measures our pipeline and
nothing else: **~0.4% of one core in real time**, three to four orders of magnitude inside every
stage budget. That is a genuine and useful result — it says the latency problem will not be our
code — but real TTFA is set by stages 3, 6 and 7, all of which need providers that have not been
chosen and a credential that does not exist here. *Scheduled Phase 8* with EXP-001 and EXP-004.

**M3-02 — The Claude adapter is still unexercised against the live API** (carried from
[Gate 2](PHASE_2_AUDIT.md) M2-01). Every voice turn in this phase ran through the fake LLM.
`scripts/smoke_llm.py` remains the check. Until it passes, "the mentor talks to Claude" is a claim
about code.

**M3-03 — No real ASR or TTS adapter exists.** `build_stt` and `build_tts` raise for anything but
the fake, deliberately, so nothing can silently serve a fake in production. The voice loop is
therefore complete and *provider-less*: every mechanism is tested, and no word has been transcribed
or synthesised. *Scheduled Phase 3b/8*, decided by EXP-001 and ADR-0003.

**M3-04 — VAD thresholds are untuned, and cannot be tuned here.**
0.5/0.35 with 250/500 ms are the library defaults. Silero was measured rejecting silence and white
noise correctly, but **no human speech fixture exists in this environment** — and the attempt to
substitute one is itself a finding (§5). Tuning waits for the first real recordings.
*Scheduled with the v1 dataset.*

**M3-05 — The browser client is unverified.**
`frontend/voice-client.html` was written without a browser to run it in. The protocol it speaks is
covered by the backend suite; the file itself is not. Specific risks: the 48 kHz → 16 kHz decimation
has no anti-alias filter, and the `played_ms` derivation from `AudioContext.currentTime` is the
part the whole barge-in invariant depends on client-side. The page says so at the top.
*Scheduled Phase 7*, with a real device and a Playwright test.

**M3-06 — Turn state lives in worker memory, so a voice session cannot migrate** (R-13, now real
rather than prospective). Sticky routing by `session_id` is required. Accepted for v1; the upgrade
path is documented in ARCHITECTURE §15.

**M3-07 — Gate 2's M2-02 is now worse, not better.** The WS endpoint holds one database session
open for the life of the connection — up to 60 minutes — which is a connection held out of the pool
for a whole conversation. It works and is tested, but it does not scale past a handful of
concurrent sessions. *Scheduled Phase 9* with load testing: a session per turn, or a dedicated
pool.

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m3-01 | Semantic endpointing (EXP-003) is implemented but off by default | Correct: it ships only if the voice suite shows a win without more premature cutoffs |
| m3-02 | The chunker merges very short consecutive sentences | Deliberate — a stream of three-word chunks sounds chopped when spoken. Documented and tested |
| m3-03 | `_speak` sends audio before the client has confirmed it can play it | The jitter buffer absorbs this; a slow client just lags. Revisit if the demo shows drift |
| m3-04 | Cross-event-loop test plumbing: the WS tests build their own app so the engine is created in TestClient's loop | Documented in the fixture. A genuine constraint of mixing `TestClient` with session-scoped async fixtures, not a workaround to remove |
| m3-05 | `onnxruntime` ships no type stubs | `ignore_missing_imports` for that module only |

---

## 5. An empirical finding worth recording

While looking for a speech fixture, `espeak-ng` was installed and used to synthesise English and
Hindi utterances. Silero VAD scored them **max 0.16 and 0.23** — below its 0.5 speech threshold.
Silence and white noise scored ~0.001, so the detector is working; formant-synthesised speech
simply is not human speech to it.

This is direct evidence for the policy already written into
[DATASET.md §3](DATASET.md#3-sourcing-honestly): *synthetic audio systematically understates
difficulty and must be reported separately from human speech.* It was a design assumption; it is
now a measurement. The consequence for this phase is concrete: VAD and ASR evaluation cannot be
bootstrapped with TTS output, so M3-04 genuinely blocks on collecting real recordings.

---

## 6. Dimensions reviewed with no finding above Minor

**Security.** The handshake authenticates before `accept`, so no session state is created for an
unauthenticated peer; the credential rides the subprotocol header rather than the query string,
which would land in access logs. Cross-student access returns the same closure as an unknown
session. Audio messages are size-capped and validated; an odd byte count is rejected rather than
padded. The connection is age-capped at 60 minutes with a `session.reauth` frame, closing Gate 0's
M-08. Voice minutes are metered as audio is consumed, so an abandoned session still counts what it
used.

**Architecture consistency.** Phase 0's design survived contact: the pre-roll, merge window, tool
atomicity and playback ledger from §5.5–5.7 are all implemented as specified, and the two places
the design was wrong (D3-01, D3-02) were wrong in *detail*, not in shape. The delivery-tracker seam
added to `ConversationService` keeps persistence in one place while letting the voice path report
what was heard — the text path passes nothing and behaves exactly as before.

**Testing strategy.** The state machine is tested exhaustively rather than representatively,
because its illegal transitions are the correctness argument for barge-in. The scripted VAD is used
for every logic test on purpose: a deterministic timeline tests our hysteresis, whereas an acoustic
model tested through our logic tests neither well. Two of the four defects above were found only by
making a test *harder* (interrupt in flight; assert the request rather than the helper), which is
the pattern worth carrying forward.

---

## 7. Gate decision

**PASSED.** The voice loop's mechanisms are implemented and tested; its providers are not chosen.
Phase 4 (language routing) may begin, and is largely independent of the missing providers.

Carried forward, in priority order:
1. **M3-02 / M3-01** — run `scripts/smoke_llm.py` with a credential, then measure real TTFA.
2. **M3-03** — choose and implement an ASR and a TTS adapter (EXP-001, ADR-0003).
3. **M3-04** — collect real speech, then tune the VAD.
4. **M3-05** — verify the browser client on a real device.
