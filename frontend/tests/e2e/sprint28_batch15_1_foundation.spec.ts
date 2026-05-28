import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

// The Vite dev server does not proxy /api/* — the frontend's axios
// client talks to VITE_API_BASE_URL directly. Mirror that contract
// here so this spec works without depending on PLAYWRIGHT_BASE_URL
// being set to the prod-compose nginx host.
const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:8000";

async function apiAs(
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  const loginCtx = await request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
  });
  const tokenResponse = await loginCtx.post("/api/auth/token/", {
    data: { email, password },
  });
  expect(tokenResponse.status()).toBe(200);
  const body = (await tokenResponse.json()) as { access: string };
  await loginCtx.dispose();
  return await request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
  });
}

async function resolveFirstCustomerId(api: APIRequestContext): Promise<number> {
  const response = await api.get("/api/customers/?page_size=1");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  expect(body.results.length, "demo seed has at least one customer").toBeGreaterThan(0);
  return body.results[0].id;
}

/**
 * Sprint 28 Batch 15.1 — design-system foundation primitives.
 *
 * The batch unifies the brand identity to "CleanOps" across the
 * shell, replaces the inline topbar identity block with a
 * UserMenu dropdown that includes a one-click language toggle,
 * and scrubs raw enum strings out of the customer settings
 * helper copy. These tests lock the visible contract so later
 * batches (15.2 Permissions rebuild, 15.5 sidebar polish) cannot
 * accidentally regress the brand wording or the topbar shape.
 */

test.describe("Sprint 28 Batch 15.1 — foundation primitives", () => {
  test("brand name CleanOps appears in sidebar and topbar consistently", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/");

    // Sidebar brand.
    await expect(page.locator(".brand-name")).toHaveText("CleanOps");
    // Topbar context name.
    await expect(page.locator(".topbar-context-name")).toHaveText("CleanOps");
    // Sidebar footer.
    await expect(page.locator(".footer-sys-name")).toContainText("CleanOps");

    // FacilityPro and VERIDIAN must not appear anywhere on the
    // authenticated shell.
    await expect(page.locator("body")).not.toContainText("FacilityPro");
    await expect(page.locator("body")).not.toContainText("VERIDIAN");
  });

  test("user menu opens and contains language toggle + sign out", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/");

    const trigger = page.locator(".user-menu-trigger");
    await expect(trigger).toBeVisible();

    await trigger.click();
    const panel = page.locator(".user-menu-panel");
    await expect(panel).toBeVisible();

    // Language toggle is the segmented control inside the panel.
    await expect(panel.locator(".user-menu-lang-toggle")).toBeVisible();

    // Sign out lives inside the menu (no longer in the topbar).
    await expect(
      panel.getByRole("menuitem", { name: /sign out|uitloggen|afmelden/i }),
    ).toBeVisible();

    // Escape closes the panel.
    await page.keyboard.press("Escape");
    await expect(page.locator(".user-menu-panel")).toHaveCount(0);
  });

  test("language toggle in user menu switches NL <-> EN", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/");

    // Open the user menu, click NL.
    await page.locator(".user-menu-trigger").click();
    const panel = page.locator(".user-menu-panel");
    await expect(panel).toBeVisible();
    await panel
      .locator(".user-menu-lang-option", { hasText: /^NL$/i })
      .click();
    // Wait for the i18next switch to settle in the DOM.
    await expect(page.locator(".brand-tag")).toHaveText("Operationele console");

    // Switch back to EN. Re-open the menu (selecting a lang may not
    // close it, but a click outside is enough to dismiss in some
    // layouts — re-open defensively).
    if ((await page.locator(".user-menu-panel").count()) === 0) {
      await page.locator(".user-menu-trigger").click();
    }
    await page
      .locator(".user-menu-panel .user-menu-lang-option", {
        hasText: /^EN$/i,
      })
      .click();
    await expect(page.locator(".brand-tag")).toHaveText("Operations console");
  });

  test("no raw enum strings leak in customer settings helper text", async ({
    page,
  }) => {
    // Resolve a real customer id via the API so the route is valid
    // regardless of auto-increment shuffles in the demo seed.
    const sa = await apiAs(DEMO_USERS.super.email);
    const customerId = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/settings`);
    await expect(
      page.locator("[data-testid='sidebar-customer-settings']"),
    ).toBeVisible({ timeout: 10_000 });

    const body = page.locator("body");
    // The two known leak strings must not appear in the helper text
    // after the i18n scrub of customer_view.settings.visibility_helper
    // and user_form.role_staff_helper.
    await expect(body).not.toContainText("CUSTOMER_USER");
    await expect(body).not.toContainText("BUILDING_MANAGER");
  });
});
