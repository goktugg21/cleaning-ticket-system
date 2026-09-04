import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 15.3 — Extra Work list + Users page grouping + Audit
 * log readable diff.
 *
 * P-10 C3 — the Extra Work half is rewritten against the list as it is.
 * The FE-1 status tiles and the list total this spec used to read
 * (`extra-work-status-tile-*`, `extra-work-list-total`) went with P-8R;
 * the list is P-9's four tabs (`/extra-work/:tab`, each
 * `extra-work-tab-<tab>[data-count]`) over the guard line
 * `extra-work-list-loaded-count[data-count]`. The tab arithmetic itself
 * (four counts + cancelled = the server's count) is
 * `p9_extra_work_tabs.spec.ts`'s; this file keeps what that spec does
 * not assert: the money line is money, no raw status enum leaks, and the
 * Approved tab opens on "Not planned yet" (P-10 B1).
 */
const TABS = ["to-price", "with-customer", "approved", "finished"] as const;

test.describe("Sprint 28 Batch 15.3 — Extra Work list", () => {
  test("the list opens on a tab, every tab carries a count, the guard line is loaded", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await expect(page).toHaveURL(
      /\/extra-work\/(to-price|with-customer|approved|finished)/,
    );
    await expect(page.getByTestId("extra-work-list-page")).toBeVisible();
    const loaded = page.getByTestId("extra-work-list-loaded-count");
    await expect(loaded).toBeVisible();
    expect(Number(await loaded.getAttribute("data-count"))).not.toBeNaN();
    for (const tab of TABS) {
      const tabButton = page.getByTestId(`extra-work-tab-${tab}`);
      await expect(tabButton).toBeVisible();
      expect(Number(await tabButton.getAttribute("data-count"))).not.toBeNaN();
    }
  });

  test("money is formatted with a currency symbol", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    // P-11 F1 — per P-9's tabs (§D.22 pt 4) each tab has ONE line and
    // To price's is deliberately a COUNT sentence, not money. The €
    // pin belongs on a tab whose line IS money: Approved.
    await page.goto("/extra-work/approved");
    // Wait for at least one row or the empty state to render.
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    test.skip(
      (await page.getByTestId("extra-work-row").count()) === 0,
      "the Approved tab has no rows, so it draws no money line",
    );
    const money = page.getByTestId("extra-work-tab-money");
    await expect(money).toBeVisible({ timeout: 10_000 });
    expect(
      (await money.textContent()) ?? "",
      "the tab's money line should be a formatted money string",
    ).toMatch(/€\s?\d/);
  });

  test("status uses StatusBadge — no raw enum word visible", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    for (const tab of TABS) {
      await page.goto(`/extra-work/${tab}`);
      await page.waitForSelector(
        '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
        { timeout: 10_000 },
      );
      const body =
        (await page
          .locator('[data-testid="extra-work-list-page"]')
          .textContent()) ?? "";
      // The raw enum strings must not surface in row cells (a <select>'s
      // option values are not part of the rendered text).
      for (const raw of [
        "PRICING_PROPOSED",
        "CUSTOMER_APPROVED",
        "WAITING_PLANNING",
        "IN_EXECUTION",
      ]) {
        expect(body, `raw status enum ${raw} should not leak on ${tab}`).not.toMatch(
          new RegExp(`\\b${raw}\\b`),
        );
      }
    }
  });

  test("the Approved tab opens on Not planned yet", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work/approved");
    await expect(page.getByTestId("extra-work-tab-approved")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // P-11 F1 — the chip key has been `not_planned` since P-10 B1/B2
    // (the ticket's own words); this line was the rewrite's one miss.
    await expect(page.getByTestId("extra-work-chip-not_planned")).toHaveAttribute(
      "aria-selected",
      "true",
    );
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
