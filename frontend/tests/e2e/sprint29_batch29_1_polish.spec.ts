import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.1 — polish and papercut fixes.
 *
 * Covers:
 *   1. Scope chip on /admin/users pluralizes correctly
 *      (no more "1 customers").
 *   2. Extra Work pricing totals row has a "Total" label cell.
 *   3. Show-technical-keys toggle on the Permissions page hides
 *      the affects-line by default and reveals it when checked.
 *   4. Settings page collapses to a single column at typical
 *      laptop widths (1280px breakpoint).
 */
test.describe("Sprint 29 Batch 29.1 — polish & papercuts", () => {
  test("scope chip pluralizes count correctly", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/users");
    await page.waitForSelector('[data-testid="users-scope-chip"]', {
      timeout: 10_000,
    });
    const chips = await page
      .locator('[data-testid="users-scope-chip"]')
      .allTextContents();
    test.skip(chips.length === 0, "No scope chips visible in seed.");
    for (const chip of chips) {
      const trimmed = chip.trim();
      expect(
        trimmed,
        `Bad pluralization: "${trimmed}"`,
      ).not.toMatch(/^1 (customers|buildings|companies)$/);
      expect(trimmed).toMatch(
        /^(\d+ (customer|building|company)s?|All companies)$/,
      );
    }
  });

  test("pricing totals row renders a Total label", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const rowCount = await page.locator('[data-testid="extra-work-row"]').count();
    test.skip(rowCount === 0, "No EW rows in seed.");
    await page.locator('[data-testid="extra-work-row"]').first().click();
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
    const totalsRow = page.locator(".ew-pricing-totals-row");
    const totalsCount = await totalsRow.count();
    test.skip(totalsCount === 0, "No pricing totals row on this EW.");
    await expect(totalsRow.locator("text=Total")).toBeVisible();
  });

  test("show technical keys toggle controls affects-line visibility", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/customers");
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
    const firstCustomerLink = page
      .locator('a[href^="/admin/customers/"]')
      .filter({ hasNot: page.locator("text=/new/i") })
      .first();
    if ((await firstCustomerLink.count()) === 0)
      test.skip(true, "No customers in seed.");
    await firstCustomerLink.click();
    await page.goto(page.url() + "/permissions");
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});

    // RF-8 (#106) — the technical-keys toggle + policy grid moved
    // behind the collapsed "Geavanceerd" card; open it first.
    await page
      .locator('[data-testid="customer-permissions-advanced-toggle"]')
      .click();

    const toggle = page.locator('[data-testid="show-technical-keys-toggle"]');
    await expect(toggle).toBeVisible();

    // Reset to OFF to make the test deterministic regardless of
    // any persisted localStorage state from earlier runs.
    const checkbox = toggle.locator('input[type="checkbox"]');
    if (await checkbox.isChecked()) {
      await checkbox.uncheck();
    }
    await expect(page.locator(".policy-toggle-card-affects")).toHaveCount(0);

    await checkbox.check();
    await expect(
      page.locator(".policy-toggle-card-affects").first(),
    ).toBeVisible();
    const firstAffects = await page
      .locator(".policy-toggle-card-affects")
      .first()
      .textContent();
    expect(firstAffects).toMatch(/customer\.(ticket|extra_work)\./);

    await checkbox.uncheck();
    await expect(page.locator(".policy-toggle-card-affects")).toHaveCount(0);
  });

  test("settings page collapses to single column at typical laptop width", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto("/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
    const layout = page.locator(".settings-layout");
    await expect(layout).toBeVisible();
    const computedColumns = await layout.evaluate(
      (el) => window.getComputedStyle(el).gridTemplateColumns,
    );
    const trackCount = computedColumns
      .split(" ")
      .filter((s) => s.trim() !== "").length;
    expect(
      trackCount,
      `Expected single-column at 1100px, got: ${computedColumns}`,
    ).toBe(1);
  });
});
