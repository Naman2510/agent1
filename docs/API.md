# API

**Status:** Phase 7 — what the backend serves today. The machine-checked contract is
[`openapi.json`](openapi.json), generated from the code by `backend/scripts/export_openapi.py`;
`backend/tests/unit/test_openapi_snapshot.py` fails when the two disagree. This page is the human
summary, and also covers the voice socket, which OpenAPI cannot describe.

Until Phase 7 this page was the Phase 0 plan, and had drifted: it listed endpoints that were never
built, missed ones that were, and described cursor pagination the API never had. Planned endpoints
are now listed separately, at the end.

Base path `/v1`. JSON with `snake_case` fields, UTC ISO-8601 timestamps and UUID identifiers.
`/docs` and `/openapi.json` are served outside production.

## Conventions

**Errors** are uniform and never leak internals:

```json
{"error": {"code": "rate_limited", "message": "Too many requests.", "request_id": "5d0c…"}}
```

`code` is stable and machine-readable, `message` is safe to show, and a validation error adds
`fields`. Detail is logged server-side under `request_id`. Statuses: `401` unauthenticated, `403`
forbidden, `404` absent *or not yours* (never distinguished — that would confirm another student's
data exists), `409` conflict, `422` invalid input, `429` rate limited with `Retry-After`, `503`
`service_unavailable` with `Retry-After` when a dependency cannot be reached right now (the database;
[DEGRADATION.md](DEGRADATION.md)), `500` otherwise.

**Request IDs.** Every response carries `X-Request-ID`. A client-supplied one (up to 64
characters) is echoed so a caller can correlate, and trusted for nothing else.

**Authentication.** `Authorization: Bearer <access token>`: a 15-minute JWT. The roles are
`student` and `admin`, read from the database on every request, so a role change or a disabled
account takes effect immediately rather than at token expiry.

**Rate limits** (docs/SECURITY.md §4), per class:

| Class | Applies to | Keyed by |
|---|---|---|
| anonymous | register, login, logout | client address |
| refresh | refresh | client address |
| authenticated | reads, profile, end session, admin dashboard | user |
| ai | starting a session, a typed turn | user |

**Pagination.** The session list takes `limit` (1–100, default 20) and `offset`, and returns
`{items, total}`. A transcript takes `limit` (1–500, default 200). No cursors.

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness: the process answers |
| GET | `/ready` | `{status, database, redis}`: `ready`; `degraded` (200) when Redis is down — every use of it degrades; `unavailable` (503) when the database is down |

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `email`, `password`, `display_name`, optional `semester` → `201` with tokens; creates the student |
| POST | `/auth/login` | → `{access_token, refresh_token, token_type, expires_in}`; one generic error for any failure |
| POST | `/auth/refresh` | `{refresh_token}` → a new pair. Rotating: replaying a used token revokes its whole family |
| POST | `/auth/logout` | `{refresh_token}` → `204`; revokes it |
| GET | `/auth/me` | the user, role and student profile |
| PATCH | `/auth/me/profile` | display name, institution, semester, preferred language, audio-retention consent |
| DELETE | `/auth/me` | deletes the account and everything that cascades from it → `204` |

The web app never hands the refresh token to page script: its own `/api/auth/*` routes hold it in
an `httpOnly` cookie and call these endpoints on the student's behalf (frontend/README.md).

## Sessions and conversation

| Method | Path | Notes |
|---|---|---|
| POST | `/sessions` | `{transport: "websocket" \| "text"}` → `201` session |
| GET | `/sessions` | the student's own sessions, newest first, each with `turn_count` |
| GET | `/sessions/{id}` | one session |
| POST | `/sessions/{id}/end` | ends it; idempotent |
| GET | `/sessions/{id}/messages` | the transcript, in turn order. Each message has `language`, `was_interrupted`, `spoken_prefix_chars` and `latency_ms`; each mentor message also has the `citations` it made and the turn's `tool_activity` |
| POST | `/sessions/{id}/messages` | a **typed** turn, `{text}` (≤ 2000 characters), answered as server-sent events |

A typed turn streams `delta` events (`{text}`), then one `done` event: turn index, stop reason,
language, latency, estimated cost, token usage, and the answer's `citations` and `tool_activity`.
A failure after the stream has started arrives as a terminal `error` event (`{code, message}`), since
the status line has already been sent.

Stored interrupted answers hold what was heard, not what was generated (docs/ARCHITECTURE.md §5.3).

## Voice

`GET /v1/voice/ws?session_id=<id>` upgrades to a WebSocket. The access token travels in the
subprotocol list — `["bearer", "<token>"]` — never in the URL, which would land in logs. The
connection lasts only as long as its newest token: the client renews it with a `session.reauth`
frame, and the server closes with `1008` once it expires. Frames, states, playback acknowledgements
and the microphone tagging rule are in [ARCHITECTURE.md §10](ARCHITECTURE.md).

The server ends a connection with these close codes and reasons:

| Code | Reason | When |
|---|---|---|
| `1000` | `connection age limit` | after an hour |
| `1008` | `credential expired` | the first frame after the newest token's expiry |
| `1008` | `voice_quota_exceeded` | the day's voice allowance is used up. Usage is metered every 5 s of audio, and an `error` frame with the same code comes first |
| `1008` | `audio faster than real time` | audio received has run more than 10 s ahead of the connection's age. No microphone sends that |

A malformed frame does not end the connection. It is answered with an `error` frame (`bad_frame`,
`frame_too_large`, `bad_control` for a control frame that is not a JSON object, or has a field of
the wrong type, and `unknown_control`), and the conversation goes on.

## Admin

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/health` | the dashboard's data: live and total counts, tool usage by outcome, average time to first token, mastery overview, memory updates. An average with no samples is the string `"not_measured"`, never `0` |
| GET | `/admin/evaluation` | each configuration's latest recorded evaluation run — provenance (git SHA, dataset digest), case and failure counts, headline metrics — and every decided experiment with its comparison and guards. Empty lists when nothing is recorded |
| GET | `/admin/evaluation/runs/{run_id}/failures` | a run's failing cases as recorded (input, expected, actual, why), at most 200; `404` for an unknown run |

There is deliberately no endpoint that grants the admin role: `backend/scripts/promote_admin.py`,
run with shell access to the deployment, is the only way (README).

## Planned, not built

Course material is ingested from the command line (`backend/scripts/ingest_sample_corpus.py`), and
study plans, quizzes and progress exist only as the mentor's tools (ARCHITECTURE §8), not as REST
endpoints. These were in the Phase 0 plan and have no route today:

| Area | Planned surface | Phase |
|---|---|---|
| Student data | read own progress, profile and memory digest; study plans; quiz history and attempts | unscheduled |
| Documents (admin) | upload with licence, list, inspect chunks, delete | unscheduled |
| Evaluation (admin) | start a suite run from the API — runs are started from the command line (`python -m eval.runner`), and the API only reads them | unscheduled |
