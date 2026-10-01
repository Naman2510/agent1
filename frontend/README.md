# VaaniOS web app

The student-facing app and the admin dashboard: Next.js 16 (App Router), React 19, Tailwind 4.
Pages are client-rendered and talk to the backend directly; the only server code is the auth
proxy under `src/app/api/auth/`.

```
src/app/               pages: /login, /register, / (sessions), /sessions/[id], /admin
src/app/api/auth/      login, register, refresh, logout — the auth proxy (below)
src/components/        the voice panel, the typed panel, transcript, session list, dashboard
src/lib/api/           typed client for the backend API, with one refresh-and-retry on 401
src/lib/auth/          the in-memory access token and its refresh schedule; AuthProvider
src/lib/voice/         the voice socket client, wire protocol and gap-free playback queue
public/voice-capture-worklet.js   microphone capture: resample to 16 kHz, 20 ms frames
e2e/                   Playwright end-to-end tests
```

## Running it

```bash
npm ci
npm run dev          # http://localhost:3000, against the backend on :8000
npm run lint
npm run typecheck
npm test             # unit tests (Vitest)
npm run build
```

The whole stack (database, Redis, backend, this app) comes up with Docker Compose — see the
repository README.

| Variable | When | What |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | build time | Where the browser reaches the backend; inlined into the bundle |
| `VAANIOS_API_URL` | run time | Where the auth proxy reaches it (on Compose, the internal address); defaults to the above |

## How sign-in works

The backend returns an access token and a refresh token. The access token lives only in memory.
The refresh token never reaches page script: the auth proxy moves it into an `httpOnly`,
`SameSite=Strict` cookie scoped to `/api/auth`, and refreshing goes through the proxy. Refreshes
are serialized across tabs with the Web Locks API, because the backend treats a reused refresh
token as theft and revokes the whole family. The proxy checks that requests come from this
origin, and forwards the client's address so per-IP rate limits apply to the student rather than
to the proxy (docs/SECURITY.md §4).

## End-to-end tests

Real browsers against the real backend, PostgreSQL and Redis. The VAD is the real Silero model,
and the microphone plays recordings of speech, generated from `datasets/v1/voice/fixtures/` when
the run starts. The model providers are faked: the STT and TTS fakes, and the scripted LLM. So the
tests check the application, not a model.

Three engines, as three Playwright projects. Chromium runs everything. Only Chromium can play a
recording as its microphone, so Firefox and WebKit (Safari's engine) run only the flows that need
no microphone: signing in, typed sessions and their history, and the admin page.

They cover: registering, signing in and out, staying signed in across a reload, generic sign-in
errors, the redirect back after signing in; a typed session end to end; a student opening another
student's session; a voice session with a typed question, the Stop button, a spoken question and a
spoken interruption (barge-in), checking what the transcript stores in each case; the admin
dashboard and who can see it; and every page at phone width.

```bash
npm run e2e
```

This starts the backend from `../backend` (its virtualenv, `../backend/venv`, or set `E2E_PYTHON`)
on port 8100 and a production build of this app on 3100, so development servers are left alone.
It needs what the backend needs: `../backend/.env` pointing at a migrated database, Redis, and the
VAD weights (`backend/scripts/fetch_models.sh`). If a browser is missing, run
`npx playwright install chromium firefox webkit`, or run one engine with
`npm run e2e -- --project=chromium`.

To test a stack that is already running instead — CI runs these against the Docker Compose stack,
so the shipped images are what is tested:

```bash
E2E_WEB_URL=http://localhost:3000 E2E_API_URL=http://localhost:8000 \
E2E_PROMOTE_ADMIN="docker compose --env-file .env -f infra/compose.yaml exec -T backend python scripts/promote_admin.py" \
npm run e2e
```

`E2E_PROMOTE_ADMIN` is the command that makes an account an admin (run from the repository root).
Every test registers its own student, so these per-IP limits need raising on the stack under test:
`VAANIOS_RATE_LIMIT_ANONYMOUS_PER_MIN` and `VAANIOS_RATE_LIMIT_REFRESH_PER_MIN`.
