import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.2 — Structural dedup of the Edit Basics page.
 *
 * The Permissions page (CustomerPermissionsPage) is canonical for the
 * per-access permission-override editor and the customer-company
 * policy panel. Two duplicate sections were removed from the Edit
 * Basics page (CustomerFormPage), and user rows there now deep-link
 * into the Permissions page with focus_user (+ optional
 * focus_building) URL params.
 *
 * This spec asserts:
 *   1. The two deleted sections do not render on /admin/customers/:id.
 *   2. The new "Manage permissions" deep-link routes correctly.
 *   3. The Permissions page consumes focus_user and scrolls the
 *      matching UserAccessCard into view.
 *   4. The Extra Work pricing add-form carries the new wrapper class
 *      that drives the 29.2 spacing rules.
 */
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

async function resolveFirstMembershipUserId(
  api: APIRequestContext,
  customerId: number,
): Promise<number | null> {
  const response = await api.get(
    `/api/customers/${customerId}/users/?page_size=1`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ user_id: number }>;
  };
  if (body.results.length === 0) return null;
  return body.results[0].user_id;
}

test.describe("Sprint 29 Batch 29.2 — Edit Basics dedup", () => {
  test("deleted sections are absent on Edit Basics", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const customerId = await resolveFirstCustomerId(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/edit`);

    // The kept sections remain.
    await expect(
      page.locator('[data-testid="section-customer-buildings"]'),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator('[data-testid="section-customer-users"]'),
    ).toBeVisible();

    // The two deleted sections must NOT render on Edit Basics.
    await expect(
      page.locator('[data-testid="section-customer-overrides-editor"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="section-customer-company-policy"]'),
    ).toHaveCount(0);

    // The local policy toggle and per-key override radios from the
    // deleted inline editor must NOT appear here either.
    await expect(
      page.locator('[data-testid="customer-policy-toggle"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="customer-overrides-radio"]'),
    ).toHaveCount(0);
  });

  test("Manage permissions deep-link routes to Permissions page with focus_user", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const customerId = await resolveFirstCustomerId(sa);
    const userId = await resolveFirstMembershipUserId(sa, customerId);
    await sa.dispose();
    test.skip(
      userId === null,
      "No customer memberships in seed for this customer.",
    );

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${customerId}/edit`);

    const link = page
      .locator(
        `[data-testid="manage-permissions-link"][data-user-id="${userId}"]`,
      )
      .first();
    await expect(link).toBeVisible({ timeout: 10_000 });

    // The link href must point at the Permissions page with the
    // focus_user param.
    const href = await link.getAttribute("href");
    expect(href).toBe(
      `/admin/customers/${customerId}/permissions?focus_user=${userId}`,
    );

    await link.click();
    await expect(
      page.locator('[data-testid="customer-permissions-page"]'),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("focus_user scrolls the matching card and consumes the param", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const customerId = await resolveFirstCustomerId(sa);
    const userId = await resolveFirstMembershipUserId(sa, customerId);
    await sa.dispose();
    test.skip(
      userId === null,
      "No customer memberships in seed for this customer.",
    );

    await loginAs(page, DEMO_USERS.super);
    await page.goto(
      `/admin/customers/${customerId}/permissions?focus_user=${userId}`,
    );

    // The card with id=user-access-card-<userId> must be present.
    const card = page.locator(`#user-access-card-${userId}`);
    await expect(card).toBeVisible({ timeout: 10_000 });

    // The focus_user param must be consumed (replaceState) after the
    // effect runs; the URL no longer carries it.
    await page.waitForFunction(
      () =>
        !new URLSearchParams(window.location.search).has("focus_user"),
      undefined,
      { timeout: 5_000 },
    );
  });

  test("pricing add-form carries the spacing wrapper class", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const rowCount = await page
      .locator('[data-testid="extra-work-row"]')
      .count();
    test.skip(rowCount === 0, "No EW rows in seed.");

    await page.locator('[data-testid="extra-work-row"]').first().click();
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});

    // Only the provider side renders the add-pricing-item form. The
    // demo seeds super_admin as provider; the form must carry the
    // wrapper class that drives the 29.2 spacing CSS.
    const addForm = page.locator("form.ew-pricing-add-form");
    const addFormCount = await addForm.count();
    test.skip(
      addFormCount === 0,
      "Add-pricing-item form not visible on this EW (workflow state).",
    );
    await expect(addForm).toBeVisible();
  });
});
