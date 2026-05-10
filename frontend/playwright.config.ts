import { defineConfig, devices } from "@playwright/test";

/**
 * Sprint 16 — Playwright config for the demo / scope smoke tests.
 *
 * The tests assume a running stack:
 *   - Backend (Django) at http://localhost:8000 with the dev compose
 *     OR the prod compose, with `python manage.py seed_demo_data`
 *     applied so the canonical demo accounts exist.
 *   - Frontend served at PLAYWRIGHT_BASE_URL (default
 *     http://localhost:5173, the Vite dev server). Set
 *     PLAYWRIGHT_BASE_URL=http://localhost:80 to run against the
 *     prod-compose nginx instead.
 *
 * Browser binaries are NOT installed by `npm ci` — this config
 * pulls only the test runner. Operator runs once:
 *
 *   npx playwright install chromium
 *
 * before `npm run test:e2e`. CI integration is a separate sprint.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  // Sprint 17: bumped from 30_000 to 120_000 so a single test can
  // absorb up to two auth_token-throttle backoffs (~35s each) inside
  // `loginAs` and still finish without blowing the per-test budget.
  // Most tests still complete in <3s; the new ceiling is a safety
  // valve for the worst case.
  timeout: 120_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    // Ignore HTTPS errors so a dev/prod-compose host with a self-signed
    // cert does not fail the smoke run.
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
