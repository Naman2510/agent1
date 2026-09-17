# ADR-0003 — TTS: managed streaming synthesis for Indic languages, local voice for CI

**Status:** Accepted (Phase 0), provider choice deferred to measurement · **Date:** 2026-09-17

## Context
The mentor must speak English, Hindi, Tamil, and code-switched Hinglish, starting audio fast enough
to feel conversational (350 ms stage-7 budget) and streaming rather than synthesising whole responses.

## Options considered
1. **Managed Indic-capable TTS** with streaming output.
2. **Managed general multilingual TTS** with low-latency streaming.
3. **Local open Indic TTS** (Indic-Parler-TTS, AI4Bharat VITS/IndicF5).
4. **Local fast CPU TTS** (Piper) — quick, but weak Indic coverage.

## Decision
Define `TTSProvider` with chunk-level streaming. Use a **managed streaming provider** for the
real-time path in all four languages, and **Piper (English)** as the offline/CI voice so tests never
require network or credentials. The specific managed provider and voice IDs are recorded in run
configs and chosen by measurement, not reputation.

## Rationale
- Local neural Indic TTS on 4 CPU cores is not real-time (R-01). Streaming Tamil or Hindi from a
  local model on this hardware is not achievable, and pretending otherwise would put a fake number in
  the latency table.
- Streaming is required by the design: audio must start on the first sentence, not the last
  (ARCHITECTURE §6).
- Voice quality in Indic languages varies enormously between providers and cannot be assessed from
  documentation — it needs human listening on our own script.

## Tradeoffs accepted
- Network dependency and per-character cost in the demo path.
- CI covers TTS *plumbing* (chunking, ordering, cancellation) with a different voice than production
  uses; voice quality is therefore never validated by CI, only by human rating.
- Provider voice inventories change; voice IDs are pinned in config and recorded per run.

## Consequences
- The interface is `synthesize_stream(text, voice, lang) -> AsyncIterator[bytes]` with cancellation,
  because barge-in must abort synthesis mid-chunk (ARCHITECTURE §5.2).
- **Honesty rule:** documentation states the exact provider, model, and voice ID in use. "Indian
  accent" is never claimed because a provider labels a voice that way; intelligibility and
  pronunciation are reported from human ratings (EXP-006, R-05).
- Romanized Hindi is transliterated to Devanagari before Indic synthesis where measurement supports
  it (EXP-006).
- A Redis byte cache holds a small set of language-specific openers for the optional filler trick,
  which is always reported separately from bare TTFA.

## Revisit when
A GPU host is available (local Indic TTS becomes viable and removes the cost/privacy dependency), or
human ratings for the chosen provider fall below the recorded baseline.
