# ADR-0014 — Structured logs + OpenTelemetry now; Prometheus/Grafana deferred

**Status:** Accepted (Phase 0) · **Date:** 2026-09-17

## Context
Spec §32 requires structured logging and tracing of stage latencies, tool calls, retrieval, errors,
and tokens; spec §33 requires a dashboard of system health and model quality. Spec §19 and §32 both
warn against adopting technology merely because it is fashionable.

## Options considered
1. Structured JSON logging only.
2. **Structured logging + OpenTelemetry tracing + Postgres-backed aggregates for the dashboard.**
3. The above plus Prometheus + Grafana.
4. A managed observability platform.

## Decision
Option 2. `structlog`-style JSON logs with `request_id` / `session_id` / `turn_id`, OpenTelemetry
spans per stage with the nine stage marks as span events, and dashboard aggregates computed from
`messages.latency_ms`, `tool_calls`, and `evaluation_runs`. Prometheus and Grafana are deferred.

## Rationale
- **Traces answer the question we actually have.** "Why was this turn slow?" is a per-turn,
  high-cardinality question — a trace with nine marks answers it; a latency histogram does not.
- Latency data already has to be persisted per turn for the voice suite and the dashboard. Exporting
  the same numbers to Prometheus would create a **second source of truth for metrics the project is
  built to report accurately**, which is precisely the failure mode this project is trying to avoid.
- There is no operational load to justify alerting: one developer, no on-call, no SLOs.
- An OTel exporter can be added later without changing instrumentation — the whole point of OTel.

## Tradeoffs accepted
- No time-series alerting; problems are found by inspection or by the eval suites.
- Postgres aggregate queries are heavier than a Prometheus range query, and will need indexes or
  materialised views if data grows.
- Logs and traces need retention management to avoid filling disk.

## Consequences
- The dashboard reads only real data and shows "not measured" where none exists (spec §33).
- Log hygiene is enforced: raw audio never logged; transcripts hashed at INFO, full text only at DEBUG
  in development; a redaction filter with a test asserting secrets never serialise (SECURITY §5).
- Trace context propagates into provider adapters so external-call latency is attributed correctly
  rather than blamed on our own code.

## Revisit when
The system runs continuously for real users, or a latency regression is found that per-turn traces
cannot explain.
