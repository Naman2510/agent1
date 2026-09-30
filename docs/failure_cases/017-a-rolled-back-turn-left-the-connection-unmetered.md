# FC-017 — After a rolled-back turn, the connection's audio went unmetered

**Status:** fixed
**Found:** 2026-09-30 · **Phase:** 9 (load) · **Component:** voice
**Severity:** major — the daily voice allowance is the control that bounds voice spend
(SECURITY.md §4), and it missed the connection's audio
**Case IDs:** `test_voice_ws.py::test_a_connection_is_metered_even_after_a_turn_was_rolled_back`

## Input

A voice connection in which one turn's transaction was rolled back (the recovery of FC-011 and
FC-016), which then closes.

## Expected

When the connection closes, its audio is added to the student's daily allowance, whatever happened
to its turns.

## Actual

In the load run at 100 students, the close failed once for each rollback, ten times in all:

```
  File "app/ws/voice.py", line 247, in voice_ws
    await ledger.record_voice_seconds(str(student.id), audio_ms // 1000)
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call await_() here.
RuntimeError: Expected ASGI message 'websocket.send' or 'websocket.close', but got
'websocket.http.response.start'.
```

The audio was never recorded, and the handler ended in an unhandled error. (The second line is
Starlette trying to send a 500 response on a WebSocket.)

## Root cause

A rollback expires every row that the database session has loaded, including the student row loaded
before accept. Reading `student.id` from an expired row needs a query, and an async session cannot
run a query from a plain attribute access (`MissingGreenlet`). The handler read the id there, at the
close, after the rollback.

## Fix

The handler reads the id once, as a value, straight after the lookup, and uses that value
everywhere. The test rolls back the connection's database session before the close and then checks
the meter: 3 seconds recorded with the fix, 0 without it.

## Result

No `MissingGreenlet` in any load run after the fix. Before it there were ten, at 100 students.
