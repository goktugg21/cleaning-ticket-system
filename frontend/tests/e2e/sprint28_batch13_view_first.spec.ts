/**
 * Sprint 28 Batch 13 (rework) — view-first refactor of admin customer
 * pages + unified operations dashboard.
 *
 * What's locked here:
 *   1. `/admin/customers/:id` (Overview) renders the new Overview
 *      page with the stat strip, quicklinks grid, and buildings
 *      preview AND NO permission affordances (no override radios,
 *      no policy toggles, no "Edit permissions" buttons).
 *   2. `/admin/customers/:id/permissions` renders the new
 *      Permissions page with permission affordances intact (at
 *      least one `customer-policy-toggle` exists).
 *   3. BUILDING_MANAGER read-only customer detail still works —
 *      the `ByRole` dispatcher in App.tsx routes BM to
 *      `BuildingManagerCustomerDetailPage`, NOT the new Overview.
 *   4. Dashboard segmented work-view toggle hides / shows the
 *      Tickets and Extra Work sections, the unified 5-card top KPI
 *      strip always renders, and `view=all` carries a single
 *      "Recent operational items" card.
 *   5. `/admin/customers/:id/buildings` shows a real shell (not the
 *      placeholder) and `/admin/customers/:id/users` shows a per-
 *      user access summary cell.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

const OSIUS_CUSTOMER_NAME = "B Amsterdam";

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

test.describe("Sprint 28 Batch 13 — view-first customer pages", () => {
  test("overview has no permission controls and surfaces useful summary", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}`);

    // Overview page renders.
    await expect(page.getByTestId("customer-overview-page")).toBeVisible({
      timeout: 15_000,
    });

    // New summary scaffolding from the Batch 13 rework: stat strip
    // (4 cards), buildings preview card, quicklinks grid (>= 6
    // anchors).
    await expect(
      page.getByTestId("customer-overview-stat-strip"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-stat-buildings"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-stat-users"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-stat-contacts"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-stat-pricing"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-buildings-preview"),
    ).toBeVisible();
    await expect(
      page.getByTestId("customer-overview-quicklinks"),
    ).toBeVisible();
    // The quicklinks grid has six management areas. Anchor on count.
    const quicklinks = page.locator(
      '[data-testid^="customer-overview-quicklink-"]',
    );
    expect(await quicklinks.count()).toBeGreaterThanOrEqual(6);

    // Permission affordances are NOT present on the Overview surface.
    await expect(
      page.getByTestId("customer-overrides-radio"),
    ).toHaveCount(0);
    await expect(page.getByTestId("customer-policy-toggle")).toHaveCount(0);
    await expect(
      page.getByTestId("customer-access-overrides-button"),
    ).toHaveCount(0);
  });

  test("permissions page renders permission controls", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/permissions`);

    await expect(page.getByTestId("customer-permissions-page")).toBeVisible({
      timeout: 15_000,
    });

    // RF-8 (#106) — the detailed policy grid moved behind the collapsed
    // "Geavanceerd" card; open it before asserting the toggles.
    await page
      .locator('[data-testid="customer-permissions-advanced-toggle"]')
      .click();

    // At least one policy toggle resolves — the policy panel has
    // four booleans wired through this testid.
    const policyToggles = page.getByTestId("customer-policy-toggle");
    await expect(policyToggles.first()).toBeVisible({ timeout: 15_000 });
    expect(await policyToggles.count()).toBeGreaterThan(0);
  });

  test("customer buildings page is not a placeholder", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/buildings`);

    await expect(page.getByTestId("customer-buildings-page")).toBeVisible({
      timeout: 15_000,
    });
    // Either the buildings table OR a typed empty-state should render
    // — never the legacy placeholder.
    const table = page.getByTestId("customer-buildings-table");
    const empty = page.getByTestId("customer-buildings-empty");
    const tableCount = await table.count();
    const emptyCount = await empty.count();
    expect(tableCount + emptyCount).toBeGreaterThan(0);
  });

  test("customer users page shows access summary", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/users`);

    await expect(page.getByTestId("customer-users-page")).toBeVisible({
      timeout: 15_000,
    });
    // Either at least one per-user access summary cell renders, or
    // the typed empty-state copy renders. Both are valid outcomes.
    const access = page.getByTestId("customer-user-access-summary");
    const empty = page.getByTestId("customer-users-empty");
    const accessCount = await access.count();
    const emptyCount = await empty.count();
    expect(accessCount + emptyCount).toBeGreaterThan(0);
  });

  test("bm read-only customer detail still works", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.managerAll);
    await page.goto("/admin/customers");

    // Resolve a BM-scoped customer by clicking the first list row.
    const firstLink = page.getByTestId(/^bm-customer-link-/).first();
    await expect(firstLink).toBeVisible({ timeout: 15_000 });
    await firstLink.click();

    // BM still gets the read-only detail page, NOT the new admin
    // Overview.
    await expect(page.getByTestId("bm-customer-detail-page")).toBeVisible({
      timeout: 15_000,
    });

    // The admin Overview testid is NOT rendered for BM.
    await expect(page.getByTestId("customer-overview-page")).toHaveCount(0);

    // No "Edit basics" affordance for BM (and no permission radios
    // anyway — that's a separate page, but anchor on the absence to
    // keep the spec self-contained).
    await expect(
      page.getByTestId("customer-overview-edit-basics"),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("customer-overrides-radio"),
    ).toHaveCount(0);
  });
});

test.describe("Sprint 28 Batch 13 — dashboard work-view toggle", () => {
  test("dashboard work view toggle and unified ops KPI strip", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/");

    // Unified KPI strip is always visible — same five testids no
    // matter the active work-view.
    await expect(page.getByTestId("dashboard-ops-kpi-row")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByTestId("dashboard-ops-kpi-total"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-ops-kpi-tickets"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-ops-kpi-extra-work"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-ops-kpi-awaiting"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-ops-kpi-urgent"),
    ).toBeVisible();

    // Default view=all renders the unified Recent operational items
    // card AND the dashboard-tickets-section wrapper that the legacy
    // contract still expects.
    await expect(page.getByTestId("dashboard-recent-ops")).toBeVisible();
    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible();

    // Switch to tickets-only — extra-work section gone.
    await page.getByTestId("dashboard-work-view-tickets").click();
    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toHaveCount(0);

    // Switch to extra-work-only — tickets section gone.
    await page.getByTestId("dashboard-work-view-extra-work").click();
    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toBeVisible();
    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toHaveCount(0);

    // Back to all.
    await page.getByTestId("dashboard-work-view-all").click();
    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible();
    await expect(page.getByTestId("dashboard-recent-ops")).toBeVisible();
  });
});
