# Failure Cases

**Status:** 17 cases (Phase 9 requires at least eight): 10 fixed, 3 accepted as limitations with
the reason recorded, 4 open. FC-006 was reopened in Phase 9, when the first Intel runner did not
reproduce the recogniser's baselines.

| Case | What failed | Category | Status |
|---|---|---|---|
| [FC-001](001-insufficient-lexical-evidence.md) | Short English utterances carry no language signal | language detection | accepted-limitation |
| [FC-002](002-mixed-language-under-detected.md) | Code-switched utterances classified as one language | language detection | open |
| [FC-003](003-lexical-arm-lacks-idf-weighting.md) | The lexical arm ranks a common word like a rare one | retrieval | accepted-limitation |
| [FC-004](004-cross-lingual-retrieval-degrades-to-zero-signal.md) | A query with no shared vocabulary got a fake ranking | retrieval | fixed |
| [FC-005](005-hindi-speech-never-heard-as-hindi.md) | Hindi speech never heard as Hindi; invented English instead | STT, language detection, hallucination | open (EXP-013) |
| [FC-006](006-stt-baseline-not-reproducible.md) | A recogniser baseline no other machine reproduced | evaluation | open: exact on one CPU model; an Intel runner diverged, one cause pinned |
| [FC-007](007-redis-outage-broke-answered-turns.md) | A Redis outage broke answered turns and blocked voice | degradation | fixed |
| [FC-008](008-a-stalled-model-means-silence.md) | A stalled model kept a voice student in silence | latency spike | fixed |
| [FC-009](009-recogniser-that-never-finishes-freezes-the-session.md) | A recogniser that never finished froze the session | STT | fixed |
| [FC-010](010-a-lost-voice-ended-the-answer.md) | When the voice failed, the answer stopped too | TTS | fixed |
| [FC-011](011-one-lost-database-connection-failed-the-session.md) | One lost database connection failed every later turn | interruption, degradation | fixed |
| [FC-012](012-a-pause-mid-question-ends-the-turn.md) | A pause mid-question ends the student's turn | interruption | accepted-limitation |
| [FC-013](013-an-embedding-outage-silenced-every-sourced-answer.md) | An embedding outage made every sourced answer an apology | retrieval, degradation | fixed |
| [FC-014](014-circuit-terms-misheard-in-english.md) | Circuit terms misheard in plain English | STT | open |
| [FC-015](015-the-sixteenth-student-could-not-connect.md) | A server process admitted fifteen voice students; the sixteenth could not connect | load | fixed |
| [FC-016](016-an-answer-being-recorded-when-cancelled-was-lost.md) | An answer being recorded when its turn was cancelled was lost | interruption, load | fixed |
| [FC-017](017-a-rolled-back-turn-left-the-connection-unmetered.md) | After a rolled-back turn, the connection's audio went unmetered | cost control, load | fixed |

**Not yet measured,** so no case can honestly be filed: *wrong tool selection* and *hallucination
by the mentor* need a real model in the loop, and CI has none (tier T3, which would, is run by hand
and needs an API key); *TTS pronunciation* needs a real synthesiser (the one in use is a fake). RISKS.md
predicts where they will appear (R-05, R-07, R-08), so that when they are measured they are not
surprises.

This directory is not an appendix. A project that reports only successes is either not being measured
or not being reported honestly, so documented failures are a deliverable (spec §34) and a phase-gate
requirement (Phase 9 requires at least eight).

## Rules

1. One file per case: `NNN-short-slug.md`.
2. A case is filed when it is **found**, not when it is fixed. `Status: open` is a valid, permanent
   state if the fix is out of scope — with the reason recorded.
3. Reproduction steps must be concrete enough for someone else to see the failure.
4. Root cause means the actual mechanism. "The model hallucinated" is a symptom; "retrieval returned
   no chunk above the score floor and the prompt did not require abstention" is a cause.
5. If the fix was validated by an experiment, link the `experiments` slug and the run IDs.

## Template

```markdown
# FC-NNN — <one-line title>

**Status:** open | fixed | accepted-limitation
**Found:** YYYY-MM-DD · **Phase:** N · **Component:** stt | rag | agent | tts | voice | memory
**Severity:** blocker | major | minor
**Case ID:** <dataset case id, if any>

## Input
Exact input — utterance text, audio file reference, session state, retrieved context.

## Expected
What should have happened, and why that is the correct behaviour.

## Actual
What happened. Verbatim output, with the relevant log lines and stage timings.

## Root cause
The mechanism. Include the code path or the configuration responsible.

## Proposed fix
What would address the cause, and what it costs.

## Experiment
Link to the experiment (EXP-NNN) and the baseline/candidate run IDs, if the fix was measured.

## Result
What the measurement showed — including "no significant difference" or "made it worse", which are
results and are kept.
```

## Categories expected (from spec §34)

STT failure · RAG retrieval failure · hallucination · wrong tool selection · incorrect language
detection · TTS pronunciation problem · interruption failure · latency spike.

Several are already predicted in [RISKS.md](../RISKS.md) — R-04 (Hinglish LID), R-05 (code-switched
TTS), R-07 (self-barge-in), R-08 (backchannel interruptions). Those predictions are on record so that
the corresponding failure cases cannot be presented later as surprises.
