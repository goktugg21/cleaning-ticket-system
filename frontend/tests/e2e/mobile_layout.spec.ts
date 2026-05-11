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

  test("390px: dashboard renders the mobile ticket card list, no body overflow", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_390);
    await loginAs(page, DEMO_USERS.companyAdmin);
    // Sprint 22 final polish: below 600px we hide the desktop
    // `.ticket-list-wrap` table and render a card list instead.
    // The card list must be present, contain at least one card,
    // and not push the page itself into horizontal scroll.
    const cardList = page.locator('[data-testid="ticket-card-list"]');
    await expect(cardList).toBeVisible({ timeout: 10_000 });
    const firstCard = cardList.locator(".ticket-card").first();
    await expect(firstCard).toBeVisible({ timeout: 10_000 });
    // The desktop table-wrap exists in the DOM but is
    // `display: none` on phones, so its rendered box is empty.
    const wrapBox = await page.locator(".ticket-list-wrap").boundingBox();
    expect(wrapBox).toBeNull();
    // Body must not overflow horizontally on a phone.
    await expectNoBodyHorizontalOverflow(page, MOBILE_390.width);
  });

  test("430px: each ticket card has a tap-target height >= 44px", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_430);
    await loginAs(page, DEMO_USERS.companyAdmin);
    const cards = page.locator(
      '[data-testid="ticket-card-list"] .ticket-card-link',
    );
    await expect(cards.first()).toBeVisible({ timeout: 10_000 });
    const heights = await cards.evaluateAll((els) =>
      els.map((el) => (el as HTMLElement).getBoundingClientRect().height),
    );
    expect(heights.length).toBeGreaterThan(0);
    for (const h of heights) {
      expect(h).toBeGreaterThanOrEqual(44);
    }
    await expectNoBodyHorizontalOverflow(page, MOBILE_430.width);
  });

  test("360px: dashboard ticket card list does not horizontally overflow", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_360);
    await loginAs(page, DEMO_USERS.companyAdmin);
    const cardList = page.locator('[data-testid="ticket-card-list"]');
    await expect(cardList).toBeVisible({ timeout: 10_000 });
    // The card list itself must fit inside the viewport (its
    // scrollWidth and clientWidth match — no internal horizontal
    // overflow that would force the user to scroll sideways).
    const dims = await cardList.evaluate((el) => ({
      scrollWidth: (el as HTMLElement).scrollWidth,
      clientWidth: (el as HTMLElement).clientWidth,
    }));
    expect(dims.scrollWidth).toBeLessThanOrEqual(dims.clientWidth + 1);
    await expectNoBodyHorizontalOverflow(page, MOBILE_360.width);
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
  // Sprint 22 final polish: at 390px the dashboard renders the
  // `[data-testid="ticket-card-list"]` card list, not the desktop
  // table. Find the right card by its title text and tap it.
  const card = page
    .locator('[data-testid="ticket-card-list"] .ticket-card', {
      hasText: "Pantry zeepdispenser",
    })
    .first();
  await expect(card).toBeVisible({ timeout: 10_000 });
  await card.locator(".ticket-card-link").click();
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
  // Sprint 22 final mobile + copy polish: below 600px the desktop
  // `.data-table` is `display: none` and the parallel
  // `[data-testid="admin-card-list"]` of `.admin-card` items is
  // visible instead. Assert against the card list directly.
  await expect(
    page.locator('[data-testid="admin-card-list"] .admin-card').first(),
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
  // Either at least one audit card (mobile) or the empty-state card
  // mounts. `[data-testid="audit-row"]` (the desktop <tr>) is hidden
  // at 390px under the new card list; check the card instead.
  const cards = page.locator('[data-testid="audit-card"]');
  const empty = page.locator('[data-testid="audit-empty"]');
  await expect(cards.first().or(empty)).toBeVisible({ timeout: 10_000 });
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
      hasText: "superadmin@cleanops.demo",
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

// ===========================================================================
// SPRINT 20 FOLLOW-UP #2 — MOBILE PAGE-BOTTOM REACHABILITY
//
// Manual review on iPhone 14 Pro Max (430px) showed the last
// "Load by building" row partially cut at the absolute scroll bottom.
// On Playwright's Chromium the env(safe-area-inset-bottom) is always 0,
// so the only protection against a clipped last row is the .page-canvas
// rule's plain padding-bottom. The Sprint 20 follow-up bumps that value
// to 36 / 40 px on ≤480 / ≤360 phones; these tests defend that
// behaviour against future regressions.
// ===========================================================================

/**
 * Scroll the document to its absolute bottom and let layout settle.
 * Helper because Playwright's `scrollIntoViewIfNeeded` can stop early
 * when the element is "in viewport" but a few pixels still hang off
 * the bottom edge.
 */
async function scrollDocumentToBottom(
  page: import("@playwright/test").Page,
) {
  await page.evaluate(() => {
    const target = document.documentElement.scrollHeight;
    window.scrollTo(0, target);
  });
  // Recharts and other lazy components can re-flow on scroll; one
  // small tick is enough.
  await page.waitForTimeout(150);
}

for (const vp of [MOBILE_360, MOBILE_430]) {
  test(`dashboard at ${vp.width}px: last "Load by building" row is fully visible after scrolling to bottom`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    // Use a role that sees the by-building card. companyAdmin sees
    // all 3 demo buildings.
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.waitForLoadState("networkidle");
    // The dashboard's "Load by building" sidebar card collapses below
    // the main card on mobile and is the LAST visible card. Wait for
    // its rows to render.
    const lastBldRow = page.locator(".bld-list .bld-row-head").last();
    await expect(lastBldRow).toBeAttached({ timeout: 10_000 });
    await scrollDocumentToBottom(page);
    // The full row must be in viewport (ratio 1 = no clipping).
    await expect(lastBldRow).toBeInViewport({ ratio: 1, timeout: 5_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

for (const vp of [MOBILE_360, MOBILE_430]) {
  test(`reports at ${vp.width}px: last chart card is fully visible after scrolling to bottom`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/reports");
    await page.waitForLoadState("networkidle");
    const last = page.locator(
      '[data-testid="chart-card-tickets-by-building"]',
    );
    await expect(last).toBeAttached({ timeout: 10_000 });
    await scrollDocumentToBottom(page);
    await expect(last).toBeInViewport({ ratio: 1, timeout: 5_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

for (const vp of [MOBILE_360, MOBILE_430]) {
  test(`settings at ${vp.width}px: bottom of the settings page is reachable`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");
    // SettingsPage renders form sections and standalone cards; we
    // pick the last `.card` on the page, which is whatever final
    // section renders (notification preferences in the current
    // build). The key invariant: no matter what the last block is,
    // its full bounding box must clear the viewport bottom after a
    // hard scroll.
    const lastCard = page.locator("main .card").last();
    await expect(lastCard).toBeAttached({ timeout: 10_000 });
    await scrollDocumentToBottom(page);
    await expect(lastCard).toBeInViewport({ ratio: 1, timeout: 5_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

for (const vp of [MOBILE_360, MOBILE_430]) {
  test(`/admin/users at ${vp.width}px: pagination row is fully visible after scrolling to bottom`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/users");
    await page.waitForLoadState("networkidle");
    // The /admin/users table renders the demo users (≥7 rows) plus
    // any legacy users; the pagination is below the table when there
    // are enough rows for `next/previous` to be set. When there are
    // not enough rows, the empty/footer area is still the last block
    // — pick the last child of the .card so the test is robust to
    // either case.
    //
    // Sprint 22 final mobile + copy polish: at phone widths the
    // desktop `.table-wrap` is `display: none`; the visible
    // last-content block is the mobile `.admin-card-list` or the
    // pagination row below it. Include it in the selector so the
    // last-block lookup keeps working at 360/430.
    const lastBlock = page
      .locator(
        ".card .table-wrap, .card .admin-card-list, .card .pagination, .card .empty-state",
      )
      .last();
    await expect(lastBlock).toBeAttached({ timeout: 10_000 });
    await scrollDocumentToBottom(page);
    await expect(lastBlock).toBeInViewport({ timeout: 5_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

// ---------------------------------------------------------------------------
// /admin/invitations at phone widths — Sprint 20 follow-up #3 polish
// ---------------------------------------------------------------------------

/**
 * Sprint 20 follow-up #5: the Activity / "All invitations" card
 * must not have an internal horizontal scroll on phones. Returns
 * the scrollWidth − clientWidth delta of the .invitations-activity-card
 * (and the inner .table-wrap when present), so a test can assert it
 * is zero.
 */
async function measureInvitationsActivityOverflow(
  page: import("@playwright/test").Page,
) {
  return page.evaluate(() => {
    const activity = document.querySelector(
      ".invitations-activity-card",
    ) as HTMLElement | null;
    const wrap = activity?.querySelector(".table-wrap") as HTMLElement | null;
    return {
      activityOverflow: activity ? activity.scrollWidth - activity.clientWidth : -1,
      wrapPresent: !!wrap,
      wrapOverflow: wrap ? wrap.scrollWidth - wrap.clientWidth : 0,
      hasEmptyState: !!activity?.querySelector(".empty-state"),
      hasTableHead: !!activity?.querySelector(".invitations-table thead"),
    };
  });
}

test("/admin/invitations at 430x932: Activity card has no internal horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_430);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  // Send invitation submit must be visible (rendered + mid-page).
  const submit = page.locator('[data-testid="invite-submit"]');
  await expect(submit).toBeVisible({ timeout: 10_000 });
  // Activity card mounts after the form. Either the table OR the
  // empty-state must be present once the network idles.
  const activity = page.locator(".invitations-activity-card");
  await expect(activity).toBeVisible({ timeout: 10_000 });
  const m = await measureInvitationsActivityOverflow(page);
  // Real assertion: Activity card itself has no horizontal scroll.
  // Allow +1 px for sub-pixel rounding on the platform.
  expect(m.activityOverflow).toBeLessThanOrEqual(1);
  // If the wrap is present (i.e. there ARE rows), it must also not
  // overflow horizontally — the mobile card transform should remove
  // the table's horizontal width.
  if (m.wrapPresent) {
    expect(m.wrapOverflow).toBeLessThanOrEqual(1);
  }
  await expectNoBodyHorizontalOverflow(page, MOBILE_430.width);
});

test("/admin/invitations at 430x932: empty state has no orphan table header", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_430);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  const m = await measureInvitationsActivityOverflow(page);
  // The demo seed has no pending invitations by default, so the
  // empty-state card is what renders. Sprint 20 #5: in the empty
  // state we must NOT also render the table (whose 6-column
  // thead would otherwise show as an empty header row above the
  // empty state, with horizontal overflow on phones).
  if (m.hasEmptyState) {
    expect(m.hasTableHead).toBe(false);
    expect(m.wrapPresent).toBe(false);
  }
});

test("/admin/invitations at 430px: page bottom is reachable after scroll", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_430);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  // The Activity card is the last block on the page. After the
  // mobile margin-top tightening (16 → 10 px on ≤480), it should
  // still clear the safe-area-aware page-canvas padding when the
  // user scrolls to the absolute bottom.
  const activity = page.locator(".invitations-activity-card").last();
  await expect(activity).toBeAttached({ timeout: 10_000 });
  await scrollDocumentToBottom(page);
  // We assert the activity card is in viewport (any ratio is fine —
  // a long invitations table can stretch the card taller than the
  // viewport, in which case toBeInViewport passes if any part of it
  // is on screen, which is the user-relevant assertion).
  await expect(activity).toBeInViewport({ timeout: 5_000 });
  await expectNoBodyHorizontalOverflow(page, MOBILE_430.width);
});

test("/admin/invitations at 360px: status tabs row stays inside the viewport", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_360);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  const tabs = page.locator(".status-tabs");
  await expect(tabs).toBeVisible({ timeout: 10_000 });
  const box = await tabs.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    // The tabs row may wrap below the title on a 360px viewport but
    // must NOT overflow the viewport horizontally.
    expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_360.width + 1);
  }
  await expectNoBodyHorizontalOverflow(page, MOBILE_360.width);
});

test("/admin/invitations at 360x640: page may scroll but Activity is reachable AND has no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_360);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  // 360x640 is much shorter than the form + activity stack — the
  // page WILL scroll vertically. What we assert is:
  //   (a) the body itself has no HORIZONTAL overflow,
  //   (b) the Activity card is reachable via scroll-to-bottom, and
  //   (c) the Activity card itself has no internal horizontal
  //       scroll (Sprint 20 #5 mobile card transform).
  const activity = page.locator(".invitations-activity-card");
  await expect(activity).toBeAttached({ timeout: 10_000 });
  await scrollDocumentToBottom(page);
  await expect(activity).toBeInViewport({ timeout: 5_000 });
  await expectNoBodyHorizontalOverflow(page, MOBILE_360.width);
  const m = await measureInvitationsActivityOverflow(page);
  expect(m.activityOverflow).toBeLessThanOrEqual(1);
  if (m.wrapPresent) {
    expect(m.wrapOverflow).toBeLessThanOrEqual(1);
  }
});

test("/admin/invitations at 768x1024: desktop table layout still renders (no mobile card transform)", async ({
  page,
}) => {
  await page.setViewportSize(TABLET_768);
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/invitations");
  await page.waitForLoadState("networkidle");
  // The @media (max-width: 480px) mobile card transform must NOT
  // fire at 768px — the column header row (thead) must still
  // render so a tablet/desktop user sees the standard table layout.
  // We tolerate the empty-state path: when the demo data has no
  // rows for the active tab, the JSX renders the empty-state
  // instead of the table by design (Sprint 20 #5). Either branch
  // is fine; what we forbid is the broken hybrid (cards on tablet).
  const m = await measureInvitationsActivityOverflow(page);
  if (!m.hasEmptyState) {
    // Rows present → table must render with its column header.
    expect(m.hasTableHead).toBe(true);
  }
  // No body-level horizontal overflow.
  await expectNoBodyHorizontalOverflow(page, TABLET_768.width);
});

for (const vp of [MOBILE_360, MOBILE_430]) {
  test(`/tickets/new at ${vp.width}px: bottom of the page is reachable`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/tickets/new");
    await page.waitForLoadState("networkidle");
    // CreateTicketPage's `.create-layout` collapses to one column on
    // mobile, with `.create-main` (form sections + submit row) on top
    // and `.create-side` (summary / guidelines / SLA cards) BELOW it.
    // The last card on the page is therefore the SLA card from the
    // side panel — not the submit button. We check that last card is
    // fully visible after scrolling, which is the real "bottom is
    // reachable" assertion. The submit button itself is reachable by
    // scrolling up from the bottom; that's expected mobile behaviour
    // for a stacked form + sidebar layout.
    const lastCard = page.locator("main .card").last();
    await expect(lastCard).toBeAttached({ timeout: 10_000 });
    await scrollDocumentToBottom(page);
    await expect(lastCard).toBeInViewport({ ratio: 1, timeout: 5_000 });
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}
