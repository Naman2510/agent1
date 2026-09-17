# ADR-0009 — A hand-written orchestrator instead of an agent framework

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The agent loop must interleave streaming generation with tool execution, enforce latency and call
budgets, expose per-stage timing marks, and — the hard requirement — be **cancellable mid-generation**
with an accurate record of how much of the response was actually spoken.

## Options considered
1. **LangChain / LangGraph** — graph orchestration, large ecosystem.
2. **LlamaIndex** — strong RAG abstractions.
3. **Pydantic AI** — typed, lighter-weight.
4. **A hand-written orchestrator** over the provider SDK's native tool calling.

## Decision
A hand-written orchestrator (`agent/orchestrator.py`) using the SDK's streaming and tool-calling
directly, with a typed Pydantic tool registry and an explicit state machine.

## Rationale
- **Cancellation is the deciding factor.** Barge-in requires aborting an in-flight stream, cancelling
  a dependent TTS task, and truncating the persisted message at the *played* boundary
  (ARCHITECTURE §5.3). Frameworks abstract the stream; getting a partial-output boundary back out of
  them, reliably, is fighting the abstraction.
- **Measurability (P1).** Nine stage marks per turn, and attributing a latency regression to a stage,
  requires owning the control flow. Framework-internal retries and hidden calls make per-stage
  attribution unreliable.
- **Tool gating.** Intent-conditioned tool subsets are a first-class requirement (spec §12); most
  frameworks assume a fixed tool set per agent.
- **Defensibility.** The developer must be able to explain every request the system makes. A
  framework's implicit behaviour is hard to defend in a technical interview, which is an explicit
  project goal.
- The loop itself is genuinely small: stream, collect `tool_use` blocks, execute in parallel, append
  `tool_result` blocks, repeat under budget.

## Tradeoffs accepted
- We reimplement retries, timeouts, parallel tool execution, and history trimming — roughly a few
  hundred lines that must be tested rather than trusted.
- No free ecosystem integrations (callbacks, tracing plugins, prebuilt chains).
- More code to maintain as provider APIs evolve.

## Consequences
- The SDK's tool-runner helper is deliberately *not* used either: it owns the loop, and this design
  needs the loop.
- Parallel tool results must be returned in a **single** user message; splitting them across messages
  degrades the model's willingness to make parallel calls. This is a test case.
- The orchestrator is the most safety-critical module in the codebase (budgets, cancellation,
  authority injection) and gets the heaviest unit-test coverage.

## Revisit when
The loop grows beyond roughly 500 lines of essential logic, or a framework provides first-class
mid-stream cancellation with partial-output boundaries.
