import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 3 — sidebar refactor foundation.
 *
 * Validates the URL-derived "customer-scoped" sidebar mode and the
 * Back-to-top-level affordance. Three cases:
 *
 *   1. Customer deep link shows the customer-scoped sidebar.
 *      Navigate directly to `/admin/customers/<id>`; assert the
 *      Back link + a submenu entry (Permissions) are visible AND
 *      the top-level entries (New ticket, Reports) are NOT.
 *
 *   2. Back returns to top-level.
 *      Click the Back link; assert the URL becomes
 *      `/admin/customers` and the top-level entries are visible
 *      again.
 *
 *   3. Non-customer admin route shows top-level sidebar.
 *      Navigate to `/admin/buildings`; assert the top-level
 *      entries are visible AND the customer-scoped submenu is
 *      NOT (no `data-testid="sidebar-customer-permissions"`).
 *
 * Auth: COMPANY_ADMIN (Ramazan @ Osius Demo) — the AdminRoute
 * guard admits SUPER_ADMIN + COMPANY_ADMIN, and the spec uses the
 * narrower role so it also locks in that COMPANY_ADMIN sees the
 * submenu.
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

test("Sprint 28 B3 — customer deep link shows customer-scoped sidebar", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // Customer-scoped submenu entries are visible.
  await expect(
    page.locator("[data-testid='sidebar-customer-back']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator("[data-testid='sidebar-customer-permissions']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-testid='sidebar-customer-buildings']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-testid='sidebar-customer-contacts']"),
  ).toBeVisible();

  // Top-level entries are NOT rendered. The customer-scoped mode
  // replaces (not appends after) the operations group.
  await expect(
    page.locator(".sidebar-nav a[href='/tickets/new']"),
  ).toHaveCount(0);
  await expect(page.locator(".sidebar-nav a[href='/reports']")).toHaveCount(0);
  // The customers list link itself only appears as the "Back"
  // target in this mode, so direct `/admin/customers` link in the
  // admin group should not be present.
  await expect(
    page.locator(".sidebar-nav a.nav-item[href='/admin/buildings']"),
  ).toHaveCount(0);
});

test("Sprint 28 B3 — Back link returns to top-level sidebar", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  const backLink = page.locator("[data-testid='sidebar-customer-back']");
  await expect(backLink).toBeVisible({ timeout: 10_000 });
  await backLink.click();

  // URL becomes the customers list page.
  await page.waitForURL(/\/admin\/customers$/, { timeout: 10_000 });
  expect(new URL(page.url()).pathname).toBe("/admin/customers");

  // Top-level entries are back.
  await expect(
    page.locator(".sidebar-nav a[href='/tickets/new']"),
  ).toBeVisible();
  await expect(
    page.locator(".sidebar-nav a[href='/admin/buildings']"),
  ).toBeVisible();

  // Customer-scoped submenu is gone.
  await expect(
    page.locator("[data-testid='sidebar-customer-permissions']"),
  ).toHaveCount(0);
  await expect(
    page.locator("[data-testid='sidebar-customer-back']"),
  ).toHaveCount(0);
});

test("Sprint 28 B3 — non-customer admin route shows top-level sidebar", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/admin/buildings");
  await page.waitForLoadState("networkidle");

  // Top-level entries present.
  await expect(
    page.locator(".sidebar-nav a[href='/tickets/new']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator(".sidebar-nav a[href='/admin/customers']"),
  ).toBeVisible();

  // Customer-scoped submenu absent — `/admin/buildings` matches
  // the top-level branch, not the customer-scoped pattern.
  await expect(
    page.locator("[data-testid='sidebar-customer-permissions']"),
  ).toHaveCount(0);
  await expect(
    page.locator("[data-testid='sidebar-customer-back']"),
  ).toHaveCount(0);
});
