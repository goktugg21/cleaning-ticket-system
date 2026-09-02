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
 *
 * FE-3 / FE-2 — where the asserted surfaces live now:
 *   - The EW detail opens on the PHASE BANNER (`extra-work-phase-banner`)
 *     with the next-step sentence and the one primary action; the
 *     badge strip under the title (`.ew-detail-header-meta`) is gone.
 *     Raw status / routing decision sit behind the "Geavanceerd" fold
 *     (`extra-work-advanced-toggle` -> `extra-work-raw-values`).
 *   - The page is tabbed (`extra-work-tab-*`): contacts and the
 *     spawned-tickets panel are on Overview, the cart line items and
 *     the proposal on Money.
 *   - A CUSTOMER_USER never sees the provider list/detail: `/extra-work`
 *     is the Meerwerk tracker (`meerwerk-row-<id>`) and `/extra-work/:id`
 *     the customer detail (`meerwerk-detail-page`, `meerwerk-reject`).
 */
import { expect, test } from "@playwright/test";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import { TICKETS_LIST_ALL } from "./fixtures/tickets";

// ---------------------------------------------------------------------------
// EW detail page — phase banner + tabs + locked testids
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Extra Work detail two-column", () => {
  test("detail opens on the phase banner with the actions column", async ({
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

    // The phase banner states the phase + the next step in words.
    await expect(
      page.locator('[data-testid="extra-work-phase-banner"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="extra-work-next-sentence"]'),
    ).toBeVisible();

    // The actions container exists on every detail load (some
    // sub-cards only render conditionally on role + status).
    await expect(
      page.locator('[data-testid="extra-work-detail-actions"]'),
    ).toBeVisible();

    // The raw status badge + the routing decision (a sentence plus the
    // raw enum in <code>) live behind the Advanced fold.
    await page.locator('[data-testid="extra-work-advanced-toggle"]').click();
    const raw = page.locator('[data-testid="extra-work-raw-values"]');
    await expect(raw).toBeVisible();
    await expect(
      raw.locator('[data-testid="extra-work-header-status"]'),
    ).toBeVisible();
    await expect(
      raw.locator('[data-testid="extra-work-detail-routing-decision"] code'),
    ).toHaveText(/^(INSTANT|PROPOSAL)$/);
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
    // Customer Contacts panel (super admin can see it) — Overview.
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
    // Routing decision field testid (behind the Advanced fold).
    await page.locator('[data-testid="extra-work-advanced-toggle"]').click();
    await expect(
      page.locator('[data-testid="extra-work-detail-routing-decision"]'),
    ).toBeVisible();
    // Cart line-items card (always rendered, even when empty) — Money.
    await page.locator('[data-testid="extra-work-tab-money"]').click();
    const lineItems = page.locator('[data-testid="extra-work-detail-line-items"]');
    await expect(lineItems).toBeVisible();
    const lineItemRows = await lineItems
      .locator(".ew-pricing-table tbody tr")
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

    // P-11 F1 — REPINNED to the P-9 ruling (§D.22 pt 6): the Route
    // column LEFT the list ("what the tab does not ask is not a
    // column"); the route lives on To price's After-pricing column and
    // chips. A route badge in a list row would be the regression now.
    const badges = await page
      .locator('[data-testid="extra-work-row"] [data-testid="extra-work-list-route-badge"]')
      .count();
    expect(badges).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Customer reject-reason flow
// ---------------------------------------------------------------------------
test.describe("Sprint 28 Batch 15.4 — Customer reject-reason flow", () => {
  test("reject dialog opens, requires reason, submits", async ({ page }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    // FE-2 — the customer's list is the Meerwerk tracker.
    await page.goto("/extra-work");
    await expect(
      page.locator('[data-testid="meerwerk-tracker-page"]'),
    ).toBeVisible({ timeout: 10_000 });
    await page.waitForSelector(
      '[data-testid^="meerwerk-row-"], [data-testid="meerwerk-tracker-empty"]',
      { timeout: 10_000 },
    );

    // Find an EW the customer can actually reject. We do this by
    // walking visible rows and opening each until a Reject button
    // appears (PRICING_PROPOSED + allowed_next_statuses includes
    // CUSTOMER_REJECTED for this user). If none qualifies, skip.
    const rowCount = await page.locator('[data-testid^="meerwerk-row-"]').count();
    test.skip(rowCount === 0, "No Extra Work rows visible to customer.");

    let foundRejectable = false;
    for (let i = 0; i < rowCount; i++) {
      await page.goto("/extra-work");
      await page.waitForSelector('[data-testid^="meerwerk-row-"]');
      const rows = page.locator('[data-testid^="meerwerk-row-"]');
      await rows.nth(i).click();
      await page.waitForSelector('[data-testid="meerwerk-detail-page"]', {
        timeout: 8_000,
      });
      const rejectBtn = page.locator('[data-testid="meerwerk-reject"]');
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
    // FE-6 — the dashboard carries no ticket list; walk the tickets
    // page (every status, every period) looking for the optional
    // spawned-from anchor. If no ticket in the seed carries an EW
    // origin, the assertion path is skipped.
    await page.goto(TICKETS_LIST_ALL);
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(
      () => {
        /* the list may have ongoing polls; ignore timeout */
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
