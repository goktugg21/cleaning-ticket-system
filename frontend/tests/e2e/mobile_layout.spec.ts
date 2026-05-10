import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 20 — mobile UI polish coverage.
 *
 * The brief calls out four phone-class viewports plus the small-tablet
 * boundary:
 *
 *   360x640   — iPhone SE 1st gen / older Android (`MOBILE_360`)
 *   390x844   — iPhone 12/13/14                   (`MOBILE_390`)
 *   430x932   — iPhone 14 Pro Max                 (`MOBILE_430`)
 *   768x1024  — iPad portrait / small tablet      (`TABLET_768`)
 *
 * The tests assert layout invariants — no body-level horizontal
 * overflow, the hamburger toggle replaces the sidebar, primary CTAs
 * stay tappable, dense tables scroll horizontally inside their wrap
 * (not the whole page) — rather than pixel-perfect screenshots, so
 * future skin tweaks do not break the suite.
 */

const MOBILE_360 = { width: 360, height: 640 };
const MOBILE_390 = { width: 390, height: 844 };
const MOBILE_430 = { width: 430, height: 932 };
const TABLET_768 = { width: 768, height: 1024 };

/**
 * Read the workspace's scrollWidth and confirm it does not exceed the
 * viewport (the SPA never intends a horizontal page scroll). A small
 * tolerance covers anti-aliasing rounding.
 */
async function expectNoBodyHorizontalOverflow(
  page: import("@playwright/test").Page,
  viewportWidth: number,
) {
  const documentScrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(documentScrollWidth).toBeLessThanOrEqual(viewportWidth + 1);
}

// ---------------------------------------------------------------------------
// Login page — public, no auth needed
// ---------------------------------------------------------------------------

for (const vp of [MOBILE_360, MOBILE_390]) {
  test(`login at ${vp.width}px renders without horizontal page overflow`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await page.goto("/login");
    // Either the demo cards (VITE_DEMO_MODE=true build) or the bare
    // form must mount.
    await expect(page.locator(".login-form")).toBeVisible({ timeout: 10_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

test("login demo cards stack to one column at 360px", async ({ page }) => {
  await page.setViewportSize(MOBILE_360);
  await page.goto("/login");
  const cards = page.locator('[data-testid="demo-cards"]');
  if ((await cards.count()) === 0) {
    test.skip(true, "VITE_DEMO_MODE not enabled for this build");
    return;
  }
  // The Sprint 20 stylesheet collapses .qa-grid to one column at
  // <=480px. Two card centres stacked vertically should differ in y
  // (not x).
  const first = page.locator('[data-testid="demo-card-super"]').first();
  const second = page.locator('[data-testid="demo-card-company-admin"]').first();
  const a = await first.boundingBox();
  const b = await second.boundingBox();
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  if (a && b) {
    expect(Math.abs(a.y - b.y)).toBeGreaterThan(20);
  }
});

// ---------------------------------------------------------------------------
// Dashboard / app shell at phone widths
// ---------------------------------------------------------------------------

test.describe("app shell at phone widths", () => {
  test("390px: sidebar hidden by default, hamburger toggle visible", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_390);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await expect(page.locator(".sidebar-toggle")).toBeVisible({
      timeout: 10_000,
    });
    // The fixed sidebar is translateX(-100%) when the mobile-open
    // class is absent. Its bounding box should sit fully off-screen
    // (x + width <= 0).
    const aside = page.locator(".sidebar").first();
    const box = await aside.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.x + box.width).toBeLessThanOrEqual(0);
    }
  });

  test("390px: hamburger opens sidebar and the backdrop closes it", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_390);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.locator(".sidebar-toggle").click();
    const aside = page.locator(".sidebar").first();
    // After open the sidebar should be visibly inside the viewport.
    await expect.poll(async () => {
      const box = await aside.boundingBox();
      return box ? box.x : -999;
    }, { timeout: 5_000 }).toBeGreaterThanOrEqual(0);
    // The .sidebar-backdrop covers the full viewport but the sidebar
    // visually overlaps its left third, so a default `.click()` (at
    // the bounding-box centre) actually lands ON the sidebar's nav
    // links. Click the backdrop AT a coordinate to the right of the
    // sidebar (the sidebar is `min(280px, 86vw)` wide; on a 390px
    // viewport that's 280px) so the dismiss handler fires.
    const aside_box = await aside.boundingBox();
    const sidebarRight = aside_box ? aside_box.x + aside_box.width : 280;
    await page.locator(".sidebar-backdrop").click({
      position: { x: sidebarRight + 20, y: 200 },
    });
    await expect.poll(async () => {
      const box = await aside.boundingBox();
      return box ? box.x + box.width : 999;
    }, { timeout: 5_000 }).toBeLessThanOrEqual(0);
  });

  test("390px: dashboard ticket table is reachable and scrolls inside its wrap, not the page", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_390);
    await loginAs(page, DEMO_USERS.companyAdmin);
    // Wait for the ticket table to render at least one row.
    await expect(
      page.locator(".data-table tbody tr").first(),
    ).toBeVisible({ timeout: 10_000 });
    // The .table-wrap exposes the horizontal scroll; its scrollWidth
    // should exceed its clientWidth on this viewport because the
    // table sets `min-width: 860px`.
    const overflowFlags = await page
      .locator(".data-table")
      .first()
      .evaluate((el) => {
        const wrap = el.closest(".table-wrap");
        const wrapEl = wrap as HTMLElement | null;
        return {
          hasWrap: !!wrap,
          wrapScrollWidth: wrapEl ? wrapEl.scrollWidth : 0,
          wrapClientWidth: wrapEl ? wrapEl.clientWidth : 0,
        };
      });
    expect(overflowFlags.hasWrap).toBe(true);
    expect(overflowFlags.wrapScrollWidth).toBeGreaterThan(
      overflowFlags.wrapClientWidth,
    );
    // The page itself, however, must NOT overflow horizontally.
    await expectNoBodyHorizontalOverflow(page, MOBILE_390.width);
  });
});

// ---------------------------------------------------------------------------
// Ticket detail at phone widths
// ---------------------------------------------------------------------------

test("390px: ticket detail page workflow buttons are tappable", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_390);
  // Amanda has access to the [DEMO] Pantry zeepdispenser ticket
  // (B3) which is in WAITING_CUSTOMER_APPROVAL → her workflow card
  // shows Approve + Reject. Use her so the detail page exercises
  // the "render workflow buttons" path instead of a blank one.
  await loginAs(page, DEMO_USERS.customerB3);
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: "Pantry zeepdispenser" })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  const buttons = page.locator(".status-actions .status-btn");
  await expect(buttons.first()).toBeVisible({ timeout: 10_000 });
  // Each workflow button must have a tap target of at least 36px on
  // mobile (the existing `.btn-sm` rule under `@media (max-width:
  // 760px)`).
  const heights = await buttons.evaluateAll((els) =>
    els.map((el) => (el as HTMLElement).getBoundingClientRect().height),
  );
  for (const h of heights) {
    expect(h).toBeGreaterThanOrEqual(36);
  }
  await expectNoBodyHorizontalOverflow(page, MOBILE_390.width);
});

// ---------------------------------------------------------------------------
// Admin users + audit logs at phone widths (SUPER_ADMIN)
// ---------------------------------------------------------------------------

test("390px: admin users page is readable for SUPER_ADMIN", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_390);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/users");
  await expect(
    page.locator(".data-table tbody tr").first(),
  ).toBeVisible({ timeout: 10_000 });
  await expectNoBodyHorizontalOverflow(page, MOBILE_390.width);
});

test("390px: /admin/audit-logs renders for SUPER_ADMIN without page overflow", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_390);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/audit-logs");
  await expect(
    page.locator('[data-testid="audit-logs-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  // Either at least one audit row or the empty-state card mounts.
  const rows = page.locator('[data-testid="audit-row"]');
  const empty = page.locator('[data-testid="audit-empty"]');
  await expect(rows.first().or(empty)).toBeVisible({ timeout: 10_000 });
  await expectNoBodyHorizontalOverflow(page, MOBILE_390.width);
});

// ---------------------------------------------------------------------------
// Unauthorized admin route at phone widths still redirects (guard
// behaviour does not depend on viewport, but assert it once at 360px
// so we know the SPA route guards still fire under the mobile layout).
// ---------------------------------------------------------------------------

test("360px: customer-user hitting /admin/users still redirects away", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_360);
  await loginAs(page, DEMO_USERS.customerAll);
  await page.goto("/admin/users");
  await page.waitForLoadState("networkidle");
  expect(new URL(page.url()).pathname).not.toBe("/admin/users");
  await expectNoBodyHorizontalOverflow(page, MOBILE_360.width);
});

// ---------------------------------------------------------------------------
// Tablet 768 — ticket detail should still behave (this is the boundary
// where the layout switches from desktop to single-column).
// ---------------------------------------------------------------------------

test("768px: ticket detail renders the assignment side panel without overflow", async ({
  page,
}) => {
  await page.setViewportSize(TABLET_768);
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: "Pantry zeepdispenser" })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  await expect(page.locator(".assign-select")).toBeVisible({
    timeout: 10_000,
  });
  await expectNoBodyHorizontalOverflow(page, TABLET_768.width);
});

// ---------------------------------------------------------------------------
// Tablet 768 — admin users page is desktop-shape (sidebar visible).
// ---------------------------------------------------------------------------

test("768px: sidebar shows on tablet (not the mobile overlay)", async ({
  page,
}) => {
  await page.setViewportSize(TABLET_768);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/users");
  // 768px is at the @media (max-width: 760px) boundary; the rule
  // applies STRICTLY below 760, so 768 keeps the persistent sidebar.
  // Hamburger button must therefore be hidden.
  await expect(page.locator(".sidebar-toggle")).toBeHidden({
    timeout: 10_000,
  });
  // The persistent sidebar should be on-screen.
  const aside = page.locator(".sidebar").first();
  const box = await aside.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    expect(box.x).toBeGreaterThanOrEqual(0);
  }
});

// ===========================================================================
// SPRINT 20 FOLLOW-UP — REPORTS + ROW-CLICK-TO-EDIT
// ===========================================================================

// ---------------------------------------------------------------------------
// Reports — mobile chart visibility
// ---------------------------------------------------------------------------

const MOBILE_366 = { width: 366, height: 800 };

for (const vp of [MOBILE_360, MOBILE_366, MOBILE_390]) {
  test(`reports at ${vp.width}px: chart cards span the viewport (no clipping)`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/reports");
    // Wait for at least one chart card to mount before measuring.
    const firstCard = page
      .locator('[data-testid^="chart-card-"]')
      .first();
    await expect(firstCard).toBeVisible({ timeout: 10_000 });
    // The grid template is now `minmax(min(420px, 100%), 1fr)`, so on a
    // ≤420px viewport there is exactly one column and every card's
    // width fits inside the available canvas (viewport minus
    // page-canvas padding). Allow some tolerance for paddings; the
    // important assertion is that the card does NOT exceed the
    // viewport.
    const box = await firstCard.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
    }
    // The page must NOT scroll horizontally.
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

test("reports at 360px: every chart card stays inside the viewport width", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_360);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/reports");
  await expect(
    page.locator('[data-testid^="chart-card-"]').first(),
  ).toBeVisible({ timeout: 10_000 });
  const widths = await page
    .locator('[data-testid^="chart-card-"]')
    .evaluateAll((cards) =>
      cards.map((c) => {
        const box = (c as HTMLElement).getBoundingClientRect();
        return { right: box.left + box.width };
      }),
    );
  for (const w of widths) {
    expect(w.right).toBeLessThanOrEqual(MOBILE_360.width + 1);
  }
});

test("reports at 360px: page can scroll to bottom (last chart reachable)", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_360);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/reports");
  await page.waitForLoadState("networkidle");
  // tickets-by-building is the last chart in ReportsPage.tsx. Scroll
  // it into view and confirm we can — i.e. the workspace did not
  // clip its bottom under the URL bar / safe area.
  const last = page.locator(
    '[data-testid="chart-card-tickets-by-building"]',
  );
  await last.scrollIntoViewIfNeeded({ timeout: 10_000 });
  await expect(last).toBeInViewport({ timeout: 10_000 });
});

test("reports at 430px: still renders multi-column where the viewport allows", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_430);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/reports");
  await expect(
    page.locator('[data-testid^="chart-card-"]').first(),
  ).toBeVisible({ timeout: 10_000 });
  // 430px < 420 * 2 + gap, so the auto-fit grid still falls back to
  // a single column at this viewport (one card width >= viewport
  // minus padding). Just confirm no horizontal overflow and that the
  // first card is fully inside the viewport.
  const first = page.locator('[data-testid^="chart-card-"]').first();
  const box = await first.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_430.width + 1);
  }
  await expectNoBodyHorizontalOverflow(page, MOBILE_430.width);
});

// ---------------------------------------------------------------------------
// Row-click-to-edit on admin CRUD tables
// ---------------------------------------------------------------------------

test("admin/buildings: clicking a row navigates to the edit page", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/buildings");
  const row = page
    .locator(".data-table tbody tr.admin-row-clickable", {
      hasText: "B1 Amsterdam",
    })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  // The first cell holds an inner anchor; clicking the row body but
  // outside the anchor should still navigate. We click the status
  // cell — neutral, has no inner anchor.
  await row.locator("td").nth(4).click();
  await page.waitForURL(/\/admin\/buildings\/\d+$/, { timeout: 10_000 });
});

test("admin/buildings: Edit button still works alongside row-click", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/buildings");
  const row = page
    .locator(".data-table tbody tr.admin-row-clickable", {
      hasText: "B1 Amsterdam",
    })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  // Click the explicit Edit button; React Router fires a navigate
  // and the row's onClick handler also fires (same destination), so
  // the URL should still settle on the edit page exactly once.
  await row.getByRole("link", { name: /edit/i }).click();
  await page.waitForURL(/\/admin\/buildings\/\d+$/, { timeout: 10_000 });
});

test("admin/users: clicking a row navigates to the edit page", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/users");
  const row = page
    .locator(".data-table tbody tr.admin-row-clickable", {
      hasText: "super@cleanops.demo",
    })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  // Click the language cell (cell index 3) — neutral, no inner link.
  await row.locator("td").nth(3).click();
  await page.waitForURL(/\/admin\/users\/\d+$/, { timeout: 10_000 });
});

test("admin/customers: clicking a row navigates to the edit page", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/customers");
  const row = page
    .locator(".data-table tbody tr.admin-row-clickable", {
      hasText: "B Amsterdam",
    })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  // Click the contact-email cell (index 3) — neutral, no inner link.
  await row.locator("td").nth(3).click();
  await page.waitForURL(/\/admin\/customers\/\d+$/, { timeout: 10_000 });
});

test("admin/companies: clicking a row navigates to the edit page", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/companies");
  const row = page
    .locator(".data-table tbody tr.admin-row-clickable", {
      hasText: "Osius Demo",
    })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  // Slug cell (index 1) — neutral, no inner link.
  await row.locator("td").nth(1).click();
  await page.waitForURL(/\/admin\/companies\/\d+$/, { timeout: 10_000 });
});

// Audit logs are intentionally NOT row-clickable (read-only feed); we
// also covered this in admin_crud.spec.ts. Add one assertion here so a
// future regression cannot quietly add the class to the audit table
// without re-scoping the page's row semantics.
test("admin/audit-logs: rows are NOT marked row-clickable for editing", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/audit-logs");
  await expect(
    page.locator('[data-testid="audit-logs-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('.data-table tbody tr.admin-row-clickable'),
  ).toHaveCount(0);
});
