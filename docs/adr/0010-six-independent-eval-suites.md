# ADR-0010 — Six independent evaluation suites instead of one end-to-end score

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The system is a chain of five fallible model-driven stages. When answer quality drops, the question is
always *which stage*. A single end-to-end score cannot answer that, and a chain of five 90%-accurate
stages is a ~59%-accurate system — so stage-level visibility is not a nicety.

## Options considered
1. One end-to-end conversational quality score.
2. Per-stage suites only.
3. **Per-stage suites plus a thin end-to-end suite.**
4. Manual testing plus anecdotes.

## Decision
Six suites — `stt`, `retrieval`, `agent`, `response`, `voice`, `e2e` — each independently runnable
against a versioned dataset, each writing an `evaluation_runs` row and logging to MLflow. The `e2e`
suite exists to catch integration failures (ordering, cancellation, state), not to grade quality.

## Rationale
- Attribution: a WER regression and a retrieval regression look identical end to end and require
  opposite fixes.
- Cost and speed: `retrieval` runs free and locally on every push; `response` needs paid calls and
  runs on demand. One monolithic suite would force the expensive tier on everything.
- Experiments (spec §31) change one variable, which usually affects one stage; per-stage suites give
  the tight feedback loop that makes single-variable discipline practical.

## Tradeoffs accepted
- Six harnesses, six dataset slices, six report formats — real implementation and maintenance cost.
- Stage-level metrics can all improve while the conversation gets worse (Goodhart); the `e2e` suite
  and human spot-checks are the guard, and they are weaker instruments than the stage metrics.
- Per-stage fixtures drift from production behaviour unless refreshed, so fixtures are regenerated
  when providers change.

## Consequences
- The CI tiering in EVALUATION §6 (T0–T3) follows directly from suite cost.
- The dashboard shows the latest run per suite per language rather than one headline number, and shows
  "not measured" where no run exists.
- A phase gate that produces metrics cannot be passed without a recorded run.

## Revisit when
Suite maintenance starts crowding out feature work, or two suites prove consistently redundant.
