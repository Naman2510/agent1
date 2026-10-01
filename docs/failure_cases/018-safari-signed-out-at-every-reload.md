# FC-018 — On the local stack, Safari signed the student out at every reload

**Status:** fixed
**Found:** 2026-10-01 · **Phase:** after 10 (the end-to-end suite's first WebKit run, M7-02) ·
**Component:** web app (auth proxy)
**Severity:** major. Every page load after the first needs the refresh cookie, so a student on
Safari could use nothing past the page they signed in on.
**Case IDs:** `e2e/auth.spec.ts` "a reload keeps the student signed in, from a cookie page script
cannot read", in the `webkit` project; `auth-proxy.test.ts` "marks the cookie Secure exactly when
the app is served over HTTPS"

## Input

The Docker Compose stack as the README documents it: a production build of the web app, served
over plain HTTP at `http://localhost:3000`. A student registers in WebKit (Safari's engine), then
reloads the page, or opens a session, the history or the admin page.

## Expected

The student stays signed in, as they do in Chromium and Firefox. The refresh cookie restores the
session after a reload (ARCHITECTURE, SECURITY.md §3).

## Actual

The first run in WebKit (CI #59) failed 6 of its 9 tests, every one that depends on staying signed
in:

```
[webkit] › auth.spec.ts › a reload keeps the student signed in, from a cookie page script cannot read
[webkit] › sessions.spec.ts › a typed question streams an answer, and both are kept
[webkit] › sessions.spec.ts › an answer in the history shows the tools it used and the sources it cited
[webkit] › sessions.spec.ts › a student cannot open another student's session
[webkit] › admin.spec.ts › a student is kept out of the admin page
[webkit] › admin.spec.ts › an admin sees the dashboard, counting what just happened
26 passed
```

Registering, a failed sign-in, and the redirect back after signing in passed. Chromium passed all
14 of its tests and Firefox all 9 of its.

## Root cause

The auth proxy set the refresh cookie `Secure` whenever the app was a production build
(`NODE_ENV === "production"`). The Compose stack serves a production build over plain HTTP.
Chromium and Firefox treat `http://localhost` as a secure context and keep a `Secure` cookie there.
WebKit does not, so it dropped the cookie, and every refresh found none. Phase 7 named exactly this
as unverified (PHASE_7_AUDIT M7-02); no test could see it while the suite ran in Chromium alone.

The rule confused two questions: whether the build is a production build, and whether the app is
served over HTTPS. Only the second decides whether `Secure` means anything.

## Fix

`frontend/src/lib/server/auth-proxy.ts`, at 9ad5305: the cookie is `Secure` exactly when the app is
served over HTTPS. That is judged as `next.config.ts` already judged it for HSTS and
`upgrade-insecure-requests`: by the address the browser uses for the API, fixed at build time. A
real HTTPS deployment keeps the flag. Over plain HTTP it never protected anything. A unit test
checks both sides under a production build, and fails with the old rule.

## Result

CI #60: 32 of 32 end-to-end runs pass, all 9 of WebKit's among them.

What is still not covered: voice in Firefox and WebKit, since only Chromium can play a recording as
its microphone, and Safari's real audio stack on a device (M7-02).
