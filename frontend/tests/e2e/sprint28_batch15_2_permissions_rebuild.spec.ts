import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 15.2 — Permissions page rebuild.
 *
 * The Vite dev server does not proxy /api/* — the SPA's axios client
 * talks to VITE_API_BASE_URL directly. Mirror that contract here so
 * this spec works regardless of PLAYWRIGHT_BASE_URL.
 */
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

// RF-8 (#106) — the detailed policy grid + user matrix moved behind the
// collapsed "Geavanceerd" card on the permissions page; open it before
// touching those surfaces (the simple module-bundle cards are primary).
async function openAdvanced(page: Page): Promise<void> {
  await page
    .locator('[data-testid="customer-permissions-advanced-toggle"]')
    .click();
}

async function resolveFirstCustomerId(api: APIRequestContext): Promise<number> {
  const response = await api.get("/api/customers/?page_size=1");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  expect(
    body.results.length,
    "demo seed has at least one customer",
  ).toBeGreaterThan(0);
  return body.results[0].id;
}

test.describe("Sprint 28 Batch 15.2 — Permissions page rebuild", () => {
  test("three zones render with locked testids", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    await expect(
      page.locator('[data-testid="customer-permissions-page"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="section-customer-company-policy"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="section-customer-users"]'),
    ).toBeVisible();
    // The overrides editor is the drawer — not visible until a
    // "Custom permissions" pill is clicked.
    await expect(
      page.locator('[data-testid="section-customer-overrides-editor"]'),
    ).toHaveCount(0);
  });

  test("policy toggles are still real checkboxes with data-policy-field", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    const toggles = page.locator('[data-testid="customer-policy-toggle"]');
    await expect(toggles).toHaveCount(4);
    const fields = await toggles.evaluateAll((els) =>
      els.map((el) =>
        (el as HTMLInputElement).getAttribute("data-policy-field"),
      ),
    );
    expect(fields.sort()).toEqual(
      [
        "customer_users_can_approve_extra_work_pricing",
        "customer_users_can_approve_ticket_completion",
        "customer_users_can_create_extra_work",
        "customer_users_can_create_tickets",
      ].sort(),
    );
  });

  test("sticky save bar appears only when policy is dirty", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    const saveBar = page.locator('[data-testid="customer-policy-save-bar"]');
    await expect(saveBar).toHaveCount(0);

    // Flip a policy toggle and the bar should appear.
    const firstToggle = page
      .locator('[data-testid="customer-policy-toggle"]')
      .first();
    await firstToggle.click();
    await expect(saveBar).toBeVisible();

    // Cancel reverts the draft and unmounts the bar.
    await saveBar
      .getByRole("button", { name: /cancel|annuleren/i })
      .click();
    await expect(saveBar).toHaveCount(0);
  });

  test("Edit permissions button opens modal with 16 override rows", async ({
    page,
  }) => {
    // Sprint 31 Phase 6 — the per-user inline AccessPermissionsPanel
    // is gone. The pill (now an "Edit permissions" button on each
    // matrix row) opens the modal directly. The pill's locked testid
    // `customer-access-overrides-button` is preserved on the matrix
    // row's Edit button so this spec's first locator still resolves.
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    const firstOverridesButton = page
      .locator('[data-testid="customer-access-overrides-button"]')
      .first();
    await expect(firstOverridesButton).toBeVisible({ timeout: 10_000 });
    await firstOverridesButton.click();

    // Modal opens directly; no intermediate panel.
    await expect(
      page.locator('[data-testid="section-customer-overrides-editor"]'),
    ).toBeVisible();

    // 16 customer permission keys -> 16 rows.
    const rows = page.locator('[data-testid="customer-overrides-row"]');
    await expect(rows).toHaveCount(16);

    // Close via the close button.
    await page.locator('[data-testid="customer-overrides-close"]').click();
    await expect(
      page.locator('[data-testid="section-customer-overrides-editor"]'),
    ).toHaveCount(0);
  });

  test("override radio selection persists in draft until saved", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    // Sprint 31 Phase 6 — pill click opens the modal directly.
    await page
      .locator('[data-testid="customer-access-overrides-button"]')
      .first()
      .click();

    const firstRow = page
      .locator('[data-testid="customer-overrides-row"]')
      .first();
    const allowRadio = firstRow.locator(
      '[data-testid="customer-overrides-radio"][value="allow"]',
    );
    await allowRadio.check();
    await expect(allowRadio).toBeChecked();

    await expect(
      page.locator('[data-testid="customer-overrides-save"]'),
    ).toBeVisible();
  });

  test("no raw permission keys appear as labels in the modal", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const id = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${id}/permissions`);
    await openAdvanced(page);

    // Sprint 31 Phase 6 — pill click opens the modal directly.
    await page
      .locator('[data-testid="customer-access-overrides-button"]')
      .first()
      .click();

    // The modal's label cells (.permission-editor-modal-row-label,
    // replacing the legacy .override-row-label) must not show the raw
    // `customer.ticket.*` enum strings — they should be the
    // translated labels.
    const labelTexts = await page
      .locator(".permission-editor-modal-row-label")
      .allTextContents();
    expect(labelTexts.length).toBe(16);
    for (const txt of labelTexts) {
      expect(
        txt,
        "modal label should not contain raw permission key",
      ).not.toContain("customer.ticket.");
      expect(
        txt,
        "modal label should not contain raw permission key",
      ).not.toContain("customer.extra_work.");
      expect(
        txt,
        "modal label should not contain raw permission key",
      ).not.toContain("customer.users.");
    }
  });
});
