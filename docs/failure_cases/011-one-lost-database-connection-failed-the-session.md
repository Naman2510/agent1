# FC-011 — One lost database connection failed every turn after it

**Status:** fixed (both routes to it)
**Found:** 2026-09-27, twice — Phase 8 (as D8-04), then Phase 9 · **Component:** voice / data
**Severity:** blocker — the session was unusable until the student reconnected
**Case IDs:** `test_voice_session.py::test_an_interruption_mid_query_does_not_break_every_turn_after_it`;
`test_degradation.py::test_a_database_connection_lost_mid_session_costs_one_turn_not_the_session`

## Input

A voice session — which holds one database session for the whole connection — whose connection is
lost part-way through a turn, by either of two routes:

1. **A barge-in that lands mid-query** (Phase 8). Cancelling the turn's task while it awaits a
   query abandons asyncpg's connection mid-protocol.
2. **The server dropping the connection** (Phase 9): a Postgres restart, a failover, a network
   blip. Reproduced with `pg_terminate_backend` on the session's own backend.

## Expected

That turn is lost — it was in flight — and the next question works.

## Actual

Every later turn failed too. Route 2, as first tested: the interrupted turn failed with
`InterfaceError: connection is closed`, and the next with

```
sqlalchemy.exc.PendingRollbackError: Can't reconnect until invalid transaction is rolled back.
```

— and so would every turn after it, each one `turn_failed`, "Sorry — I lost that", until the
student reconnected and got a new database session.

## Root cause

SQLAlchemy invalidates a connection that failed mid-operation, and the session's transaction then
can only be rolled back; until it is, the session refuses all work. Nothing rolled it back. For
route 1, D8-04 added `finish_then_cancel` (database work finishes before a cancellation proceeds)
and a rollback backstop — but that backstop ran only after a *cancelled* turn. A turn that *failed*
went through `_answer`'s catch-all, which reported it and left the transaction as it was.

## Fix

`ConversationService.recover()` — the backstop generalised — rolls back when the session's
transaction is in a state that can only be rolled back: its connection invalidated, or the session
already refusing work. It leaves a healthy transaction, and its work, alone. The voice session calls
it after a barge-in (as before) and now after any failed turn. The engine's `pool_pre_ping` then
hands the session a live connection for the next turn.

## Result

Route 1: mutation-checked in Phase 8 — with neither protection every turn fails; with the backstop
alone only the interrupted turn's record is lost. Route 2: the test failed before the fix
(`turn_failed` twice) and passes after it (once). The typed path never had the problem: each HTTP
request gets its own database session.
