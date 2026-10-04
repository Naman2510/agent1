# FC-008 — A model that stops answering kept a voice student in silence

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 · **Component:** agent (LLM provider)
**Severity:** major — a latency spike with no upper bound the student could see
**Case IDs:** `test_llm_that_never_answers_is_given_up_on_with_an_apology`

## Input

An upstream that accepts the request and then sends nothing — a stalled connection, an overloaded
API holding the stream open. In the test, a provider whose stream never yields.

## Expected

An apology, and the chance to ask again, within a bound the design chooses: the latency budget
gives the model 0.8 s to its first token (ARCHITECTURE §9).

## Actual

In the test: the turn never ended. In production the only bound was the Anthropic SDK's, configured
in `AnthropicLLMProvider` as a 30 s timeout with two retries — derived from that configuration, not
measured against the real API: a stall before the response begins is retried, so up to about 90 s
of silence; a stall mid-stream is not retried, so 30 s. Throughout, the voice session sits in
`thinking`, and the student cannot tell a slow answer from a dead one.

## Root cause

The SDK's timeout bounds each HTTP read, which is the wrong quantity: what the student experiences
is the silence, and nothing measured that. The conversation already turned a `ProviderError` into a
spoken apology — nothing ever raised one for a stream that was merely quiet.

## Fix

`app/providers/llm/watchdog.py`: `StallGuard` wraps the configured provider (registry) and gives up
on a stream that produces no event for `llm_stall_seconds` (20 s), raising
`ProviderUnavailableError` — which the existing path turns into the apology — and closing the
upstream stream so the request is cancelled rather than left running. The bound is between events,
not on the whole answer, so a long answer that keeps arriving is never cut off. Because it wraps the
provider, it covers every caller: the turn, the intent gate before it, and the memory work after it.

Twenty seconds is still long for a voice. It is a "something is broken" bound, not a latency target:
a turn that legitimately thinks for longer before saying anything would be cut, and one that does
is already lost to the student. Filler audio ("let me think…") would be the latency answer, and is
an experiment, not a given (ARCHITECTURE §9).

## Result

The test gives up on a silent provider at 0.2 s (the test's bound) and the student gets the apology
in the stream's normal shape (`done` included). A healthy stream passes through untouched
(`test_the_stall_guard_passes_a_healthy_stream_through_untouched`), and the registry test asserts
the real provider is wrapped. Not measured: how often the real API stalls.
