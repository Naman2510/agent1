# ADR-0001 — WebSocket transport for v1, WebRTC as a documented upgrade

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17 · **Supersedes:** —

## Context
The client must send continuous microphone audio upstream and receive synthesised audio downstream,
plus a control channel for partial transcripts, state changes, tool activity, citations, latency
marks, and — critically — an immediate cancel signal for barge-in.

## Options considered
1. **WebSocket** with binary audio frames and JSON control frames on one connection.
2. **WebRTC** (`aiortc`, or a media server such as LiveKit) with Opus over SRTP/UDP and a data
   channel for control.
3. HTTP chunked upload + SSE download.
4. Polling. Not seriously considered; incompatible with interactive latency.

## Decision
WebSocket, carrying 16 kHz mono Int16 PCM in 20 ms frames with an 8-byte `[turn_id][seq]` header,
alongside JSON control messages (ARCHITECTURE §10).

## Rationale
- One protocol, one connection, one auth handshake for audio *and* control. With WebRTC we would
  operate both a media path and a data channel and keep them consistent; the barge-in design depends
  on cancel signalling and audio being ordered with respect to each other.
- Native, first-class support in FastAPI/Starlette; no SFU, no TURN, no ICE negotiation, no
  additional container.
- Debuggability: frames are inspectable, recordable, and replayable, which is what the e2e and
  voice-latency suites need. Replaying an RTP session is markedly harder.
- The interruption race (stale frames after cancel) is solvable with an application-level fencing
  token, which is easier to reason about and to test on an ordered stream.

## Tradeoffs accepted
- **TCP head-of-line blocking.** A lost packet delays everything behind it; WebRTC's UDP transport
  with an adaptive jitter buffer degrades more gracefully on poor networks (R-17).
- **Bandwidth.** Uncompressed PCM upstream is ~256 kbit/s versus ~24–32 kbit/s for Opus. Acceptable
  for a demo on campus or home broadband; not acceptable for mobile data at scale.
- **No built-in echo cancellation or adaptive bitrate.** WebRTC gets AEC, AGC, and noise suppression
  from the browser's media pipeline; we get only what `getUserMedia` constraints provide, which
  contributes directly to R-07.

## Consequences
- The client owns a jitter buffer (target 60 ms) and an AudioWorklet for capture, 48 kHz → 16 kHz
  resampling, and framing.
- Transport sits behind a thin interface so a WebRTC implementation can be added without touching the
  orchestrator.
- An Opus-in-WASM encoder upstream is a cheap intermediate step if bandwidth becomes the problem
  before jitter does.

## Revisit when
Measured audio-gap p95 exceeds 200 ms on a representative network, or mobile-data use becomes a
requirement, or AEC becomes necessary for the primary demo environment.
