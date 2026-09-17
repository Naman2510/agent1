# ADR-0002 — STT: local faster-whisper for evaluation, managed streaming ASR for the real-time path

**Status:** Accepted (Phase 0), with the provider choice deliberately deferred to measurement
**Date:** 2026-09-17

## Context
The system must transcribe English, Hindi (Devanagari), romanized code-switched Hinglish, and Tamil,
with technical vocabulary, Indian names, and numerals, at conversational latency. The development
environment has 4 vCPU, 15 GB RAM, and **no GPU** (R-01).

## Options considered
1. **`faster-whisper` (CTranslate2) locally** — `small`/`medium` int8 on CPU.
2. **Managed streaming ASR** with Indic support (e.g. Indic-specialised APIs, or a general
   low-latency streaming provider).
3. **`whisper.cpp`** — similar CPU profile, weaker multilingual tooling.
4. **Self-hosted Indic ASR** (AI4Bharat-family models) — strong Indic coverage, but needs a GPU to
   be real-time.

## Decision
Define `STTProvider` and ship **two adapters**:
- `FasterWhisperSTT` — default for offline evaluation, CI, and fully local development.
- a managed streaming adapter — default for the interactive voice path.

**Which managed provider wins is not decided here.** It is EXP-001, decided on the `stt` suite by
per-language WER/CER, entity WER, and p95 latency. Choosing now would be choosing by reputation,
which spec §7 explicitly forbids.

## Rationale
- Whisper is **not a streaming model**: a non-causal encoder over 30-second windows, with no
  incremental decode. Streaming means re-decoding a growing buffer and stabilising output with a
  LocalAgreement-style policy; partials will revise themselves (R-03).
- On 4 CPU cores, `small` int8 is plausibly near real-time for short utterances and `medium` is not.
  The 400 ms stage-3 budget is at risk, so the real-time path should not depend on it.
- A local model is nonetheless essential: it makes the `stt` suite runnable offline, free, and
  deterministic, which is what makes STT experiments possible at all.

## Tradeoffs accepted
- The interactive demo depends on a third party's availability, pricing, and privacy terms — audio
  leaves the machine (SECURITY §5).
- Two adapters mean two behaviours to test; the suite runs against both, which is also the point.
- Deferring the provider choice means Phase 3 ships with whichever adapter is configured, and the
  decision lands in Phase 8.

## Consequences
- `STTProvider.transcribe_stream(frames) -> AsyncIterator[Partial | Final]` with `stable_prefix_len`
  on partials, and a provider-reported language hint treated as a weak signal only (ADR-0011).
- Contextual vocabulary biasing (technical terms, the student's current subject) is exposed in the
  interface where the provider supports it — EXP-002.
- If local CPU latency turns out acceptable, the local adapter can serve the real-time path too; that
  would be a measured upgrade, not a hope.

## Revisit when
The `stt` suite shows local CPU meeting the stage-3 budget, or a GPU host becomes available, or the
chosen managed provider's Hinglish entity WER proves unacceptable.
