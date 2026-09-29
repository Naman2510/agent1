# FC-014 — Circuit terms misheard in plain English

**Status:** open — a fix is proposed and measurable, not yet run
**Found:** 2026-09-27 · **Phase:** 8 · **Component:** stt
**Severity:** major for retrieval (a misheard term is a missed search), minor for display
**Case IDs:** `single-en-08-a`, `hesitation-en-08-b`, `single-en-02-a`, `hesitation-en-01-b`,
`hesitation-en-07-a`, `multi-en-06-b`, `multi-en-08-a` (dataset v1, voice slice)

## Input

English questions about circuits, spoken by eSpeak, heard by faster-whisper `small` (the `stt`
suite), in CI tier T2.

## Expected

The course's own terms written as the course writes them: Thevenin, Ohm's law, voltage, node.

## Actual

English is the recogniser's best language here — WER 0.123, language right 44 of 44 — and still the
domain's words come back as common ones. From T2's first pinned run (bdcad75); the unpinned first
run misheard the same words, one of them differently ("slavery" for "savory"):

```
What does Thevenin's theorem say?          →  What does the man in theorem say?
related to Thevenin's theorem?             →  related to the Manning's theorem.
Can you explain Ohm's law with an example? →  Can you explain Omslaw with an example?
voltage across the second resistor?        →  Molding across the second resistor.
Is the voltage across a capacitor          →  In the molten across a capacitor
Did you say the resistors are in series?   →  The new savory system are in theory.
What is a node?                            →  What is unknown?
```

## Root cause

A general-purpose recogniser's language model prefers common phrases to rare ones when the audio is
ambiguous, and a physicist's surname is rare. eSpeak's formant voice makes the audio more ambiguous
than a person's would be, so this overstates the rate — but the direction is the known one, and the
recogniser is given nothing about the domain: `FasterWhisperSTT` passes no vocabulary, though the
provider interface declares a capability for it (`Capability.CONTEXTUAL_VOCABULARY`).

It matters beyond the transcript: "the man in theorem" is what `search_knowledge` would be asked.

## Proposed fix

Give the recogniser the course's vocabulary — faster-whisper's `hotwords` (or an `initial_prompt`)
built from the corpus's headings and glossary terms — and measure it as one knob in the `stt` suite,
with English WER as the metric and per-language guards, registered before it runs (EXPERIMENTS.md).
The same terms could bias the managed streaming recogniser ADR-0002 plans, which accepts phrase
hints.

## Experiment

Not run. EXP-002 (EVALUATION.md §7), registered in Phase 0 as "contextual vocabulary biasing
reduces technical-term errors", is this experiment; it is the next T2 one, at about 13 minutes of CI
per config.

## Result

—
