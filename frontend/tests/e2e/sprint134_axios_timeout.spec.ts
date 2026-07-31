import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 134 — both axios clients in api/client.ts used to have no
 * `timeout`, so a stalled request waited indefinitely. For the refresh
 * client specifically, that left `refreshPromise` unsettled forever:
 * every 401 queues behind it, so the page went dead with no console
 * error, and the Sprint 129 session-expired handler never fired because
 * it only runs once the refresh call settles.
 *
 * Both tests force the exact trigger — a protected request 401s, which
 * fires the response interceptor's refresh attempt — via route
 * interception, so neither depends on real token expiry timing. The
 * first leaves the refresh request permanently unfulfilled (Playwright
 * holds it open until this test ends; only the CLIENT's own axios
 * `timeout` can end the wait — proving it now rejects instead of hanging
 * forever). The second 401s the refresh immediately, the ordinary
 * failure path. Both must converge on the SAME outcome: back at /login
 * with the session-expired notice, proving the timeout path isn't a
 * second, differently-behaved code path.
 */

async function fail401Once(
  page: import("@playwright/test").Page,
  pattern: string,
) {
  let calls = 0;
  await page.route(pattern, async (route) => {
    calls += 1;
    if (calls === 1) {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: "{}",
      });
      return;
    }
    await route.continue();
  });
}

test("a hanging token refresh eventually rejects and routes to /login", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);

  // AuthContext's mount effect calls reloadMe() -> GET /auth/me/ on every
  // reload. 401 it exactly once so the response interceptor's refresh
  // attempt fires.
  await fail401Once(page, "**/api/auth/me/");

  // Never call fulfill/continue/abort - the request stays pending for as
  // long as this test runs. This is what "hanging" means: not a slow
  // server, a connection that never resolves at all.
  await page.route("**/api/auth/token/refresh/", async () => {});

  await page.reload();

  // REFRESH_TIMEOUT_MS is 8s (see client.ts) - allow generous slack
  // above it without approaching the 120s test-level ceiling.
  await expect(
    page.locator('[data-testid="login-session-expired"]'),
  ).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/login/);
});

test("a 401'd token refresh routes to /login the same way", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);

  await fail401Once(page, "**/api/auth/me/");
  await page.route("**/api/auth/token/refresh/", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: "{}",
    });
  });

  await page.reload();

  await expect(
    page.locator('[data-testid="login-session-expired"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page).toHaveURL(/\/login/);
});
