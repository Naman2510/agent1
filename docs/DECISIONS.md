# Architecture Decision Records

Every meaningful architectural decision is recorded in `docs/adr/` using the format required by spec
§40: context, options considered, decision, rationale, tradeoffs, consequences, and — added here —
an explicit **revisit trigger**, so a decision can be reopened by evidence rather than by opinion.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-transport-websocket-over-webrtc.md) | WebSocket transport for v1; WebRTC as a documented upgrade | Accepted |
| [0002](adr/0002-stt-provider-strategy.md) | Local faster-whisper for eval/CI, managed streaming ASR for the real-time path | Accepted; provider choice deferred to EXP-001 |
| [0003](adr/0003-tts-provider-strategy.md) | Managed streaming TTS for Indic languages, Piper for CI | Accepted; provider choice deferred |
| [0004](adr/0004-vad-silero.md) | Silero VAD (ONNX), server-side and authoritative | Accepted |
| [0005](adr/0005-vector-store-pgvector.md) | PostgreSQL + pgvector rather than Qdrant | Accepted |
| [0006](adr/0006-embedding-model.md) | `multilingual-e5-base` as the default embedding model | Accepted |
| [0007](adr/0007-reranker-latency-gated.md) | Reranking flag-gated; must earn its latency | Accepted |
| [0008](adr/0008-llm-provider-claude.md) | Claude `claude-opus-5` behind `LLMProvider`; tier choice is EXP-004 | Accepted |
| [0009](adr/0009-no-agent-framework.md) | Hand-written orchestrator instead of an agent framework | Accepted |
| [0010](adr/0010-six-independent-eval-suites.md) | Six independent eval suites, not one end-to-end score | Accepted |
| [0011](adr/0011-language-detection-strategy.md) | Layered language ID with sticky session state | Accepted |
| [0012](adr/0012-memory-two-tier-extraction.md) | Two-tier memory with audited extraction | Accepted |
| [0013](adr/0013-experiment-tracking-mlflow.md) | Self-hosted MLflow, one-way mirror into Postgres | Accepted |
| [0014](adr/0014-observability-scope.md) | Structured logs + OTel; Prometheus/Grafana deferred | Accepted |
| [0015](adr/0015-monorepo-and-eval-placement.md) | Monorepo, eval harness inside the backend package | Accepted |
| [0016](adr/0016-provider-abstraction-boundaries.md) | Six provider interfaces and where the boundary sits | Accepted |

## Answers to the questions spec §40 asks directly

| Question | Answer |
|---|---|
| Why WebSocket instead of polling? | Polling cannot carry continuous audio or deliver a cancel signal in time; ADR-0001 |
| Why pgvector instead of Qdrant? | Corpus size, transactional consistency, one fewer service; ADR-0005 |
| Why Whisper variant X instead of Y? | Not yet decided — it is EXP-001, measured on the `stt` suite; ADR-0002 |
| Why hybrid retrieval? | Vector search misses exact technical terms and formula tokens; but the claim is tested per language, not assumed; ADR-0005, EVALUATION §4 |
| Why Redis? | Seven enumerated ephemeral/atomic use cases, each with a TTL and a reason it is not Postgres; ARCHITECTURE §13 |
| Why this TTS provider? | Choice deferred to measurement; the requirement is Indic streaming synthesis at latency; ADR-0003 |

## Decisions deliberately not yet made

Recording these prevents them from being made by accident:

- Which managed ASR provider (EXP-001) and which TTS provider/voices (ADR-0003).
- Which LLM tier serves the voice path (EXP-004).
- Whether the reranker is on in the voice path (EXP-007).
- Whether semantic endpointing ships (EXP-003).
- Whether the intent classifier is fine-tuned (EXP-010) — and "no" is an acceptable answer.
