# ADR-0018 — The local voice is eSpeak NG, not Piper

**Status:** Accepted · **Date:** 2026-10-01 · **Amends:** [ADR-0003](0003-tts-provider-strategy.md)
(its offline and CI voice only)

## Context
ADR-0003 gives the real-time path to a managed streaming synthesiser, and names Piper (English) as
the offline and CI voice so tests never need a network or a credential. Neither was built. Every
voice turn ended in the fake synthesiser's silence, so no answer had ever been spoken, and the
voice loop had never been timed with a synthesiser that does real work (M9-01).

Piper needs a voice model downloaded from Hugging Face, which this project's development
environment cannot reach (the recogniser's weights meet the same wall: EVALUATION.md §3). And it
covers English only, while the system routes English, Hindi and Tamil.

eSpeak NG is an operating-system package with no model to download. It has voices for all three
languages. Measured here, it synthesises a four-second sentence in about 25 ms on one core, and
gives the same samples for the same text every time.

## Options considered
1. **Piper, as ADR-0003 says:** neural and better sounding, but English only, and blocked here by
   its download.
2. **eSpeak NG:** a formant synthesiser. Intelligible and robotic, in all three languages, with
   nothing to download.
3. **Keep the fake** until a managed provider is chosen.

## Decision
**eSpeak NG** (`VAANIOS_TTS_PROVIDER=espeak`, `app/providers/tts/espeak.py`) is the local voice,
for development, evaluation and CI. The production image does not install it, and the real-time
path is still the managed provider ADR-0003 plans.

- Each chunk (a sentence) is synthesised whole, then streamed in 20 ms frames at the session's
  rate (eSpeak NG's 22,050 Hz, resampled to 24,000). Audio still starts on the first sentence.
- The text goes in on standard input, never as an argument, so an answer cannot become an option.
- Barge-in cancels synthesis by killing the process.
- A failed synthesis is a `ProviderError`, so the session's degradation applies: the rest of the
  answer arrives as text (DEGRADATION.md).
- Voices are eSpeak NG's own `en-us`, `hi` and `ta`. The exact program version is recorded in every
  voice and in the provider's identity.
- The app builds its voice once at startup, so a missing program stops the server from starting
  rather than failing a student's first answer.

## Rationale
- A turn that ends in real speech, and a voice loop that can be timed with a synthesiser doing real
  work, matter more for this project's evidence than how the voice sounds. Neither changes what is
  claimed about voice quality, which stays with human ratings (ADR-0003, EXP-006).
- All three routed languages, against one for Piper. Hindi and Tamil plumbing (voice selection, the
  mismatch log, the transliteration gap) runs against real Indic synthesis.
- No download means it runs here, in CI and in an offline demo alike.

## Tradeoffs accepted
- **It sounds robotic,** and nothing about it predicts how a neural or managed voice will sound or
  be understood. No voice-quality claim may rest on it.
- **Its timing is not a managed provider's.** Synthesising a whole sentence locally in about 25 ms
  says nothing about a network round trip. Latency measured with it measures the pipeline and a
  local synthesiser, and is labelled as such.
- **Romanized Hindi** goes to the Hindi voice as written, so it is read with that voice's rules for
  Latin letters. The transliterator is still EXP-006.

## Consequences
- CI installs `espeak-ng`, and its tests fail rather than skip there: the three voices, framing,
  loudness, option injection, cancellation, failure, and a full voice turn that ends in speech.
- ADR-0003's offline and CI voice is eSpeak NG. Its decision for the real-time path is unchanged.

## Revisit when
A managed streaming voice is chosen (ADR-0003), or a neural local voice covering Hindi and Tamil
can be downloaded where the project is built and tested.
