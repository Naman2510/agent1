# FC-015 — A server process admitted fifteen voice students; the sixteenth could not connect

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 (load) · **Component:** voice / data
**Severity:** blocker — past fifteen, a student could not start a voice session at all
**Case IDs:** `test_voice_ws.py::test_connected_students_hold_no_database_connection_while_idle`;
`test_conversation_service.py::test_a_turn_holds_no_database_connection_while_the_model_answers`

## Input

`python scripts/load_voice.py --levels 1,10,25,50 --questions 3`: N students connect the voice
WebSocket to one server process at once, and each asks three spoken questions
([LOAD.md](../LOAD.md) has the method).

## Expected

Every student connects; waits grow with load, and they grow gradually.

## Actual

```
25 sessions: 45 of 75 turns complete
  connection failures ['TimeoutError: timed out during opening handshake']
50 sessions: 45 of 150 turns complete
  connection failures ['TimeoutError: timed out during opening handshake']
```

Exactly fifteen students connected at both levels (45 turns = 15 × 3). Those fifteen were answered
as quickly as one student alone was (first audio p50 1.9 s), with the server at 41% of a core: it
was not busy. It was waiting.

## Root cause

Fifteen is the database pool: `database_pool_size` 10 + `database_max_overflow` 5. Two
transactions were held open long after their last query:

1. The WebSocket handler looks up the user, the student and the session before it accepts. Those
   reads began a transaction on the connection's database session, which lives as long as the
   connection, and nothing ended it until the first turn's commit. So every connected student, idle
   or not, held a pooled connection. The sixteenth handshake waited for one (`pool_timeout`, 30 s),
   and the client gave up first (10 s).
2. A turn held its connection from its first read to its final commit, through the intent call,
   the answer and the whole of the playback. That is seconds of waiting on something other than the
   database.

## Fix

The handler commits before it accepts. A turn commits, which hands its connection back to the
pool, before each wait on a model: after its reads, after storing the question and after each tool
call, as well as at the end (`ConversationService._release_connection`). Each test fails without its
half of the fix. The first uses a pool of one connection with three students connected side by
side; the second checks whether the turn still holds a transaction when the model is asked.

## Result

The same ladder after the fix ([LOAD.md](../LOAD.md)): at 25 and at 50 students every student
connected and every turn completed. Past that, the limit is the process's one core (mostly the
VAD), not the pool. Releasing the connection between queries had a cost: a write at the end of a
turn could now wait for a connection, and a cancellation could land during that wait (FC-016).
