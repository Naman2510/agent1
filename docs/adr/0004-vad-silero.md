# ADR-0004 — Silero VAD (ONNX), server-side and authoritative

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Voice activity detection drives three things: gating audio to the ASR (cost), deciding when the
student's turn ended (latency), and triggering barge-in (correctness). It runs on every 32 ms of
audio for every session.

## Options considered
1. **Silero VAD v5** (ONNX, ~1–2 MB, MIT).
2. **WebRTC VAD** (GMM-based, microseconds per frame) — noticeably worse with background noise and
   music, which is exactly the hostel-room condition we care about.
3. **Energy threshold** — trivial and unusable in noise.
4. **Provider-side VAD** (endpointing inside a managed ASR) — convenient, but it puts the barge-in
   trigger behind a network hop and outside our control.

## Decision
Silero VAD v5 via ONNX Runtime on the server, on 512-sample (32 ms) 16 kHz chunks, with hysteresis:
enter speech at `p > 0.5`, leave at `p < 0.35`, `min_speech = 250 ms`, `min_silence = 500 ms`. The
server-side decision is authoritative. An optional client-side instance may gate upstream bandwidth
but never decides anything.

## Rationale
- Accuracy in noise is the whole reason to use a learned VAD, and it is cheap enough (single-digit
  milliseconds per second of audio on CPU) to be irrelevant to the latency budget.
- Barge-in must be decided where cancellation happens. A client-side trigger would race with
  server-side generation state and could not be fenced by `turn_id`.
- `min_speech = 250 ms` is the false-interruption guard: it is why a cough does not kill an
  explanation (R-08).

## Tradeoffs accepted
- Upstream bandwidth is spent on non-speech audio when client-side gating is off (ADR-0001 already
  accepts uncompressed PCM).
- An ONNX runtime dependency in the backend image.
- Thresholds are corpus-dependent; the defaults above are starting points to be tuned against the
  interruption dataset, and the tuning is recorded as an experiment rather than quietly adjusted.

## Consequences
- `VadGate` emits `speech_start` / `speech_end` with frame-accurate offsets, which the interruption
  metrics and the barge-in tests both depend on.
- VAD metrics (false-speech rate, missed-speech rate, turn-end latency) are first-class in the voice
  suite, per spec §9.
- Half-duplex mode (VAD gated during playback) exists as an escape hatch for laptop-speaker users and
  explicitly trades away barge-in (R-07).

## Revisit when
False-speech or missed-speech rates exceed the recorded baseline on the noisy slice, or semantic
endpointing (EXP-003) changes what the VAD layer needs to provide.
