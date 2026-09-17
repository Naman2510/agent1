# Failure Cases

**Status:** empty — the system does not exist yet, so it has not failed yet. Files appear from Phase 3
onward.

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
