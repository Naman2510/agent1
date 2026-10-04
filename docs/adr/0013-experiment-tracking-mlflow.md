# ADR-0013 — Self-hosted MLflow for experiment tracking, mirrored one-way into Postgres

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Spec §30 requires that every significant AI change be recorded as an experiment with model, prompt
version, dataset version, parameters, metrics, and a decision. The admin dashboard must show
experiment comparisons, and results must remain reproducible months later.

## Options considered
1. **Weights & Biases** — excellent UI, cloud account required, network dependency.
2. **Self-hosted MLflow** — runs in Compose, Postgres backend, local artifacts.
3. **Custom Postgres tables only** — no new dependency, but a UI and comparison tooling to build.
4. **Files on disk** (JSON per run) — simplest, no querying.

## Decision
Self-hosted MLflow (Postgres backend store, local artifact volume) as the source of truth for
experiment metrics and parameters. `evaluation_runs.summary_metrics` and `mlflow_run_id` are a
**one-way mirror** written once at run completion.

## Rationale
- Runs offline with no external account, so evaluation works on a laptop with no network — a hard
  requirement given that CI tiers T0/T1 must make no external calls.
- Free run comparison, parameter/metric tracking, and artifact storage; building that is not the
  interesting part of this project.
- The mirror keeps the API and dashboard independent of MLflow's availability: the dashboard queries
  Postgres, so MLflow being down degrades experiment browsing, not the product.

## Tradeoffs accepted
- **Two stores hold overlapping data.** Accepted deliberately, with one rule that makes it safe:
  the mirror is written exactly once, at run completion, and never read back into MLflow. Postgres
  holds the summary; MLflow holds the detail. Nothing updates both (M-04 in the Gate 0 audit).
- MLflow is another container to run and back up.
- MLflow's UI is less pleasant than W&B's.

## Consequences
- Every suite run logs: dataset version, git SHA, provider and model IDs, prompt version, retriever
  config, and all metrics. A run without a git SHA is treated as invalid.
- `experiments` rows link a baseline and a candidate run and record the single variable changed plus
  the decision (`adopt` / `reject` / `inconclusive`).
- Artifacts (per-case outputs, judge transcripts, confusion matrices) live in the MLflow artifact
  volume, not in git.

## Revisit when
Multiple people need shared dashboards (then W&B or a hosted MLflow), or the mirror shows any sign of
divergence in practice.
