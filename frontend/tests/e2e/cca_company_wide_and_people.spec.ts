import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * SoT Addendum A.1 + A.2 (frontend) — company-wide Customer Company
 * Admin (CCA) + People consolidation page.
 *
 * Covers:
 *   1. The "People" sidebar entry + page render: ONE list with type
 *      badges (Contact / Employee / User), reachable under the customer
 *      sidebar, and a drill-in modal (NOT an accordion).
 *   2. The Users page drill-in replaces the old accordion: a "Manage"
 *      button opens the same modal; the old
 *      `customer-user-row-summary-*` accordion row is gone.
 *   3. Company-admin make → the row collapses to a single company-wide
 *      status; remove → it returns to per-building. Gated on
 *      `actions.can_manage_customer_company_admins` (SUPER_ADMIN here).
 *   4. The Overview → Permissions contract still holds (the People page
 *      is additive and never moves the locked quicklink/stat testids).
 *
 * Auth: SUPER_ADMIN so `can_manage_customer_company_admins` is true and
 * the make/remove company-admin controls are present.
 */

const OSIUS_CUSTOMER_NAME = "B Amsterdam";

// API-only requests target the backend origin. In CI the page and API
// share an origin so `baseURL` works; in a split dev setup (Vite on
// :5173, Django on :8000) set PLAYWRIGHT_API_BASE_URL to the backend.
function apiBaseFor(pageBaseURL: string): string {
  return process.env.PLAYWRIGHT_API_BASE_URL ?? pageBaseURL;
}

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
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

/** Resolve the first customer membership's user id so we can target a
 *  concrete person row in the modal flows. */
async function resolveFirstMemberUserId(
  api: APIRequestContext,
  customerId: number,
): Promise<number> {
  const response = await api.get(`/api/customers/${customerId}/users/`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ user_id: number; is_company_admin: boolean }>;
  };
  expect(body.results.length, "customer has at least one member").toBeGreaterThan(
    0,
  );
  // Prefer a member who is NOT already a company admin so the make/remove
  // round-trip starts from a known state.
  const nonAdmin = body.results.find((m) => !m.is_company_admin);
  return (nonAdmin ?? body.results[0]).user_id;
}

test("People page renders type badges + opens a drill-in modal", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // The People sidebar entry is present and navigates to the page.
  const peopleNav = page.locator("[data-testid='sidebar-customer-people']");
  await expect(peopleNav).toBeVisible({ timeout: 10_000 });
  await peopleNav.click();

  await page.waitForURL(/\/admin\/customers\/\d+\/people$/, {
    timeout: 10_000,
  });
  await expect(
    page.locator("[data-testid='customer-people-page']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-testid='section-customer-people']"),
  ).toBeVisible();

  // At least one person row with a type badge.
  const rows = page.locator("[data-testid='customer-person-row']");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator("[data-testid='customer-person-badge-user']").first(),
  ).toBeVisible();

  // Drill-in modal opens on Manage (no accordion).
  await page.locator("[data-testid='customer-person-manage']").first().click();
  await expect(
    page.locator("[data-testid='customer-user-manage-modal']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator("[data-testid='customer-user-company-admin-section']"),
  ).toBeVisible();
  // SUPER_ADMIN may manage company admins → the make-button is present
  // (the chosen member starts as non-admin in the resolver above).
  await expect(
    page.locator("[data-testid='customer-user-make-company-admin']"),
  ).toBeVisible();

  await page.locator("[data-testid='customer-user-manage-close']").click();
  await expect(
    page.locator("[data-testid='customer-user-manage-modal']"),
  ).toHaveCount(0);
});

test("Users page drill-in replaces the accordion + company-admin round-trip", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const userId = await resolveFirstMemberUserId(sa, customerId);
  // Ensure a clean start: make sure the target is NOT a company admin.
  await sa.delete(
    `/api/customers/${customerId}/users/${userId}/company-admin/`,
  );
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}/users`);
  await page.waitForLoadState("networkidle");

  // The old accordion row is gone; the Manage button is the new entry.
  await expect(
    page.locator("[data-testid^='customer-user-row-summary-']"),
  ).toHaveCount(0);
  const manageButtons = page.locator(
    "[data-testid='customer-user-manage-button']",
  );
  await expect(manageButtons.first()).toBeVisible({ timeout: 10_000 });
  await manageButtons.first().click();

  const modal = page.locator("[data-testid='customer-user-manage-modal']");
  await expect(modal).toBeVisible({ timeout: 10_000 });

  // Make company admin → the access editor collapses to a company-wide
  // note inside the modal.
  const makeButton = page.locator(
    "[data-testid='customer-user-make-company-admin']",
  );
  await expect(makeButton).toBeVisible();
  await makeButton.click();

  await expect(
    modal.locator("[data-testid='customer-user-company-admin-access-note']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    modal.locator("[data-testid='customer-user-remove-company-admin']"),
  ).toBeVisible();

  // Remove company admin → returns to the per-building access editor
  // (the reused ContactPermissionsPanel surface).
  await modal
    .locator("[data-testid='customer-user-remove-company-admin']")
    .click();
  // ConfirmDialog (native <dialog>) → click its primary confirm button.
  // Locale-agnostic: target the open dialog's .btn-primary.
  await page.locator("dialog[open] .btn-primary").click();

  await expect(
    modal.locator("[data-testid='contact-permissions-panel']"),
  ).toBeVisible({ timeout: 10_000 });
});

test("Overview → Permissions contract holds with the People page added", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // Locked stat + quicklink testids still present.
  for (const testid of [
    "customer-overview-stat-buildings",
    "customer-overview-stat-users",
    "customer-overview-stat-contacts",
    "customer-overview-stat-pricing",
    "customer-overview-quicklink-permissions",
  ]) {
    await expect(page.locator(`[data-testid='${testid}']`)).toBeVisible({
      timeout: 10_000,
    });
  }

  // No permission-mutating controls leak onto Overview.
  await expect(
    page.locator("[data-testid='customer-overrides-radio']"),
  ).toHaveCount(0);

  // The permissions quicklink still routes to /permissions.
  await page
    .locator("[data-testid='customer-overview-quicklink-permissions']")
    .click();
  await page.waitForURL(/\/admin\/customers\/\d+\/permissions$/, {
    timeout: 10_000,
  });
});
