import type { Page } from "@playwright/test";
import type { DemoUser } from "./demoUsers";

/**
 * Sprint 16 — log in via the standard form. Avoids relying on the
 * VITE_DEMO_MODE quick-fill cards so tests still pass when the
 * demo flag is off (e.g. against a near-prod-shaped frontend).
 */
export async function loginAs(page: Page, user: DemoUser): Promise<void> {
  await page.goto("/login");
  await page.locator("#login-email").fill(user.email);
  await page.locator("#login-password").fill(user.password);
  await page.locator(".login-submit").click();
  // Wait until the dashboard route owns the URL — the AuthContext
  // navigates after the token is stored.
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 10_000,
  });
}
