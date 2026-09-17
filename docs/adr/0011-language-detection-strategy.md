# ADR-0011 — Layered language identification with sticky session state

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
The user must never have to pick a language per utterance (spec §11), mid-conversation switching must
work, and the hard case is romanized Hinglish — Latin script, Hindi grammar, English technical nouns
("Bhai KVL basically kya bol raha hai?").

## Options considered
1. **Audio-level LID model** before ASR.
2. **ASR-provided language token** (Whisper's detected language).
3. **Text-level LID on the transcript** (fastText `lid.176`, script heuristics, lexicon).
4. **Ask the user once per session** and keep it fixed.
5. **Layered signals with session stickiness.**

## Decision
Option 5, as specified in ARCHITECTURE §7: explicit user request → Unicode script decision →
romanized-Hinglish classifier → sticky session prior, with hysteresis requiring two consecutive
disagreeing turns before the prior moves.

## Rationale
- **Script is nearly free and nearly perfect** for Devanagari and Tamil: a Unicode histogram settles
  those cases with no model at all. Spending a model on them would be waste.
- **Audio-level LID does not solve the real problem.** Intra-sentence code-switching means the
  utterance has no single language, and the decision we actually need ("which language should the
  mentor answer in, and which TTS voice") is better made on text.
- **The ASR language token is a weak, biased signal** — it tends to label romanized Hindi as English —
  so it informs but never decides.
- **Stickiness prevents flapping.** Per-utterance independent decisions make the mentor switch
  language mid-conversation on a short or ambiguous turn, which is worse than being slightly slow to
  follow a genuine switch.
- Explicit requests ("Tamil-la sollunga") must win immediately and persist; that is the one case where
  the user *has* expressed intent.

## Tradeoffs accepted
- **Romanized Hinglish classification is an open problem** (R-04). The baseline is a word-level
  lexicon plus heuristics; accuracy is unknown until the `stt` suite runs, and this may remain the
  system's weakest component. Saying so now is better than discovering it in a demo.
- Hysteresis costs one turn of latency when following a genuine language switch.
- `mixed` is a real class and the boundary is arbitrary; the dataset defines it as ≥20% of tokens from
  a second language, and that threshold is part of the metric definition.

## Consequences
- LID accuracy is reported per language in the `stt` suite, with a confusion matrix — the Hinglish row
  is the interesting one.
- Conversation history is language-tagged but never partitioned, so context survives switching
  (spec §11).
- The response-language policy and the TTS voice/transliteration decision both consume this output,
  which means a LID error is audible (R-05) — it is not a silent metric.
- This is the natural fine-tuning candidate (EXP-010): narrow, labelable, measurable.

## Revisit when
The first `stt` run reports Hinglish LID accuracy; if the baseline is poor, EXP-010 becomes the
priority rather than an optional extra.
