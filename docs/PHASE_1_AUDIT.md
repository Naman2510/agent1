# Phase 1 Audit — Audit Gate 1

**Reviewed:** the Phase 1 backend foundation — app factory, config, logging, error surface,
migrations, models, repositories, auth service, routes, rate limiting, containerisation, CI.
**Date:** 2026-09-17 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions, plus the Phase 1 gate criteria from
[ROADMAP.md](ROADMAP.md#phase-1--backend-foundation), each checked by running something rather than
by reading code.

**Outcome:** 4 defects found and fixed during the phase, 6 Major items scheduled, 5 Minor recorded.
**Gate status: PASSED.** Phase 2 may begin. Phase 3 remains gated on C-05(b) from
[Gate 0](PHASE_0_AUDIT.md) — the truncated source specification.

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Migrations reversible | `alembic upgrade head → downgrade base → upgrade head`; 8 tables and 4 enums created, 0 tables and 0 enum types left after downgrade | pass |
| Migrations match the models | `alembic check` → "No new upgrade operations detected" (in CI) | pass |
| IDOR test per endpoint taking a resource id | `test_authorization.py`, parametrised over `GET /sessions/{id}`, `GET /sessions/{id}/messages`, `POST /sessions/{id}/end` | pass |
| Rate limits asserted | 3 HTTP tests + 7 unit tests, including refill behaviour and fail-open | pass |
| No secrets in the repository | `.env` git-ignored, `.env.example` values-free, gitleaks in CI | pass |
| Coverage on `core/` and `db/` | 93% overall; `core/rate_limit` 100%, `core/logging` 100%, `db/models` 100% | pass |
| Something runnable | `uvicorn app.asgi:app` serving real HTTP: register → me → session → refresh rotation → replay 401 → admin 403 | pass |

61 tests, `ruff check`, `ruff format --check`, and `mypy app` all clean.

---

## 2. Defects found and fixed during the phase

These are recorded because *how* they were caught is the useful part.

### D-01 — A security-critical write was silently discarded by the error path
**Severity: high.** On refresh-token reuse, `AuthService.refresh` revoked the compromised token
family and then raised. The request-scoped transaction rolls back on any exception, so the
revocation was rolled back with it: the attacker's stolen token was rejected, but every token in
the family stayed **valid**. The reuse detection was decorative.

Caught by `test_refresh_reuse_revokes_the_whole_family`, which asserts the *descendant* token is
also dead — not just that the replay returns 401. A test that only checked the replay would have
passed against the broken code.

**Fix:** `_commit_security_action()` commits revocations before raising, with the reasoning in a
docstring so it is not "simplified" away later.

**Generalisation:** any security action taken on an error path has this shape. A Phase 2 review item
is to check the same pattern wherever a deny decision writes state.

### D-02 — Tests validated a schema that existed nowhere
**Severity: medium.** The migration set nine server defaults that the SQLAlchemy models did not
declare. Tests built their schema with `Base.metadata.create_all` (models), production runs
`alembic upgrade head` (migrations) — so the suite was green against a schema no deployment had.

Caught by running `alembic check` rather than by any test.

**Fix, two parts:** the models now declare the same server defaults, **and** the test suite builds
its schema by running the real migrations, so the two cannot diverge again without a failing suite.
CI runs `alembic check` as a backstop. Written up in [DATA_MODEL.md §8](DATA_MODEL.md).

### D-03 — Dependencies read configuration from the environment, not from the app
**Severity: medium.** `SettingsDep` resolved `get_settings()`, an `lru_cache`d read of the process
environment, while `create_app(settings)` took settings explicitly. Any caller constructing an app
with its own settings — every test, and any future multi-tenant or embedded use — got one
configuration in the factory and a different one inside the routes, including a different JWT
secret. It surfaced as a 500 on `/health`.

**Fix:** `get_app_settings(request)` reads `request.app.state.settings`. `get_settings()` remains,
but only as the default for the ASGI entrypoint.

### D-04 — A coverage number was wrong by 39 points, in the flattering-to-fix direction
**Severity: low for the code, high for the project's premise.** `app/services/auth.py` reported
**44%** coverage while its code was demonstrably executing (the tests asserted on its behaviour).
SQLAlchemy's asyncio bridge runs code inside greenlets, which coverage cannot trace by default. The
true figure is **83%**.

This one matters beyond itself: this project's central claim is that its numbers are real. A
plausible-looking metric that is silently wrong is exactly the failure mode being guarded against —
and it was wrong in the direction that would have prompted writing tests that were not needed.

**Fix:** `concurrency = ["greenlet", "thread"]` in `[tool.coverage.run]`, with the reason in a
comment. Total coverage is 93%, not the 85% first reported.

---

## 3. Major findings (scheduled)

**M1-01 — The rate limiter fails open.** A Redis outage disables rate limiting entirely rather than
refusing traffic. This is deliberate (an availability-over-protection trade for a tutoring product,
logged at WARNING), but it means a Redis outage is also a brute-force window. *Scheduled Phase 9:*
a process-local fallback bucket so an outage degrades to a coarse limit rather than none.

**M1-02 — Per-IP anonymous limiting is weak against distributed attacks and harsh behind NAT.**
10/min per hashed IP throttles a single-source credential-stuffing run, and a campus NAT shares one
IP across many students. *Scheduled Phase 9:* per-account failure counters with progressive delay,
alongside the IP limit.

**M1-03 — No account lockout or breach-password check.** Argon2id plus throttling is the whole
defence. *Scheduled Phase 9:* consider a k-anonymity breached-password check at registration.

**M1-04 — No WebSocket authentication yet.** The handshake auth, the 60-minute cap, and
`session.reauth` are designed (ARCHITECTURE §10, Gate 0 finding M-08) but unimplemented because
there is no WebSocket yet. *Scheduled Phase 3, and it is a Gate 3 criterion.*

**M1-05 — `pip-audit` is non-blocking in CI.** A new advisory in a transitive dependency currently
emits a warning. Deliberate while the dependency set is still moving; *scheduled Phase 9* to become
blocking with an explicit ignore list.

**M1-06 — No load or concurrency testing.** Pool sizes (10 + 5 overflow) and the session-per-request
pattern are untested under concurrency. *Scheduled Phase 9.*

---

## 4. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m1-01 | `scripts/dev_db.sh` runs PostgreSQL without pgvector, so it is only usable through Phase 4 | Documented in the script and the README; Compose is the supported path |
| m1-02 | `POST /auth/register` hashes the password twice (once to create, once via `login`) | Measurable only at production Argon2 cost on the registration path; revisit if it shows up |
| m1-03 | `audit_log` exists but nothing writes to it yet | Phase 6, with the admin and ingestion endpoints that need it |
| m1-04 | Health and readiness are unauthenticated | Intentional (orchestrators cannot log in) and deliberately uninformative; no version or hostname disclosed beyond the app version |
| m1-05 | This audit is a self-review, as Gate 0 was | Recorded rather than claimed away |

---

## 5. Dimensions reviewed with no finding above Minor

**Security.** Authorization is enforced in the repository layer as designed: `SessionRepository`
exposes no unscoped lookup, so an IDOR cannot be written in a route even by accident. Absent and
foreign resources return identical 404s. Login failures are identical for unknown accounts and wrong
passwords, and the unknown-account path still performs a hash so the timing is comparable.
Validation errors return field locations only, never submitted values — asserted by a test that the
submitted password does not appear in the response. Token type is checked, so a refresh token cannot
be used as a bearer credential; `alg=none` is rejected.

**Architecture consistency.** The implementation matches the Phase 0 design where it touches it:
`student_id` is available only via `CurrentUser.require_student_id()` and appears in no request
schema, which is the load-bearing rule for ARCHITECTURE §8.4 when tools arrive in Phase 6. The
`messages` table carries `was_interrupted` / `spoken_prefix_chars` / `unspoken_remainder`, and the
transcript endpoint returns the spoken prefix while never exposing the unspoken tail — the barge-in
invariant from §5.3 is already enforced at the API boundary, before the code that will depend on it
exists.

**Unnecessary complexity.** Nothing in Phase 1 is speculative: no repository method exists without a
caller, no table is created before the code that reads it, and the deferred Gate 0 items (Prometheus,
WebRTC, Qdrant) remain deferred.

**Testing strategy.** Tests assert behaviour, not shape. Representative: the rate-limit test
distinguishes a token bucket from a fixed window by advancing a patched clock; the erasure test
counts rows in five tables before and after; the drift that D-02 exposed is now structurally
impossible rather than watched for.

---

## 6. Gate decision

**PASSED.** Phase 2 (provider layer and the text LLM path) may begin.

Carried forward into Phase 2: the spend-cap mechanism and daily voice-minute limit
([M-11](PHASE_0_AUDIT.md)), and a review of D-01's generalisation — security actions written on
error paths.

Still blocking Phase 3: **C-05(b)** — the remainder of the truncated specification, or confirmation
that the reconstructed roadmap stands.
