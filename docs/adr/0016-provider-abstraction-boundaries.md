# ADR-0016 — Six provider interfaces, and where the boundary is drawn

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Spec §42 requires that the application not be hard-coded to one provider, so that controlled
experiments (STT A vs. B, LLM A vs. B) are config changes rather than rewrites. But abstraction has a
cost: a too-thin interface leaks provider details, and a too-thick one hides the very capabilities the
experiments are about.

## Decision
Six interfaces, each with a fake implementation for tests:

| Interface | Core method | Streaming | Cancellable |
|---|---|---|---|
| `LLMProvider` | `stream(messages, tools, config) -> AsyncIterator[Delta]` | yes | yes |
| `STTProvider` | `transcribe_stream(frames) -> AsyncIterator[Partial \| Final]` | yes | yes |
| `TTSProvider` | `synthesize_stream(text, voice, lang) -> AsyncIterator[bytes]` | yes | yes |
| `EmbeddingProvider` | `embed_documents/embed_query` | no | n/a |
| `RerankerProvider` | `rerank(query, candidates) -> scores` | no | n/a |
| `VectorStore` | `search(vector, filters, k)` / `upsert` | no | n/a |

Selection is by config (`VAANIOS_LLM_PROVIDER=anthropic`), resolved through a registry at startup;
the active provider, model ID, and version are recorded in every `evaluation_runs.config` and in
per-turn telemetry.

## Rationale
- Interfaces are drawn at **replaceable-capability** boundaries, not at every class, and each one
  exists because there is a concrete competing implementation (ADR-0002, 0003, 0006, 0007).
- Cancellation is in the contract for the three streaming interfaces, because barge-in needs it
  everywhere and an adapter that cannot cancel is not usable here.
- Fakes at the interface (rather than HTTP mocks) are what make T0 CI deterministic and free while
  still exercising real orchestration logic.

## Tradeoffs accepted
- **Capability mismatch is real.** Some ASR providers support contextual vocabulary biasing, word
  timestamps, or true streaming and some do not. Rather than lowest-common-denominator interfaces,
  optional capabilities are declared via a `capabilities` property and callers degrade explicitly.
  Silently ignoring a requested capability would corrupt experiment results.
- Provider-specific tuning (Claude's `effort`, cache breakpoints, refusal fallbacks) lives in the
  adapter and is passed through a typed provider-specific config object — the abstraction does not
  pretend those features are universal.
- One extra indirection to read through when debugging.

## Consequences
- Adding a provider means one adapter plus one config entry; no orchestrator change. This is asserted
  by a test that runs the orchestrator against two different fakes.
- Every adapter records provider name, model ID, and SDK version in telemetry, so no metric is ever
  ambiguous about what produced it.
- Contract tests run against recorded fixtures per adapter, so provider API drift fails fast (R-21).

## Revisit when
An interface accumulates provider-specific branches in *calling* code — the signal that the boundary
is in the wrong place.
