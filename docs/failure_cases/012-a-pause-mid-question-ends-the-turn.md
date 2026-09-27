# FC-012 — A pause in the middle of a question ends the student's turn

**Status:** accepted-limitation — mitigated by the continued-thought merge (ARCHITECTURE §5.6)
**Found:** 2026-09-27 · **Phase:** 8 · **Component:** voice (turn-end detection)
**Severity:** major (cost and latency; the question itself is not lost — see Result)
**Case IDs:** the 9 `voice` suite failures below (dataset v1, voice slice)

## Input

Questions spoken with a pause inside them: a hesitation mid-sentence ("इस सर्किट में … कुल प्रतिरोध
कितना होगा?"), or two sentences ("What is a node? … And how is it different from a junction?").
The voice suite runs the real session — Silero VAD, the turn detector — over eSpeak audio in audio
time, with the production configuration (`voice.toml`).

## Expected

One turn per question: the pause is part of it.

## Actual

The committed `voice` baseline, reproduced on 2026-09-27: **9 of 36 questions cut off** — 4 of 12
hesitations, 5 of 12 two-sentence questions, none of the 12 single sentences. Every one of the nine
has an internal pause of 550–750 ms; the turn ended 520–690 ms after the first part stopped:

```
case              speech (ms)                  turns at (ms)
hesitation-hi-02  (500, 1450), (2100, 3830)    2020, 4400
multi-en-07       (500, 1720), (2270, 4480)    2280, 5040
multi-en-08       (500, 1320), (1920, 3970)    1840, 4480
multi-hil-01      (500, 1810), (2560, 5530)    2400, 6160
… and five more, all ending on the gate's silence rule (`speech_end`)
```

Questions whose pauses were shorter survived. Semantic endpointing (EXP-003) makes it worse: 12 of
36, rejected.

## Root cause

A design trade-off, measured. The gate ends an utterance after about half a second of silence
(ARCHITECTURE §4.3; stage 2 of the latency budget is 500 ms), and a pause of that length inside a
question looks, acoustically, exactly like the end of one. Waiting longer costs every question its
wait; waiting less cuts more. ARCHITECTURE §9 recorded this as "a UX choice, not a technical limit"
before anything was measured.

## Proposed fix

Nothing more to the threshold without real speech: eSpeak's pauses are cleaner than a room's, and
the right threshold for students is a number to measure, not to guess. The mitigation already in
place is §5.6's continued-thought merge (D8-03): speech that resumes within 1.2 s of a commit,
before any answer is heard, continues the cut-off question — the first turn is withdrawn, and the
merged question takes its place. EXP-012 (semantic endpointing only on a question) is registered
and waits for fresh cases.

## Result

In every one of the nine the student resumed within 170 ms of the turn committing (two of them just
before it) — well inside §5.6's 1.2 s window, with nothing yet heard. So each is exactly the case
the merge exists for: the resumed speech barges in, the half question's turn is withdrawn, and the
whole question is answered as one — the mechanism D8-03's tests pin. Not measured on these cases:
the suite's conversation is a stand-in that ends each turn at once, and its numbers count the cut,
not the recovery. What the cut costs even when recovered is a model call started on half a question
and then cancelled, its input tokens billed.
