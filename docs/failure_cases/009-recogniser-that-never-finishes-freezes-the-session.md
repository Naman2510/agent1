# FC-009 — A recogniser that never finishes froze the whole voice session

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 · **Component:** stt / voice
**Severity:** major — the session stopped hearing anything, including the next question
**Case IDs:** `test_a_recogniser_that_never_finishes_is_given_up_on_and_the_session_listens_again`

## Input

A recogniser that consumes the whole utterance and then never returns its final transcript — a
managed ASR whose connection hangs after the audio is sent, or a local one that deadlocks.

## Expected

The student is told, and the session listens again: exactly what already happened when the
recogniser *failed* mid-sentence (`stt_failed`, "Sorry — I didn't catch that. Could you say it
again?").

## Actual

The session hung. In the test, feeding the student's audio never returned; the test's own 5 s guard
cancelled it. Nothing was sent to the client: no error, no state change.

## Root cause

`VoiceSession._finish_transcription` awaited the recogniser's task with no bound. It runs from
`_end_utterance`, which runs from `handle_audio` — the WebSocket's receive path. So a recogniser
that never answered did not only lose one question: it stopped the connection's loop from reading
anything else — audio, `user.interrupt`, `session.end` — until the socket died.

## Fix

A bound on the wait, `stt_final_timeout_ms` (10 s), after which the task is cancelled and the same
`ProviderUnavailableError` path as a mid-sentence failure runs: `stt_failed`, the utterance
discarded, no turn spent, listening again. Ten seconds is past any healthy recogniser, the local
faster-whisper on CPU included.

## Result

The test passes within its bound; before the fix it hung until cancelled. The streaming
recogniser's final is normally due within the 400 ms budget of ARCHITECTURE §9, so the bound
changes nothing for a working one.
