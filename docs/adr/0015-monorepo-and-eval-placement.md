# ADR-0015 — Monorepo, with the eval harness inside the backend package

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The project has a Python backend, a TypeScript frontend, an evaluation harness, datasets, and infra
definitions. The harness must exercise the same provider adapters, retrievers, prompts, and tool
registry that production uses.

## Options considered
1. **Monorepo** with `backend/`, `frontend/`, `datasets/`, `infra/`.
2. Separate repositories per component.
3. Monorepo with a **separate top-level** `eval/` package.
4. Monorepo with eval **inside** `backend/` (`backend/eval/`).

## Decision
Monorepo (option 1), with the harness at `backend/eval/` (option 4). The evaluation service in
Compose is the backend image with a different entrypoint, not a separate codebase.

## Rationale
- **The harness imports what it evaluates.** A separate package would need the backend as a
  dependency anyway, and a top-level `eval/` would invite a copy of the prompts or retriever config —
  at which point the harness measures a *different system* than the one that ships. That failure is
  subtle, plausible, and fatal to the project's central claim.
- One PR can change a prompt, its eval case, and its dataset version atomically; separate repos make
  that a multi-repo dance where drift is the default.
- The frontend and backend share the WebSocket protocol and API types; one repo keeps them in step,
  with the OpenAPI drift check as the enforcement.
- One CI pipeline, one Compose file, one `docker compose up` for a reviewer.

## Tradeoffs accepted
- Coupled release cadence for frontend and backend (irrelevant at this scale).
- CI must be path-filtered to avoid running everything on every change.
- Eval dependencies (`jiwer`, `rank_bm25`, `mlflow`, judge tooling) sit in the backend's optional
  dependency group, so the production image must be built without them or it carries dead weight.
- Datasets stay **top-level**, not under `backend/`, because they are language-agnostic artifacts with
  their own versioning lifecycle.

## Consequences
- `pyproject.toml` defines extras: `dev`, `eval`, `voice-local`; the production image installs none of
  them.
- CI path filters: `backend/**` → Python jobs, `frontend/**` → Node jobs, `datasets/**` → manifest
  validation.
- `scripts/` holds entrypoints (`ingest_docs`, `run_eval`, `seed_demo`, `bench_stage`) that a reviewer
  can run without reading the code.

## Revisit when
The frontend needs an independent release cycle, or the repository becomes large enough that CI
filtering stops being effective.
