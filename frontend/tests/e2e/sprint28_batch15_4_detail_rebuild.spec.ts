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
    // P-16 repin — the old shape walked Tom's tracker hoping a
    // rejectable row existed and self-skipped when none did (and one
    // eventually didn't). The spec seeds its OWN: Tom creates a
    // proposal-routed EW, the SA drives it to PRICING_PROPOSED with
    // the W-PLAN gate's recorded-override bypass, and Tom lands on it
    // directly. Self-contained; no dependence on leftover seed state.
    const { apiAs } = await import("./fixtures/apiAs");
    const sa = await apiAs(DEMO_USERS.super.email);
    const tom = await apiAs(DEMO_USERS.customerAll.email);
    let rejectableId: number | null = null;
    try {
      const tomEws = (await (
        await tom.get("/api/extra-work/?page_size=1")
      ).json()) as { results: Array<{ customer: number; building: number }> };
      const anchor = tomEws.results[0];
      if (anchor) {
        const create = await tom.post("/api/extra-work/", {
          data: {
            title: `B15.4 reject fixture ${Date.now()}`,
            description: "Seeded by the reject-dialog spec.",
            building: anchor.building,
            customer: anchor.customer,
            category: "DEEP_CLEANING",
            line_items: [{ custom_description: "Reject me", quantity: "1.00" }],
          },
        });
        if (create.status() === 201) {
          const body = (await create.json()) as { id: number };
          const r1 = await sa.post(`/api/extra-work/${body.id}/transition/`, {
            data: { to_status: "UNDER_REVIEW" },
          });
          // The workflow leg refuses without a pricing line
          // (pricing_line_items_required) — price it first.
          const price = await sa.post(
            `/api/extra-work/${body.id}/pricing-items/`,
            {
              data: {
                description: "b15.4 reject fixture line",
                unit_type: "FIXED",
                quantity: "1.00",
                unit_price: "100.00",
                vat_rate: "21.00",
              },
            },
          );
          const r2 = await sa.post(`/api/extra-work/${body.id}/transition/`, {
            data: {
              to_status: "PRICING_PROPOSED",
              override_reason: "b15.4 fixture: plan bypass",
            },
          });
          if (
            r1.status() === 200 &&
            price.status() === 201 &&
            r2.status() === 200
          ) {
            rejectableId = body.id;
          }
        }
      }
    } finally {
      await sa.dispose();
      await tom.dispose();
    }
    test.skip(
      rejectableId === null,
      "Could not seed a rejectable EW for the customer.",
    );

    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto(`/extra-work/${rejectableId}`);
    await page.waitForSelector('[data-testid="meerwerk-detail-page"]', {
      timeout: 10_000,
    });
    const rejectBtn = page.locator('[data-testid="meerwerk-reject"]');
    await expect(rejectBtn).toBeVisible({ timeout: 10_000 });
    await rejectBtn.click();

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
//
// P-16 DELETED: the standalone `ticket-extra-work-origin` block this
// test hunted for was retired at W21/P-13 — a spawned job's ticket now
// carries the agreement card + the Money-tab extra-work card ("every-
// thing the request page was opened for lives here"), and that fact is
// pinned by sprint29_batch29_8's J1/J3/J4 (`ticket-extra-work-money`
// visible on the landing). The hunt-then-skip shape also meant this
// test had silently skipped since the block vanished — a pin of
// nothing that exists any more.
// ---------------------------------------------------------------------------
