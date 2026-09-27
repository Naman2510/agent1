# FC-005 — Hindi speech is never heard as Hindi, and comes back as invented English

**Status:** open — EXP-013 measures the first fix (below); nothing is shipped yet
**Found:** 2026-09-27 · **Phase:** 8 · **Component:** stt
**Severity:** major (for the local recogniser; the real-time path has no Hindi recogniser at all yet)
**Case IDs:** the 11 `*-hi-*` spoken parts of dataset v1's voice slice

## Input

The `stt` suite (EVALUATION.md §3): faster-whisper `small`, int8, beam 5, `language=None` — the
recogniser detects the language per utterance, as the app's adapter does. Audio: eSpeak NG's
Devanagari Hindi voice reading sentences such as `किरचॉफ का वोल्टेज नियम क्या है?` and
`ठीक है, समझ गया।` (datasets/v1/voice, synthesised; see its README).

## Expected

Hindi text in Devanagari, near the reference — or at least Hindi detected and a poor transcript.

## Actual

CI tier T2, first run (ac96111, `stt` config): Hindi WER **1.383**, CER 1.294, 0 of 11 word for word,
and the language detected as Hindi **0 of 11** times. What came back reads as Hungarian,
Japanese, Dutch and English — invented text in whichever language was detected (the report records
only whether detection matched, not which language it chose):

```
किरचॉफ का वोल्टेज नियम क्या है?   →  Kicsok, kármultinium, játé!
इस सर्किट में                       →  いっしゃいっしゃい!
मुझे एक सवाल पूछना है।              →  Muziek zomal pójdza.
ठीक है, समझ गया।                    →  Thank you for watching and I'll see you in the next video!
ओम का नियम समझाइए।                  →  Oh, can you? I'm sorry.
```

The fourth is Whisper's best-known hallucination, from subtitle training data: a closing line
that has nothing to do with the audio. WER above 1 means more words were invented than the
reference had. English on the same run: WER 0.127, detected as English 44 of 44 times.

## Root cause

Two layers, the second only partly separable from the first:

1. **Detection fails before transcription starts.** With `language=None`, faster-whisper picks the
   language from the first 30 s window's language-token probabilities, then decodes in that
   language. eSpeak's Hindi — a formant synthesiser with no natural prosody — never scored highest
   as Hindi, so every utterance was decoded as some other language, and a decoder told to write
   English writes English whatever it heard.
2. **The acoustics are hard even in the right language.** Whether `small` can transcribe eSpeak's
   Hindi when told it is Hindi was unknown until EXP-013's candidate ran (below).

The romanized-Hindi parts (read by the English voice) fare differently: they are detected as
English, and come back as English-sounding words (`kaise hota hai` → `gains over high`), WER 0.961.
That is closer to a limit of the task than a defect: Whisper writes romanized Hindi only when
nudged.

## Proposed fix

Tell the recogniser the language the session's router has already decided (ADR-0011) instead of
letting it detect — the `language = "hint"` setting in the stt suite, EXP-013. The router decides
from the transcript of previous turns and the student's explicit requests, so it cannot help the
first utterance of a session; the experiment's hint is each case's true label, an upper bound.

Beyond that: a recogniser trained on Indic speech (EXP-001, blocked on a credential), and real
recorded Hindi rather than eSpeak's (DATASET.md: no consented recordings yet).

## Experiment

EXP-013 — `stt.toml` (auto) → `stt-language-hint.toml` (hint), registered before either run at
bdcad75. Candidate, measured in T2 at bdcad75 (pinned arithmetic, seeded sampling — FC-006):

| | auto (first run, unpinned) | hint (pinned) |
|---|---|---|
| Hindi WER / CER | 1.383 / 1.294 | 0.957 / 0.633 |
| Hindi detected as written | 0 of 11 | 11 of 11 |
| English WER | 0.127 | 0.123 |

Told it is Hindi, `small` writes Devanagari, and phonetically close: `इस सर्किट में` → `इस्टागिट में`,
`अब अगला उदाहरण बताइए।` → `अब आब लव बादव बबाई`. Still wrong nearly word for word — eSpeak's Hindi
is hard to hear even in the right language.

## Result

Pending: the baseline side (`stt.toml` under the same pins) and the registered decision come from
the next T2 run. The unpinned first run is not a fair comparison — FC-006 — and is shown only to
describe the failure.
