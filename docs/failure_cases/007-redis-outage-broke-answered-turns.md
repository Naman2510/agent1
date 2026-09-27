# FC-007 — A Redis outage broke answered turns and kept every student out of voice

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 · **Component:** infrastructure (usage accounting, readiness)
**Severity:** blocker — every priced turn, and every voice connection
**Case IDs:** `test_redis_down_*` in `backend/tests/integration/test_degradation.py`

## Input

Redis unreachable (fakeredis with its server marked disconnected), everything else healthy, and
the language model a priced one (`claude-sonnet-5`), so each turn costs something.

## Expected

ARCHITECTURE §13, since Phase 0: *"Redis is not a conversation store; losing it costs a session's
live state and nothing else. That degradation path is an explicit integration test."* It was not
one; there was no such test.

## Actual

When the test was written:

- **A typed turn** streamed its whole answer, then ended in an `error` event
  (`chat.stream_failed error_type=ConnectionError`) — the student saw the answer followed by a
  failure.
- **A voice turn** spoke its whole answer, then sent `turn_failed`: *"Sorry — I lost that. Could you
  say it again?"* — an apology for an answer the student had just heard.
- **With a spend cap configured**, every turn failed.
- **A voice connection** could not open at all: the handler raised `ConnectionError` before
  accepting the socket.
- **Readiness** answered 503, which takes an instance out of a load balancer's rotation — every
  instance at once, since they share the Redis.

## Root cause

The usage ledger (`app/services/usage.py`) was the one Redis user with no failure handling. The
rate limiter fails open (Phase 2), the short-term window falls back to Postgres (Phase 6), but:

- `record_turn` — the monthly spend counter's increment — runs after the answer is stored and
  committed, inside the conversation's stream; its `RedisError` escaped the stream after the last
  fragment, into the chat route's error path and the voice session's `turn_failed` path.
- `check_spend_cap` reads the counter before every turn when a cap is set.
- `check_voice_quota` reads the daily allowance before the WebSocket is accepted.
- `/ready` treated Redis exactly like the database.

## Fix

The rule the rate limiter already followed, applied throughout: a Redis outage suspends the
controls, never the product. Each ledger call catches `RedisError`, logs it at warning
(`cost_guard.unavailable`, `cost_guard.record_failed`, `voice_quota.unavailable`,
`voice_quota.record_failed`) and carries on. No spend goes unrecorded — each turn's usage is stored
with its message (`messages.token_usage`) — only the counter misses the outage's increments.
Readiness says `degraded` with 200 when only Redis is down, and 503 (`unavailable`) only for the
database. The trade-off, that a spend cap is not enforced during an outage, is written down in
docs/DEGRADATION.md.

## Result

Six tests. Five failed before the fix — a typed turn, a voice turn, a spend cap, a voice
connection through the real WebSocket endpoint, and readiness; the sixth, that the next turn still
sees the last one, passed already (the window's Postgres fallback worked) and now pins it. The
ARCHITECTURE §13 sentence now says what is actually lost, and links the tests.
