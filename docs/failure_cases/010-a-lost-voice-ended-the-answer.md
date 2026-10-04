# FC-010 — When the voice failed, the answer stopped too

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 · **Component:** tts / voice
**Severity:** major
**Case IDs:** `test_a_voice_that_is_lost_mid_answer_finishes_the_answer_in_text` (fails, hangs);
`test_a_voice_lost_before_the_first_word_still_delivers_the_answer_in_text`

## Input

A three-sentence answer — "Kirchhoff's voltage law is about loops. The voltages around a loop sum
to zero. That is all." — with a synthesiser that speaks the first sentence and then fails on the
second (or produces no audio at all for it, or fails on the first).

## Expected

The model's answer is already streaming to the student's screen as `llm.delta`, sentence by
sentence, ahead of the audio. Losing the voice should lose the voice, not the answer: the rest in
text, the student told why it went quiet, and the turn finishing as it would have.

## Actual

The text stopped where the voice did — `llm.delta` ended at "…sum to zero. " — and the turn ended
in `turn_failed`: "Sorry — I lost that. Could you say it again?", an apology spoken by nobody, since
the voice was what had failed. With a synthesiser that hung instead, the turn hung until the
test's own 5 s guard cancelled it.

## Root cause

`_speak` iterated the synthesiser's stream directly inside the loop that consumes the model's
stream. A `ProviderError` from synthesis escaped both, into `_answer`'s catch-all, which closes the
model's stream and reports the turn as failed; a synthesiser that never yielded blocked the loop
with no bound. ARCHITECTURE §4.1 draws `SPEAKING → ERROR: provider failure → LISTENING (spoken
apology)`, which assumes the voice still works.

## Fix

Synthesis is bounded (`tts_stall_timeout_ms`, 5 s without audio) and its failure is caught in
`_speak`: the session marks the voice lost for the rest of the turn, sends one `tts_failed` notice
("My voice isn't working right now — the rest of this answer is in text."), and every later sentence
goes into the playback ledger as text only — part of the record, not spoken. The model's stream
runs on, the turn ends normally (`metrics`, sources, activity), and the whole answer is stored. The
voice is tried afresh on the next turn. The frontend already shows an `error` frame's message
without ending the turn, and clears it on the next question.

## Result

All three tests fail before the fix and pass after it. A barge-in after the voice was lost records
only what was *heard* — the ledger counts audio, not what was read — which is the same conservative
rule as everywhere else (ARCHITECTURE §5.3). Not measured: a real synthesiser's failure modes,
which include audio that arrives but is wrong; nothing here can see that.
