import { expect, test } from "@playwright/test";
import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/** P-16 — seed a PRICED, unspawned EW so the totals-row test stops
 *  gambling on the list's first row (it self-skipped whenever that row
 *  happened to carry no pricing). Tom creates a proposal-routed cart;
 *  the SA drives it to PRICING_PROPOSED (the W-PLAN gate's recorded-
 *  override bypass) and prices one line. Returns the EW id, or null. */
async function seedPricedEw(): Promise<number | null> {
  const sa = await apiAs(DEMO_USERS.super.email);
  const tom = await apiAs(DEMO_USERS.customerAll.email);
  try {
    const tomEws = (await (
      await tom.get("/api/extra-work/?page_size=1")
    ).json()) as { results: Array<{ customer: number; building: number }> };
    const anchor = tomEws.results[0];
    if (!anchor) return null;
    const create = await tom.post("/api/extra-work/", {
      data: {
        title: `29.1 totals fixture ${Date.now()}`,
        description: "Seeded by the pricing-totals spec.",
        building: anchor.building,
        customer: anchor.customer,
        category: "DEEP_CLEANING",
        line_items: [{ custom_description: "Priced line", quantity: "1.00" }],
      },
    });
    if (create.status() !== 201) return null;
    const body = (await create.json()) as { id: number };
    const r1 = await sa.post(`/api/extra-work/${body.id}/transition/`, {
      data: { to_status: "UNDER_REVIEW" },
    });
    if (r1.status() !== 200) return null;
    // The totals row renders inside the ProposalBuilder, which mounts
    // on a DRAFT proposal — so the seed builds one (the W-PLAN gate's
    // recorded-override bypass) and prices one line on it.
    const proposal = await sa.post(`/api/extra-work/${body.id}/proposals/`, {
      data: { override_reason: "29.1 fixture: plan bypass" },
    });
    if (proposal.status() !== 201) return null;
    const pid = ((await proposal.json()) as { id: number }).id;
    const line = await sa.post(
      `/api/extra-work/${body.id}/proposals/${pid}/lines/`,
      {
        data: {
          description: "29.1 totals line",
          unit_type: "FIXED",
          quantity: "1.00",
          unit_price: "100.00",
          vat_pct: "21.00",
        },
      },
    );
    if (line.status() !== 201) return null;
    return body.id;
  } finally {
    await sa.dispose();
    await tom.dispose();
  }
}

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
    await page.goto("/admin/people/users");
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
    // P-16 repin — the spec seeds its own priced EW instead of
    // clicking the list's first row and skipping when it carried no
    // pricing.
    const ewId = await seedPricedEw();
    test.skip(ewId === null, "Could not seed a priced EW.");

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${ewId}`);
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
    // FE-3 — the pricing table lives on the request's Money tab.
    await expect(page.locator('[data-testid="extra-work-detail-page"]')).toBeVisible({
      timeout: 10_000,
    });
    await page.locator('[data-testid="extra-work-tab-money"]').click();
    // The seeded EW carries a priced line, so the totals row is a
    // hard expectation now, not a maybe.
    const totalsRow = page.locator(".ew-pricing-totals-row");
    await expect(totalsRow.first()).toBeVisible({ timeout: 10_000 });
    await expect(totalsRow.locator("text=Total").first()).toBeVisible();
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

    // The switch's checkbox input is visually hidden; its `.toggle-switch`
    // label is the click target. Reset to OFF to make the test
    // deterministic regardless of any persisted localStorage state.
    const checkbox = toggle.locator('input[type="checkbox"]');
    const switchLabel = checkbox.locator("xpath=..");
    if (await checkbox.isChecked()) {
      await switchLabel.click();
    }
    await expect(page.locator(".policy-toggle-card-affects")).toHaveCount(0);

    await switchLabel.click();
    expect(await checkbox.isChecked()).toBe(true);
    await expect(
      page.locator(".policy-toggle-card-affects").first(),
    ).toBeVisible();
    const firstAffects = await page
      .locator(".policy-toggle-card-affects")
      .first()
      .textContent();
    expect(firstAffects).toMatch(/customer\.(ticket|extra_work)\./);

    await switchLabel.click();
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
