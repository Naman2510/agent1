# FC-016 — An answer being recorded when its turn was cancelled was lost

**Status:** fixed
**Found:** 2026-09-30 · **Phase:** 9 (load) · **Component:** voice / data
**Severity:** major — the student heard an answer that the record does not have
**Case IDs:** `test_conversation_service.py::test_an_answer_being_recorded_when_the_turn_is_cancelled_is_still_recorded`

## Input

100 voice students on one server process, after FC-015's fix. When the process is saturated, some
answers take longer than the load client waits (30 s). The client then moves on: it asks its next
question, which barges in, or it ends the session.

## Expected

A barge-in keeps what was heard (ARCHITECTURE §5.3): the question and the heard part of the answer
are recorded, and the next question works.

## Actual

In two runs at 100 students (ten times in the first, seven in the second), the turn's transaction
was broken when the recovery backstop (FC-011) looked at it:

```
sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a
previous exception during flush. ... Original exception was:
sqlalchemy.exc.InvalidRequestError: This session is in 'prepared' state; no further SQL can be
emitted within this transaction.
```

The empty "original exception" is a cancellation's, since `CancelledError` has no message.
`prepared` is a commit stopped part-way. The backstop rolled back, as it should, and the answer was
never recorded.

## Root cause

D8-04 made every database write of a turn finish before a cancellation proceeds
(`finish_then_cancel`). The one exception was the last write: the answer's own record and its
commit, in `stream_turn`'s `finally`. A cancellation that arrived while that write was in flight cut
it off mid-flush or mid-commit. It could be a barge-in just after the answer finished playing, or
the student leaving. For the cancellation to land there, the write has to take a while. Under load,
after FC-015's fix, it first waits for a pooled connection.

## Fix

The answer's message, its commit, its cost and the memory tasks it starts now form one unit, run
under `finish_then_cancel` (`ConversationService._record_answer`). The test holds the answer's write
open, cancels the turn during it, and checks that the answer is recorded and no transaction is left
open. Without the fix, only the question is recorded.

## Result

In the ladder after the fix ([LOAD.md](../LOAD.md)), no transaction broke at any level up to 100
students. Before the fix there were 10 and 7.
