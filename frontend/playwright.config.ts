import { defineConfig, devices } from "@playwright/test";

import { fakeMicrophone, SILENCE_WAV } from "./e2e/support/audio";
import { API_URL, BACKEND, externalStack, PYTHON, WEB_URL } from "./e2e/support/stack";

/**
 * End-to-end: a real browser against the real backend, PostgreSQL and Redis, with the model
 * providers faked — the fake STT and TTS are the only ones that exist yet, and the LLM is the
 * scripted one. The VAD is real, and the microphone plays recordings of real (synthesized) speech.
 *
 * `npm run e2e` starts the backend from ../backend (it needs that directory's .env, with its
 * database migrated) and a production build of this app, on ports 8100 and 3100 so a development
 * server is left alone. With E2E_WEB_URL and E2E_API_URL set it starts nothing and drives that
 * stack instead: CI runs it against the Docker Compose stack.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  // Serial: the microphone plays in real time and the voice tests depend on its timing, so they
  // should not share the machine with each other.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: WEB_URL,
    permissions: ["microphone"],
    // A silent microphone unless a test plays something: the default fake device beeps.
    launchOptions: { args: fakeMicrophone(SILENCE_WAV, { loop: true }) },
    trace: "retain-on-failure",
  },
  webServer: externalStack
    ? undefined
    : [
        {
          command: `"${PYTHON}" -m uvicorn app.asgi:app --host 127.0.0.1 --port ${new URL(API_URL).port}`,
          cwd: BACKEND,
          url: `${API_URL}/v1/health`,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            VAANIOS_LLM_PROVIDER: "fake",
            VAANIOS_CORS_ORIGINS: WEB_URL,
            // Every test registers its own student from this one address. The per-address
            // limits are there for credential stuffing and are tested in the backend suite.
            VAANIOS_RATE_LIMIT_ANONYMOUS_PER_MIN: "1000",
            VAANIOS_RATE_LIMIT_REFRESH_PER_MIN: "1000",
          },
        },
        {
          command: "npm run e2e:serve",
          url: `${WEB_URL}/login`,
          reuseExistingServer: false,
          timeout: 300_000,
          env: {
            NEXT_PUBLIC_API_URL: API_URL,
            VAANIOS_API_URL: API_URL,
            HOSTNAME: "127.0.0.1",
            PORT: new URL(WEB_URL).port,
          },
        },
      ],
});
