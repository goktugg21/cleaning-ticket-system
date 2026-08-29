import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 15.3 — Extra Work list rebuild + Users page
 * grouping + Audit log readable diff.
 *
 * FE-1 / W24 — the four-card KPI strip above the Meerwerk list is
 * gone; the list opens with the status TILES (one per quote-track
 * chip plus "all", `extra-work-status-tile-*`) and the list total
 * (`extra-work-list-total`) is the one money figure. Users live on
 * the People page (`/admin/people/users`).
 */

test.describe("Sprint 28 Batch 15.3 — Extra Work list rebuild", () => {
  test("status tiles render above the list", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await expect(
      page.locator('[data-testid="extra-work-list-page"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="extra-work-status-tiles"]'),
    ).toBeVisible();
    for (const id of [
      "extra-work-status-tile-all",
      "extra-work-status-tile-AWAITING_PRICING",
      "extra-work-status-tile-PRICING_PROPOSED",
      "extra-work-status-tile-CUSTOMER_APPROVED",
    ]) {
      await expect(page.locator(`[data-testid="${id}"]`)).toBeVisible();
    }
  });

  test("money is formatted with currency symbol", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    // Wait for at least one row or the empty state to render.
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const total = page.locator('[data-testid="extra-work-list-total"]');
    await expect(total).toBeVisible({ timeout: 10_000 });
    const valueText = (await total.locator("strong").textContent()) ?? "";
    // Either "—" (no rows, formatMoney returns the dash for empty)
    // or contains the euro sign + a digit.
    expect(
      valueText.trim(),
      "list total should be a formatted money string",
    ).toMatch(/^(—|.*€.*\d.*)$/);
  });

  test("status uses StatusBadge — no raw enum word visible", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const body =
      (await page
        .locator('[data-testid="extra-work-list-page"]')
        .textContent()) ?? "";
    // The raw enum strings should not surface in row cells (they
    // can still appear inside <select> option values, which are
    // not part of the text content of the page when rendered).
    expect(body, "raw status enum should not leak").not.toMatch(
      /\bPRICING_PROPOSED\b/,
    );
    expect(body, "raw status enum should not leak").not.toMatch(
      /\bCUSTOMER_APPROVED\b/,
    );
  });

  test("filtering by status narrows the visible rows", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    // Sprint 181 §2 — the status <select> in the filter bar is gone;
    // the status tiles above the list ARE the status filter.
    await page.locator('[data-testid="extra-work-status-tile-CANCELLED"]').click();
    await page.waitForLoadState("networkidle");
    // Either zero rows + filtered empty state, or every visible row
    // shows the localised "cancelled" label inside its status badge.
    const rows = page.locator('[data-testid="extra-work-row"]');
    const count = await rows.count();
    if (count === 0) {
      await expect(
        page.locator('[data-testid="extra-work-list-empty"]'),
      ).toBeVisible();
    } else {
      // Sprint 28 Batch 15.4 — each row now carries a StatusBadge AND
      // a RouteBadge (both styled with `.badge`). The RouteBadge has
      // the `.route-badge` modifier class, so filter to the status
      // badge by excluding it.
      const statuses = await rows
        .locator(".badge:not(.route-badge)")
        .allTextContents();
      for (const s of statuses) {
        expect(s.toLowerCase()).toMatch(/cancel|geannuleerd/);
      }
    }
  });
});

test.describe("Sprint 28 Batch 15.3 — Users grouping", () => {
  test("provider and customer groups render as separate sections", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/people/users");
    // The demo seed has both provider and customer users (super-admin
    // sees all five roles). Both group headers should resolve.
    await expect(
      page.locator('[data-testid="users-group-provider"]'),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator('[data-testid="users-group-customer"]'),
    ).toBeVisible();
  });

  test("role cells use RoleBadge with side classifier", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/people/users");
    // RoleBadge renders a .role-badge wrapper with either
    // .role-badge-provider or .role-badge-customer modifier.
    const providerBadges = page.locator(".role-badge-provider");
    const customerBadges = page.locator(".role-badge-customer");
    await expect(providerBadges.first()).toBeVisible({ timeout: 15_000 });
    expect(await providerBadges.count()).toBeGreaterThan(0);
    expect(await customerBadges.count()).toBeGreaterThan(0);
  });
});

test.describe("Sprint 28 Batch 15.3 — Audit log readable diff", () => {
  test("audit log changes render as ChangeDiff (no raw JSON visible)", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/audit-logs");
    await expect(
      page.locator('[data-testid="audit-logs-page"]'),
    ).toBeVisible();
    // Expand at least one row's diff if there are rows.
    const summaries = page.locator(
      '[data-testid="audit-row-changes-summary"]',
    );
    const summaryCount = await summaries.count();
    if (summaryCount > 0) {
      await summaries.first().click();
      // ChangeDiff renders a .change-diff wrapper.
      await expect(page.locator(".change-diff").first()).toBeVisible();
      const pageBody =
        (await page
          .locator('[data-testid="audit-logs-page"]')
          .textContent()) ?? "";
      // We never expect to see the exact ugly raw-JSON shape
      // `{"before":` anywhere on the page after the rebuild.
      expect(pageBody).not.toMatch(/\{"before":/);
    }
  });
});
