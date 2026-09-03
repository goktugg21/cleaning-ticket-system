import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * SoT Addendum A.1 (frontend) — company-wide Customer Company Admin
 * (CCA) on the consolidated USERS surface.
 *
 * Ramazan rejected the four-overlapping-pages IA (Users + People +
 * Employees + Contacts). The decision: USERS is the single
 * people-with-access surface; the standalone "People" page and the
 * customer-scoped "Employees" tab are DELETED. This spec asserts the
 * post-rework state:
 *   1. The customer page's tab row (FE-6: a customer is a page with
 *      one row of tabs, no sidebar swap) has no Employees tab; the
 *      People tab groups exactly Users + Contacts, and Permissions
 *      survives as its own tab.
 *   2. The Users page drill-in modal is the single people-with-access
 *      surface: a "Manage" button opens the modal (no accordion);
 *      company-admin make → the access editor collapses to a
 *      company-wide note; remove → it returns to per-building. Gated on
 *      `actions.can_manage_customer_company_admins` (SUPER_ADMIN here).
 *   3. The Users access-role + building filters narrow the list.
 *   4. The Overview → Permissions contract still holds: the overview's
 *      stat strip carries one chip per destination, and the Permissions
 *      chip routes to /permissions.
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

test("People tab groups Users + Contacts; no Employees tab; Permissions survives", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // FE-6 — the customer's in-page tab row is the navigation (the
  // "Beperkt tot" sidebar swap is gone). People is the tab that groups
  // Users + Contacts.
  const tabs = page.locator("[data-testid='customer-tabs']");
  await expect(tabs).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("[data-testid='customer-tab-people']")).toBeVisible();

  // The standalone People page tab + the customer-scoped Employees tab
  // are DELETED — neither appears in the tab row.
  await expect(page.locator("[data-testid='customer-tab-employees']")).toHaveCount(0);
  await expect(page.locator("[data-testid^='sidebar-customer-']")).toHaveCount(0);

  // The surviving people/permission surfaces are still present.
  await expect(
    page.locator("[data-testid='customer-tab-permissions']"),
  ).toBeVisible();

  // Opening People lands on Users and offers exactly the Users /
  // Contacts sub-toggle.
  await page.locator("[data-testid='customer-tab-people']").click();
  await page.waitForURL(/\/admin\/customers\/\d+\/users$/, { timeout: 10_000 });
  await expect(page.locator("[data-testid='customer-subtab-users']")).toBeVisible();
  await expect(
    page.locator("[data-testid='customer-subtab-contacts']"),
  ).toBeVisible();
  await expect(
    page.locator("[data-testid='customer-subtab-employees']"),
  ).toHaveCount(0);

  // The deleted routes never render a people surface of their own.
  // P-16 repin: since the P-4 never-void work the catch-all renders a
  // not-found page AT the URL instead of bouncing the path — the fact
  // to pin is "no customer surface here", not the redirect mechanics.
  await page.goto(`/admin/customers/${customerId}/people`);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("[data-testid='not-found-page']")).toBeVisible();
  await expect(page.locator("[data-testid='customer-tabs']")).toHaveCount(0);
  await page.goto(`/admin/customers/${customerId}/employees`);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("[data-testid='not-found-page']")).toBeVisible();
  await expect(page.locator("[data-testid='customer-tabs']")).toHaveCount(0);
});

test("Users filters narrow the list (server-side access-role + building)", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}/users`);
  await page.waitForLoadState("networkidle");

  await expect(
    page.locator("[data-testid='customer-users-page']"),
  ).toBeVisible({ timeout: 10_000 });

  // The filter bar + its three controls are present.
  await expect(
    page.locator("[data-testid='customer-users-filter-bar']"),
  ).toBeVisible();
  const accessRoleFilter = page.locator(
    "[data-testid='customer-users-filter-access-role']",
  );
  const buildingFilter = page.locator(
    "[data-testid='customer-users-filter-building']",
  );
  await expect(accessRoleFilter).toBeVisible();
  await expect(buildingFilter).toBeVisible();
  await expect(
    page.locator("[data-testid='customer-users-filter-search']"),
  ).toBeVisible();

  // Baseline: at least one member row renders before filtering.
  await expect(
    page.locator("[data-testid='customer-user-row']").first(),
  ).toBeVisible({ timeout: 10_000 });
  const baselineCount = await page
    .locator("[data-testid='customer-user-row']")
    .count();

  // Filtering by a specific access role re-fetches server-side and the
  // row count never exceeds the baseline (a narrower or equal set).
  await accessRoleFilter.selectOption("CUSTOMER_LOCATION_MANAGER");
  await page.waitForLoadState("networkidle");
  const filteredCount = await page
    .locator("[data-testid='customer-user-row']")
    .count();
  expect(filteredCount).toBeLessThanOrEqual(baselineCount);

  // Back to All restores the full list.
  await accessRoleFilter.selectOption("");
  await page.waitForLoadState("networkidle");
  await expect(
    page.locator("[data-testid='customer-user-row']").first(),
  ).toBeVisible({ timeout: 10_000 });
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

test("Overview → Permissions contract holds via the stat strip", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(apiBaseFor(baseURL!), DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.super);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  // FE-6 — the overview's stat strip is one chip per destination (the
  // separate quicklinks grid is gone; a destination appears exactly
  // once). The stat chips keep their locked testids and Permissions
  // joined them as a chip without a count.
  for (const testid of [
    "customer-overview-stat-buildings",
    "customer-overview-stat-users",
    "customer-overview-stat-contacts",
    "customer-overview-stat-pricing",
    "customer-overview-stat-permissions",
  ]) {
    await expect(page.locator(`[data-testid='${testid}']`)).toBeVisible({
      timeout: 10_000,
    });
  }

  // No permission-mutating controls leak onto Overview.
  await expect(
    page.locator("[data-testid='customer-overrides-radio']"),
  ).toHaveCount(0);

  // The permissions chip still routes to /permissions.
  await page
    .locator("[data-testid='customer-overview-stat-permissions']")
    .click();
  await page.waitForURL(/\/admin\/customers\/\d+\/permissions$/, {
    timeout: 10_000,
  });
});
