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

/**
 * The permissions matrix has one row per (user, building) access row,
 * so the spec targets the seeded "B Amsterdam" (whose members hold
 * per-building access) rather than whichever customer sorts first —
 * a customer with company-wide admins only renders an empty matrix
 * and no "Edit permissions" button.
 */
async function resolveFirstCustomerId(api: APIRequestContext): Promise<number> {
  const response = await api.get("/api/customers/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match =
    body.results.find((c) => c.name === "B Amsterdam") ?? body.results[0];
  expect(match, "demo seed has at least one customer").toBeTruthy();
  return match.id;
}

/** The four Sprint 15.2 policy booleans; Sprint 126 added documents. */
const POLICY_FIELDS_LOCKED = [
  "customer_users_can_approve_extra_work_pricing",
  "customer_users_can_approve_ticket_completion",
  "customer_users_can_create_extra_work",
  "customer_users_can_create_tickets",
];

/** FE-6 — 17 customer permission keys (`CUSTOMER_PERMISSION_KEYS`). */
const CUSTOMER_PERMISSION_KEY_COUNT = 17;

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
    await expect(toggles.first()).toBeAttached({ timeout: 10_000 });
    expect(await toggles.count()).toBeGreaterThanOrEqual(POLICY_FIELDS_LOCKED.length);
    const fields = await toggles.evaluateAll((els) =>
      els.map((el) =>
        (el as HTMLInputElement).getAttribute("data-policy-field"),
      ),
    );
    for (const field of POLICY_FIELDS_LOCKED) {
      expect(fields).toContain(field);
    }
    // Every toggle is a real checkbox carrying its policy field.
    expect(fields.every((f) => !!f && f.startsWith("customer_users_can_"))).toBe(true);
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

    // Flip a policy toggle and the bar should appear. The testid sits on
    // the switch's hidden checkbox; click its `.toggle-switch` label.
    const firstToggle = page
      .locator('[data-testid="customer-policy-toggle"]')
      .first();
    await expect(firstToggle).toBeAttached({ timeout: 10_000 });
    await firstToggle.locator("xpath=..").click();
    await expect(saveBar).toBeVisible();

    // Cancel reverts the draft and unmounts the bar.
    await saveBar
      .getByRole("button", { name: /cancel|annuleren/i })
      .click();
    await expect(saveBar).toHaveCount(0);
  });

  test("Edit permissions button opens modal with one override row per permission key", async ({
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

    // One row per customer permission key.
    const rows = page.locator('[data-testid="customer-overrides-row"]');
    await expect(rows).toHaveCount(CUSTOMER_PERMISSION_KEY_COUNT);

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
    // P-16 repin (harness mechanics, not the app): the radio is
    // `.visually-hidden` behind its optical bubble, so `.check()` on
    // the input is intercepted by the bubble span. A person clicks the
    // LABEL — so does the spec.
    await allowRadio.locator("xpath=ancestor::label[1]").click();
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
    await expect(
      page.locator(".permission-editor-modal-row-label").first(),
    ).toBeVisible({ timeout: 10_000 });
    const labelTexts = await page
      .locator(".permission-editor-modal-row-label")
      .allTextContents();
    expect(labelTexts.length).toBe(CUSTOMER_PERMISSION_KEY_COUNT);
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
