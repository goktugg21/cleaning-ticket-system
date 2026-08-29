import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 3 — customer navigation foundation.
 * FE-6 (Addendum D §D.3.4) — REWRITTEN for the replacement surface.
 *
 * The Batch 3 "customer-scoped sidebar" (the global nav swapped out for
 * a Back link + submenu whenever the URL was under /admin/customers/:id)
 * is gone. A customer is now a PAGE: the global nav stays where it is,
 * and the customer page carries a header with a back link plus ONE row
 * of tabs (`customer-tabs`). Three cases, same intent as before:
 *
 *   1. Customer deep link shows the customer tab row.
 *      Navigate directly to `/admin/customers/<id>`; assert the tab
 *      row + its Permissions / Buildings / People tabs are visible AND
 *      the global nav is still there (you never left).
 *
 *   2. Back returns to the customers list.
 *      Click the header's back link; assert the URL becomes
 *      `/admin/customers` and the tab row is gone.
 *
 *   3. Non-customer admin route shows no customer tab row.
 *      Navigate to `/admin/buildings`; assert the global nav entries
 *      are visible AND no `customer-tabs` is rendered.
 *
 * Auth: COMPANY_ADMIN (Ramazan @ Osius Demo) — the AdminRoute
 * guard admits SUPER_ADMIN + COMPANY_ADMIN, and the spec uses the
 * narrower role so it also locks in that COMPANY_ADMIN sees the tabs.
 *
 * Customer id resolution: the demo seed creates "B Amsterdam"
 * under Osius Demo. We resolve its id via the customers list API
 * rather than hard-coding, so the spec survives a reseed that
 * shuffles auto-increment ids.
 */

const OSIUS_CUSTOMER_NAME = "B Amsterdam";

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  // Sprint 28 Batch 3 — same 429 backoff pattern used elsewhere in
  // the suite. The full Playwright run can cross the 20/min
  // auth_token throttle when several specs use apiAs.
  const MAX_ATTEMPTS = 3;
  const THROTTLE_BACKOFF_MS = 35_000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const loginCtx = await request.newContext({
      baseURL,
      ignoreHTTPSErrors: true,
    });
    const tokenResponse = await loginCtx.post("/api/auth/token/", {
      data: { email, password },
    });
    const status = tokenResponse.status();
    if (status === 200) {
      const body = (await tokenResponse.json()) as { access: string };
      await loginCtx.dispose();
      return await request.newContext({
        baseURL,
        ignoreHTTPSErrors: true,
        extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
      });
    }
    await loginCtx.dispose();
    if (status === 429 && attempt < MAX_ATTEMPTS) {
      await new Promise((r) => setTimeout(r, THROTTLE_BACKOFF_MS));
      continue;
    }
    expect(
      status,
      `token request for ${email} should succeed (attempt ${attempt})`,
    ).toBe(200);
  }
  throw new Error(`apiAs(${email}) exhausted attempts`);
}

async function resolveCustomerId(
  api: APIRequestContext,
  customerName: string,
): Promise<number> {
  const response = await api.get("/api/customers/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match = body.results.find((c) => c.name === customerName);
  expect(match, `customer ${customerName} present`).toBeTruthy();
  return match!.id;
}

test("FE-6 — customer deep link shows the customer tab row, global nav stays", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // The customer page's own header + tab row are visible.
  await expect(
    page.locator("[data-testid='customer-page-header']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("[data-testid='customer-tabs']")).toBeVisible();
  await expect(
    page.locator("[data-testid='customer-tab-permissions']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-testid='customer-tab-buildings']"),
  ).toBeVisible();
  await expect(page.locator("[data-testid='customer-tab-people']")).toBeVisible();

  // The global nav is NOT replaced: the top-level entries stay put.
  await expect(page.locator("[data-testid='sidebar-new']")).toBeVisible();
  await expect(page.locator("[data-testid='sidebar-tickets']")).toBeVisible();
  await expect(
    page.locator(".sidebar-nav a[href='/admin/buildings']"),
  ).toBeVisible();
  // ...and the old scoped submenu never renders.
  await expect(page.locator("[data-testid^='sidebar-customer-']")).toHaveCount(0);
});

test("FE-6 — the header's back link returns to the customers list", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  const header = page.locator("[data-testid='customer-page-header']");
  await expect(header).toBeVisible({ timeout: 10_000 });
  const backLink = header.locator("a[href='/admin/customers']").first();
  await expect(backLink).toBeVisible();
  await backLink.click();

  // URL becomes the customers list page.
  await page.waitForURL(/\/admin\/customers$/, { timeout: 10_000 });
  expect(new URL(page.url()).pathname).toBe("/admin/customers");

  // Top-level entries are (still) there.
  await expect(page.locator("[data-testid='sidebar-new']")).toBeVisible();
  await expect(
    page.locator(".sidebar-nav a[href='/admin/buildings']"),
  ).toBeVisible();

  // The customer tab row is gone with the customer page.
  await expect(page.locator("[data-testid='customer-tabs']")).toHaveCount(0);
  await expect(
    page.locator("[data-testid='customer-page-header']"),
  ).toHaveCount(0);
});

test("FE-6 — non-customer admin route renders no customer tab row", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/admin/buildings");
  await page.waitForLoadState("networkidle");

  // Top-level entries present.
  await expect(page.locator("[data-testid='sidebar-new']")).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.locator(".sidebar-nav a[href='/admin/customers']"),
  ).toBeVisible();

  // Customer tab row absent — `/admin/buildings` is not a customer page.
  await expect(page.locator("[data-testid='customer-tabs']")).toHaveCount(0);
  await expect(page.locator("[data-testid^='sidebar-customer-']")).toHaveCount(0);
});
