# Voice dataset v1

**Synthetic, not human.** Every utterance here was spoken by eSpeak NG, a formant synthesiser. It
exists to measure the voice front end's *logic* — when it hears a question begin, when it decides
the question is over, whether it cuts in mid-sentence, whether noise becomes a turn — on audio
whose timing is known exactly. It says nothing about accuracy on real students, Indian-English
accents, code-switched speech in the wild, or real rooms. The VAD thresholds stay untuned until the
human slice in `docs/DATASET.md` exists (M7-03).

## What is in it

`cases.jsonl` — 48 cases, each assembled at run time (`backend/eval/suites/voice.py`) from:

| Folder | What | Size |
|---|---|---|
| `parts/` | 66 synthesised utterance parts, 16 kHz mono 16-bit PCM, trimmed of leading and trailing silence | 3.3 MB |
| `noise/` | three unit-level noise beds (white, fan hum, keyboard clicks), stored at −20 dBFS RMS | 0.6 MB |

Each case is 500 ms of lead-in, its parts with the pauses between them, and 1.5 s of trailing quiet,
with an optional noise bed mixed under all of it. Because the audio is assembled from parts, where
the speech starts, pauses and ends is known by construction, not annotated.

| Kind | Cases | What it is | Pauses inside the turn |
|---|---|---|---|
| `single` | 12 | one question, no pause | — |
| `hesitation` | 12 | one question with a pause mid-sentence ("What is the … voltage across the second resistor?") | 200, 250, … 750 ms |
| `multi_sentence` | 12 | a complete sentence, a pause, then the question ("I have a doubt. … What is Kirchhoff's current law?") | 250–750 ms |
| `backchannel` | 6 | "Hmm.", "Okay.", "Haan." — speech, but not a question | — |
| `noise` | 6 | no speech: quiet, white noise at −35 and −25 dBFS, fan hum, keyboard clatter at −25 and −15 dBFS | — |

Languages: English (8 per question kind), Hindi in Devanagari (2), romanized Hindi (2, spoken by
the English voice — which is how eSpeak reads it, and nothing like a Hindi speaker). Voices:
`en-us+f3`, `en-us+m3`, `en-gb`, `hi`, `hi+f3`, at 150–180 words per minute. Six question cases
carry fan noise at −35 dBFS under the speech.

**The composition was fixed before anything was measured on it**, including the equal thirds of
question kinds and the evenly spread pause lengths. How often real students pause mid-question, or
open with a sentence before asking, is unknown; every voice number is conditional on this mix, and
EXP-003's write-up says so.

## How it was made

`backend/scripts/make_voice_dataset.py` (needs `espeak-ng` on the path). It records its own
parameters in `SYNTHESIS.txt`: eSpeak NG 1.51, 22 050 → 16 000 Hz with a polyphase filter, trimmed
below −45 dBFS per 10 ms frame, 5 ms fades, peak −3 dBFS. Regenerating it with another eSpeak build
changes the audio, and so the dataset digest every recorded run carries: that is a new dataset, not
the same one.

`fixtures/espeak-en-kvl-question.wav` predates this set: the single clip the VAD tests and the
browser tests use (`tests/unit/test_vad.py`, `frontend/e2e/`).
