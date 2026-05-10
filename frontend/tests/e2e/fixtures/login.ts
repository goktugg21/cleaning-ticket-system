import type { Page } from "@playwright/test";
import type { DemoUser } from "./demoUsers";

/**
 * Sprint 16 — log in via the standard form. Avoids relying on the
 * VITE_DEMO_MODE quick-fill cards so tests still pass when the
 * demo flag is off (e.g. against a near-prod-shaped frontend).
 *
 * Sprint 17 — auth_token-throttle tolerance.
 *
 *   The backend ships with `DRF_THROTTLE_AUTH_TOKEN_RATE=20/minute`
 *   (see backend/config/settings.py). The Playwright suite easily
 *   crosses that threshold — at workers=1 with ~2s per test the rate
 *   reaches ~30 logins/min by mid-run. When a login is throttled the
 *   API returns 429 and the form never navigates away from /login;
 *   the next test sees a stale session and the run fails non-
 *   deterministically.
 *
 *   We listen for the /api/auth/token/ response, and on 429 wait the
 *   rolling-window margin (~35s) and try again. Up to 2 retries so a
 *   doubly-unlucky test still completes. Tests that use this helper
 *   should run with `timeout >= 120_000` in playwright.config.ts so
 *   the worst-case retry path fits.
 */
export async function loginAs(page: Page, user: DemoUser): Promise<void> {
  const MAX_ATTEMPTS = 3;
  const THROTTLE_BACKOFF_MS = 35_000;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    await page.goto("/login");

    // Arm the response listener BEFORE the click so we never miss
    // the request even on a fast network.
    const tokenResponsePromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/auth/token/") &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );

    await page.locator("#login-email").fill(user.email);
    await page.locator("#login-password").fill(user.password);
    await page.locator(".login-submit").click();

    const response = await tokenResponsePromise;
    const status = response.status();

    if (status === 200) {
      // AuthContext stores the token then navigate("/", replace).
      await page.waitForURL((url) => !url.pathname.includes("/login"), {
        timeout: 10_000,
      });
      return;
    }

    if (status === 429 && attempt < MAX_ATTEMPTS) {
      // Throttle window is sliding-60s on the backend; wait long
      // enough that at least one of the older requests ages out.
      await page.waitForTimeout(THROTTLE_BACKOFF_MS);
      continue;
    }

    throw new Error(
      `Login for ${user.email} failed with HTTP ${status} on attempt ${attempt}.`,
    );
  }
}
