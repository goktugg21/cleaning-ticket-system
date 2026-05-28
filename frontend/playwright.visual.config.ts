import { defineConfig, devices } from "@playwright/test";

/**
 * Visual screenshot harness — separate from the e2e bundle.
 *
 * The default `playwright.config.ts` pins `testDir` to `./tests/e2e`
 * because the spec bundle is the contract. Visual specs under
 * `tests/visual/` are for human review (screenshots checked into the
 * repo as PR evidence) and intentionally do NOT run in the spec
 * bundle. This config loads the same browser + base URL but points
 * Playwright at the visual directory.
 */
export default defineConfig({
  testDir: "./tests/visual",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  timeout: 120_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
