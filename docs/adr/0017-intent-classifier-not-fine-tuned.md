# ADR-0017 — The intent classifier is not fine-tuned: its baseline has never been measured

**Status:** Accepted (Phase 10) · **Date:** 2026-09-30

## Context
Phase 10 allows one fine-tune, of the intent classifier (ARCHITECTURE §8.2, spec §41). It is to be
compared zero-shot → prompted → fine-tuned on a held-out split, with cost and latency, and "if the
prompted baseline is already strong enough, this phase is a written decision not to fine-tune"
(ROADMAP.md). EXP-010 names the comparison, and DATASET.md forbids a training split until it is
justified.

What exists:
- **The prompted classifier**, `IntentGate`. It makes one call to the answer's own model
  (`claude-opus-5` by default): a 108-word system prompt listing eight labels, the bare utterance,
  at most 8 output tokens, low effort. An unparseable reply falls back to `question`, whose
  allowlist is course search.
- **What is measured about it**, which is only structural. The agent suite shows every allowlist
  holds the tools its scenarios need and excludes the ones named as wrong (14/14), and the gate
  changes which calls execute (5/5 probes). The injection suite shows no mutating call gets
  through an allowlist (19/19). All of these use a scripted model.
- **What is not measured.** How often a real model picks the right label. There is no labelled set
  of student utterances, and no run against a real model at all (PHASE_9_AUDIT M9-01).

What can be said without a model:
- **Latency.** The call is on every turn's critical path: the answer's generation waits for it.
  ARCHITECTURE §9 budgets 60 ms for "STT final → language + intent", and a call to a hosted model
  does not fit in 60 ms. The budget and the design disagree today. By how much is unmeasured.
- **Cost.** About 220 input tokens and 4 output tokens a turn, from the prompt's 790 characters at
  about four characters a token. At the project's price table that is about $1.20 per 1,000 turns
  on `claude-opus-5`, and about $0.24 on `claude-haiku-4-5`. The prompt is too short to be cached.
  These are estimates from the price table, not measured usage.

## Options considered
1. **Fine-tune now,** a small classifier or a hosted fine-tune, on labels written for the purpose.
2. **Measure first, then decide.** Run the prompted classifier on a real, labelled, held-out set,
   against a zero-shot prompt (the label names only), and fine-tune only if EXP-010's rule says so.
3. **Change nothing, and let the gate stay unmeasured.**

## Decision
**Option 2: no fine-tuning in this phase.** EXP-010 stays pending, with its preconditions written
down (below). The cheaper steps that need no training data come first:
- the gate on a smaller, faster model tier (its own setting, compared as EXP-004 compares the
  answer's tier);
- conversation state for the known quiz gap (ARCHITECTURE §8.2), which no classifier trained on
  bare utterances can fix.

## Rationale
- A fine-tune is justified by the gap between a measured baseline and a target, and neither exists.
  "Fine-tuned beats prompted" cannot be tested while "prompted" has no number.
- Any labels written now would be the pipeline author's own utterances. M9-02 already applies to
  every number in this project, and a classifier trained and tested on its author's phrasing
  measures the author.
- The strongest argument for a local classifier is latency, not accuracy: a hosted call cannot meet
  the 60 ms stage budget. That argument needs the measured latency of the call. It would also be
  answered by any fast local classifier, fine-tuned or not, so it is not yet an argument for
  fine-tuning.
- Serving a fine-tuned model adds a component to the voice path (a model file and its runtime on
  the CPU the VAD already saturates, LOAD.md), or a hosted fine-tune. That cost needs a measured
  benefit to set against it.

## Tradeoffs accepted
- The gate's accuracy stays unknown until a real model runs. The degradation it is designed with
  limits the damage: an unparseable or refused answer becomes `question`, never "no tools", and
  every allowlist is re-checked at execution.
- Every voice turn pays one model round trip before its answer starts, which the latency budget
  did not plan for.

## Consequences
EXP-010 runs only when all of these hold, and in this order:
1. **Data.** A labelled set of real student utterances, consented under DATASET.md, in English,
   Hindi and Hinglish: at least 30 per intent, with the held-out split fixed before any run.
2. **Baseline.** The prompted gate (as shipped) and a zero-shot prompt, both run on that split
   against a real model. Each is recorded as an evaluation run, with macro-F1, the confusion
   between intents with different allowlists (the errors that change behaviour), p50 and p95
   latency, and cost per 1,000 turns.
3. **The rule, registered before any fine-tune is trained.** Fine-tune only if the better prompted
   configuration misroutes more than 10% of held-out utterances across allowlists, or its p50
   latency is more than 15% of the turn's time to first audio. Adopt the fine-tune only if it
   improves the failing measure by the registered margin, with no other measure worse.

## Revisit when
Any of: the prompted gate is measured on real utterances and misses the bar above; the call's
measured latency or cost becomes a material share of a turn's; or labelled real utterances exist
for another reason (the consented human slice, DATASET.md).
