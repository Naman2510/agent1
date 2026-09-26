# Voice fixtures

| File | What it is | Made with |
|---|---|---|
| `fixtures/espeak-en-kvl-question.wav` | 16 kHz mono PCM: 0.5 s quiet, "Explain Kirchhoff's voltage law." (2.65 s), 0.8 s quiet | `espeak-ng -v en -s 150` (eSpeak NG 1.51), resampled 22.05 → 16 kHz |

**Synthetic, not human.** This exists to prove the voice-activity detector hears speech at all —
until Phase 7 it could not (`tests/unit/test_vad.py`). It says nothing about accuracy on real
students, noisy rooms, Indian-English accents or code-switched speech; thresholds stay untuned
until the human STT slice in `docs/DATASET.md` exists.
