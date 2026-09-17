# API Contract (planned)

**Status:** Phase 0 design. Nothing is implemented. This exists so the surface can be reviewed
before code, and so the frontend and eval harness can be written against a fixed contract.

Base path `/v1`. JSON, `snake_case` fields, UTC ISO-8601 timestamps, UUID identifiers.

## Conventions

Errors are uniform and non-leaking:

```json
{"error": {"code": "rate_limited", "message": "Too many requests.", "request_id": "01J…"}}
```

`code` is a stable machine string; `message` is safe for display; detail is correlated server-side by
`request_id`. Statuses: `400` validation, `401` unauthenticated, `403` unauthorized, `404` absent or
not yours (never distinguished — that would be an enumeration oracle), `409` conflict, `422`
semantic, `429` rate limited (`Retry-After`), `5xx` generic.

Every response carries `X-Request-ID`. Paginated collections use `?limit&cursor` and return
`{items, next_cursor}`.

## Endpoints

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | email, password, display_name → student + profile |
| POST | `/auth/login` | → access token (15 min) + refresh token |
| POST | `/auth/refresh` | rotating refresh; reuse revokes the family |
| POST | `/auth/logout` | revokes the presented refresh token |
| GET | `/auth/me` | current user + student profile |

### Sessions & conversation
| Method | Path | Notes |
|---|---|---|
| POST | `/sessions` | start a session → `session_id`, ws URL |
| GET | `/sessions` | list own sessions (paginated) |
| GET | `/sessions/{id}` | session detail with turn count and latency summary |
| POST | `/sessions/{id}/end` | graceful end |
| GET | `/sessions/{id}/messages` | transcript incl. `was_interrupted`, citations, tool calls |
| POST | `/sessions/{id}/messages` | **text** turn (accessibility / noisy-environment fallback); SSE stream |
| WS | `/voice/ws` | the real-time voice channel — protocol in ARCHITECTURE §10 |

### Student
| Method | Path | Notes |
|---|---|---|
| GET | `/students/me/progress` | topic mastery, weak topics, recent quiz scores |
| GET | `/students/me/profile` | preferences + memory digest (a student can see their own memory) |
| PATCH | `/students/me/profile` | preferred language, explanation style, audio-retention consent |
| DELETE | `/students/me` | account + data erasure (cascade) |
| GET | `/students/me/study-plans` · `/study-plans/{id}` | plans and items |
| GET | `/students/me/quizzes` · POST `/quizzes/{id}/attempt` | quiz history and submission |

That a student can read *and correct* their own long-term memory is a deliberate design choice: an
AI that keeps an unexplained private model of a person is a worse product and a worse privacy
posture.

### Documents (admin)
| Method | Path | Notes |
|---|---|---|
| POST | `/documents` | upload + metadata + **licence** (required) → async ingestion |
| GET | `/documents` · `/documents/{id}` | listing with `ingest_status` |
| GET | `/documents/{id}/chunks` | inspect chunking — needed for debugging retrieval |
| DELETE | `/documents/{id}` | cascade chunk deletion |

### Evaluation & experiments (admin)
| Method | Path | Notes |
|---|---|---|
| POST | `/eval/runs` | start a suite run (`suite`, `dataset_version`, `config`) |
| GET | `/eval/runs` · `/eval/runs/{id}` | runs with summary metrics |
| GET | `/eval/runs/{id}/results?passed=false` | failure browser |
| GET | `/experiments` · `/experiments/{id}` | baseline vs. candidate comparison |
| GET | `/admin/health` | active sessions, error rates, stage failure counts |
| GET | `/admin/metrics/latency` | aggregates from `messages.latency_ms` |

Eval endpoints are admin-only and separately rate-limited: they are the most expensive endpoints in
the system and the obvious denial-of-wallet target.

## OpenAPI

FastAPI generates the schema; Phase 1 adds a CI check that the committed `openapi.json` matches the
code, so this document and the implementation cannot drift silently.
