# ADR-0012 — Two-tier memory with explicit, audited extraction

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The mentor must remember what a student struggles with, across sessions, without either (a) stuffing
every past transcript into the context window or (b) rewriting a student's profile because of one
offhand remark.

## Options considered
1. **Full-history context** — send everything. Dies at cost, latency, and the context window.
2. **Rolling summarisation only** — cheap, but produces unqueryable prose; "which topics are weak?"
   becomes an LLM guess rather than a query.
3. **Vector memory** — embed and retrieve past turns. Good for recall of specifics, bad for aggregate
   questions like progress.
4. **Structured extraction into a schema** plus a short window.
5. Structured extraction **plus** vector memory over past turns.

## Decision
Option 4 for v1: a Redis short-term window (verbatim recent turns + rolling summary) and a Postgres
long-term store (`student_profiles`, `student_topics`) updated by an async, schema-constrained
extraction step, with every proposed delta audited in `memory_events`. Vector memory over past
conversations is deferred; `retrieve_previous_conversation` uses structured filters plus lexical
search over `messages` first, and only gains embeddings if that proves insufficient.

## Rationale
- **Structured mastery is queryable.** "How am I doing in EMT?" becomes a SQL query with real numbers,
  which is also what makes tool-use evaluation meaningful.
- **Extraction off the critical path** keeps memory out of the latency budget entirely.
- **EWMA updates, never replacement** (α = 0.3 quiz, 0.1 conversational): one bad turn cannot
  rewrite a student's record, and the aggregate is robust to noise.
- **`memory_events` makes memory falsifiable.** Every proposed delta — applied *and* rejected — is
  stored with its confidence and extractor version. Without this, long-term memory is a black box
  that cannot be debugged, evaluated, or corrected, and "the AI thinks I'm bad at waveguides" has no
  explanation.

## Tradeoffs accepted
- A fixed schema captures less than free-form memory; unmodelled observations are lost or land in the
  digest.
- The extraction step is an extra LLM call per turn (cheap tier), i.e. real cost.
- Extraction errors compound slowly; mitigated by confidence gating (< 0.5 logged, not applied),
  EWMA damping, and the student's ability to read and correct their own profile (API.md).
- Mastery is a **documented heuristic**, not knowledge tracing. Bayesian Knowledge Tracing is future
  work; claiming it now would be a fabrication.

## Consequences
- `MemoryExtractor` uses forced structured output; malformed extractions are rejected and logged
  rather than partially applied.
- `extractor_version` is stored, so changing the extractor is a versioned, replayable event.
- Students can view and edit their own long-term memory — better product, better privacy posture.

## Revisit when
Students report the mentor forgetting specifics that structured fields cannot hold (then add vector
memory), or the extraction cost per turn becomes material.
