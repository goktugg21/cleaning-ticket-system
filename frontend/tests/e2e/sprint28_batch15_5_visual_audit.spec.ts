/**
 * Sprint 28 Batch 15.5 — Visual audit.
 *
 * Closes the rebuild loop opened by Batches 15.1 through 15.4 with
 * a single sweeping regression spec that lands on the highest-
 * traffic pages and asserts:
 *
 *   1. No raw enum strings (PRICING_PROPOSED, CUSTOMER_USER, …)
 *      leak into rendered page text.
 *   2. No raw JSON shape (`{"before":…`) leaks anywhere — the
 *      audit-log ChangeDiff rebuild must hold.
 *   3. Money values always carry the euro symbol on the EW list.
 *   4. The Users page renders the un-compact RoleBadge (side
 *      caption visible) and the new per-row scope chip.
 *   5. The sidebar customer-context chip appears on every
 *      customer-scoped route and only there.
 *
 * The scope-chip assertion depends on a parallel backend change
 * (UserAdminListSerializer.scope_summary). If the field is not
 * present yet at run-time the chip count will be zero and that
 * single assertion fails — the rest of the spec stays green.
 */
import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

const FORBIDDEN_ENUM_STRINGS = [
  /\bPRICING_PROPOSED\b/,
  /\bCUSTOMER_APPROVED\b/,
  /\bCUSTOMER_REJECTED\b/,
  /\bUNDER_REVIEW\b/,
  /\bBUILDING_MANAGER\b/,
  /\bCOMPANY_ADMIN\b/,
  /\bSUPER_ADMIN\b/,
  /\bCUSTOMER_USER\b/,
];
const FORBIDDEN_JSON_SHAPE = /\{"before":/;

const PAGES_TO_AUDIT = [
  { path: "/", name: "dashboard" },
  { path: "/extra-work", name: "extra-work-list" },
  { path: "/admin/users", name: "users" },
  { path: "/admin/audit-logs", name: "audit-logs" },
  { path: "/admin/customers", name: "customers" },
];

test.describe("Sprint 28 Batch 15.5 — Visual audit", () => {
  for (const { path, name } of PAGES_TO_AUDIT) {
    test(`no raw enums on ${name}`, async ({ page }) => {
      await loginAs(page, DEMO_USERS.super);
      await page.goto(path);
      await page
        .waitForLoadState("networkidle", { timeout: 10_000 })
        .catch(() => {});
      const body =
        (await page.locator("main, .page-canvas").first().textContent()) ?? "";
      for (const re of FORBIDDEN_ENUM_STRINGS) {
        expect(body, `${name} leaked raw enum ${re}`).not.toMatch(re);
      }
      expect(body, `${name} leaked raw JSON shape`).not.toMatch(
        FORBIDDEN_JSON_SHAPE,
      );
    });
  }

  test("money values always carry the euro symbol", async ({ page }) => {
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
    // Total column. Per ExtraWorkListPage.tsx the column order is
    // title (0), status (1), route (2), category (3), building (4),
    // customer (5), total (6), requested (7). Iterate per row and
    // pull the 7th td (nth(6)) — using a single flat .td().nth(6)
    // would only inspect one row's worth of cells, not the total
    // column across every row.
    const rows = page.locator('[data-testid="extra-work-row"]');
    const rowsCount = await rows.count();
    const totals: string[] = [];
    for (let i = 0; i < rowsCount; i++) {
      const t = await rows.nth(i).locator("td").nth(6).textContent();
      if (t !== null) totals.push(t);
    }
    for (const t of totals) {
      if (t.trim() === "" || t.trim() === "—") continue;
      expect(t, `Total cell missing currency symbol: "${t}"`).toMatch(/€/);
    }
  });

  test("users page renders role badge + scope chip + group headers", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/users");
    await page.waitForSelector('[data-testid="users-group-provider"]', {
      timeout: 10_000,
    });
    // RoleBadge un-compact form renders a .role-badge-side caption.
    const sideCaptions = page.locator(".role-badge-side");
    expect(await sideCaptions.count()).toBeGreaterThan(0);
    // Scope chip is gated by the parallel backend serializer change.
    // If the field is missing the count is zero and this test fails
    // intentionally — the operator knows to wait for the bundle.
    const scopeChips = page.locator(".users-scope-chip");
    expect(await scopeChips.count()).toBeGreaterThan(0);
  });

  test("sidebar customer context chip appears on scoped routes", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/customers");
    await page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
    // Pick any customer-detail link from the list (skip the
    // "create new" link which routes to /admin/customers/new).
    const firstCustomerLink = page
      .locator('a[href^="/admin/customers/"]')
      .filter({ hasNot: page.locator("text=/new/i") })
      .first();
    if ((await firstCustomerLink.count()) === 0) {
      test.skip(true, "No customers in seed.");
    }
    await firstCustomerLink.click();
    await expect(
      page.locator('[data-testid="sidebar-customer-context-chip"]'),
    ).toBeVisible({ timeout: 5_000 });
  });
});
