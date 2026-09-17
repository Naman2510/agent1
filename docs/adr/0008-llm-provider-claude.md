# ADR-0008 — Claude (`claude-opus-5`) as the default LLM, behind `LLMProvider`

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The orchestrator needs: token streaming (to start TTS early), reliable structured tool calling,
strong multilingual reasoning including romanized Hinglish, cancellable requests (barge-in),
prompt caching (multi-turn cost), and usable token accounting.

## Decision
Default to **Claude `claude-opus-5`** via the official `anthropic` Python SDK, behind an
`LLMProvider` interface. Concretely, for Phase 2:

- `client.messages.stream(...)` (async) — streaming is required, and it avoids HTTP timeouts on long
  outputs.
- `thinking={"type": "adaptive"}` — the current parameter shape. `budget_tokens` is rejected on this
  model and must not appear in the code. Adaptive thinking is left **on**; disabling it on this model
  risks tool calls leaking into visible text, which in a voice app means the mentor *reads a tool call
  aloud*.
- `thinking.display` stays at its default (omitted) because reasoning is never spoken; latency is
  tuned with `output_config={"effort": ...}` instead, starting at `medium` for conversational turns
  and `low` for the intent classifier.
- Tools declared with `strict: true` and `additionalProperties: false`, which makes tool arguments
  schema-valid by construction and directly serves spec §13.
- Prompt-cache breakpoints after the tool list, the persona, and the memory digest
  (ARCHITECTURE §8.5); verified by asserting `usage.cache_read_input_tokens > 0` on turn two.
- Mid-conversation operator instructions appended to `messages[]` as `{"role": "system", ...}` rather
  than edited into the top-level `system` field — it preserves the cached prefix and keeps the
  operator channel separate from user content, which matters for §8.4.
- `stop_reason: "refusal"` handled explicitly (a refusal must produce a spoken fallback, not a hang),
  with server-side fallbacks enabled so a policy decline is rescued inside the same call.
- Token usage recorded per turn in `messages.token_usage`; token counting via
  `messages.count_tokens`, never a third-party tokenizer.
- Offline judge and bulk evaluation runs use the Batch API (50% cost) where latency does not matter.

## Rationale
Tool-calling reliability and multilingual quality are the two properties the agent depends on most,
and both are strengths here. The SDK provides streaming, cancellation, caching, and usage accounting
without custom HTTP work.

## Tradeoffs accepted
- Provider dependency and per-token cost; mitigated by caching, effort tuning, tool budgets, and
  batch for offline work.
- Network latency contributes to stage 6 (800 ms TTFT budget) and is partly outside our control.
- A 1M-token context window is far more than a voice conversation needs; history is still trimmed and
  summarised, because sending more tokens costs money and latency regardless of what fits.

## Model tier is an experiment, not a default
Lower tiers (`claude-sonnet-5`, `claude-haiku-4-5`) plausibly offer lower TTFT at lower cost, which
matters in a voice loop. **That is a measurement, not an assumption**: EXP-004 compares tiers on the
`response` and `voice` suites, and the default only changes if the numbers justify it. Downgrading the
default now for a latency benefit we have not measured would be exactly the kind of unevidenced choice
this project is trying to avoid. A cheaper tier is used for the utility calls (intent classification,
memory extraction) where the task is narrow and the quality bar is checkable.

## Consequences
- `LLMProvider.stream(messages, tools, config) -> AsyncIterator[Delta]` with cancellation, plus
  `usage` on completion. A second adapter exists for A/B comparison (ADR-0016).
- Implementation must follow the current SDK reference rather than recalled patterns; several
  parameter shapes in this area changed recently (`budget_tokens` removal, `output_config.format`
  replacing `output_format`, no assistant prefill).

## Revisit when
EXP-004 shows a better latency/quality/cost point, or a self-hostable model becomes necessary for
privacy or offline demonstration.
