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
