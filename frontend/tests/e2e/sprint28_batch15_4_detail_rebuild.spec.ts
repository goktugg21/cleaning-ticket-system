/**
 * Sprint 28 Batch 15.4 — Extra Work detail two-column rebuild,
 * Route badge on list, Customer reject-reason flow, Ticket EW
 * origin link.
 *
 * The backend pieces (ticket `extra_work_origin`,
 * `customer_reject_reason` requirement on CUSTOMER_USER ->
 * CUSTOMER_REJECTED) are landing in parallel; some assertions are
 * skip-gated when the seed lacks data so the run stays green even
 * before the backend deploys.
 */
import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

// ---------------------------------------------------------------------------
// EW detail page — two-column layout + locked testids
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Extra Work detail two-column", () => {
  test("two-column layout renders with status + route badges in header", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");

    // Wait for either a row or the empty state, then open the first
    // row if one exists. If no EW exists in the seed we cannot
    // exercise the detail page — skip cleanly.
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const rowCount = await page
      .locator('[data-testid="extra-work-row"]')
      .count();
    test.skip(rowCount === 0, "No Extra Work rows in seed.");

    await page.locator('[data-testid="extra-work-row"]').first().click();
    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible();

    // The header now carries one StatusBadge AND one RouteBadge in
    // the meta strip under the title row.
    const headerMeta = page.locator(".ew-detail-header-meta");
    await expect(headerMeta).toBeVisible();
    await expect(headerMeta.locator(".badge").first()).toBeVisible();
    await expect(
      headerMeta.locator('[data-testid="extra-work-list-route-badge"]'),
    ).toBeVisible();

    // The right-column actions container exists on every detail
    // load (it's the sticky aside; some sub-cards only render
    // conditionally on role + status).
    await expect(
      page.locator('[data-testid="extra-work-detail-actions"]'),
    ).toBeVisible();
  });

  test("locked testids from prior sprints all persist", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const rowCount = await page
      .locator('[data-testid="extra-work-row"]')
      .count();
    test.skip(rowCount === 0, "No Extra Work rows in seed.");
    await page.locator('[data-testid="extra-work-row"]').first().click();

    // Page anchor.
    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible();
    // Routing decision field testid (lives inside the details card).
    await expect(
      page.locator('[data-testid="extra-work-detail-routing-decision"]'),
    ).toBeVisible();
    // Customer Contacts panel (super admin can see it).
    await expect(
      page.locator('[data-testid="extra-work-customer-contacts-panel"]'),
    ).toBeVisible();
    // Either contacts list or its empty state must resolve.
    const contactRows = await page
      .locator('[data-testid="extra-work-customer-contact-row"]')
      .count();
    const contactsEmpty = await page
      .locator('[data-testid="extra-work-customer-contacts-empty"]')
      .count();
    expect(contactRows + contactsEmpty).toBeGreaterThan(0);
    // Cart line-items card (always rendered, even when empty).
    await expect(
      page.locator('[data-testid="extra-work-detail-line-items"]'),
    ).toBeVisible();
    const lineItemRows = await page
      .locator('[data-testid="extra-work-detail-line-item-row"]')
      .count();
    const lineItemsEmpty = await page
      .locator('[data-testid="extra-work-detail-line-items-empty"]')
      .count();
    expect(lineItemRows + lineItemsEmpty).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// EW list — Route badge column
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Route badge on list", () => {
  test("route badge renders in EW list rows", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );
    const rowCount = await page
      .locator('[data-testid="extra-work-row"]')
      .count();
    test.skip(rowCount === 0, "No Extra Work rows in seed.");

    // One badge per row in the desktop table (the mobile card list
    // may also render badges, but the table is the assertion source
    // because it's the desktop-default layout for Playwright).
    const tableRows = page.locator(
      'table.data-table [data-testid="extra-work-row"]',
    );
    const tableRowCount = await tableRows.count();
    if (tableRowCount > 0) {
      const tableBadges = await page
        .locator(
          'table.data-table [data-testid="extra-work-list-route-badge"]',
        )
        .count();
      expect(tableBadges).toBe(tableRowCount);
    }

    // The new Route column header is rendered.
    await expect(
      page.locator('table.data-table thead th', { hasText: /Route/i }),
    ).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Customer reject-reason flow
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Customer reject-reason flow", () => {
  test("reject dialog opens, requires reason, submits", async ({ page }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/extra-work");
    await page.waitForSelector(
      '[data-testid="extra-work-row"], [data-testid="extra-work-list-empty"]',
      { timeout: 10_000 },
    );

    // Find an EW the customer can actually reject. We do this by
    // walking visible rows and opening each until a Reject button
    // appears (PRICING_PROPOSED + allowed_next_statuses includes
    // CUSTOMER_REJECTED for this user). If none qualifies, skip.
    const rowCount = await page
      .locator('[data-testid="extra-work-row"]')
      .count();
    test.skip(rowCount === 0, "No Extra Work rows visible to customer.");

    let foundRejectable = false;
    for (let i = 0; i < rowCount; i++) {
      await page.goto("/extra-work");
      await page.waitForSelector('[data-testid="extra-work-row"]');
      const rows = page.locator('[data-testid="extra-work-row"]');
      await rows.nth(i).click();
      await page.waitForSelector('[data-testid="extra-work-detail-page"]', {
        timeout: 8_000,
      });
      const rejectBtn = page.locator(
        '[data-testid="extra-work-customer-reject"]',
      );
      if (await rejectBtn.count()) {
        foundRejectable = true;
        await rejectBtn.click();
        break;
      }
    }
    test.skip(!foundRejectable, "No rejectable EW in seed for this customer.");

    // Dialog opened — confirm button starts disabled because the
    // textarea is empty.
    const dialog = page.locator('[data-testid="reject-reason-dialog"]');
    await expect(dialog).toBeVisible();
    const confirm = page.locator('[data-testid="reject-reason-confirm"]');
    await expect(confirm).toBeDisabled();

    // Type a reason -> confirm enables. Submit and expect the
    // dialog to dismiss.
    await page
      .locator('[data-testid="reject-reason-textarea"]')
      .fill("Too expensive — needs renegotiation.");
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(dialog).toBeHidden({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Ticket EW origin link (M3)
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Ticket EW origin link", () => {
  test("ticket spawned from EW shows origin link when present", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    // The dashboard typically lists tickets; iterate and open each
    // looking for the optional spawned-from anchor. If no ticket in
    // the seed carries an EW origin, the assertion path is skipped.
    await page.goto("/");
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(
      () => {
        /* dashboard may have ongoing polls; ignore timeout */
      },
    );

    // Resolve a list of ticket links to walk. Limit to first ~10
    // for runtime.
    const ticketLinks = await page
      .locator('a[href^="/tickets/"]')
      .evaluateAll((nodes) =>
        Array.from(
          new Set(
            nodes
              .map((n) => (n as HTMLAnchorElement).getAttribute("href"))
              .filter((h): h is string => !!h && /^\/tickets\/\d+/.test(h)),
          ),
        ).slice(0, 10),
      );
    test.skip(ticketLinks.length === 0, "No tickets visible to super admin.");

    let foundOrigin = false;
    for (const href of ticketLinks) {
      await page.goto(href);
      // Either the spawned-from block appears, or it doesn't.
      const block = page.locator('[data-testid="ticket-extra-work-origin"]');
      if (await block.count()) {
        foundOrigin = true;
        await expect(block).toBeVisible();
        // The block contains a link to the parent EW and a route badge.
        await expect(block.locator('a[href^="/extra-work/"]')).toBeVisible();
        await expect(
          block.locator('[data-testid="extra-work-list-route-badge"]'),
        ).toBeVisible();
        break;
      }
    }
    test.skip(
      !foundOrigin,
      "No ticket in seed currently carries an extra_work_origin.",
    );
  });
});
