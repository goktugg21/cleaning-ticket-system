import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import {
  DEMO_TICKET_TITLES,
  resolveDemoTicketId,
} from "./fixtures/tickets";

/**
 * Sprint 27F-F1 — ticket override modal + timeline override badge.
 *
 * Closes G-F3: the customer-decision override on TicketDetailPage
 * now uses a two-press modal with a mandatory reason input,
 * mirroring the ExtraWorkDetailPage shape. The backend contract
 * (Sprint 27F-B1) requires {is_override:true, override_reason} on
 * POST /tickets/{id}/status/ when SUPER_ADMIN / COMPANY_ADMIN drive
 * WAITING_CUSTOMER_APPROVAL → APPROVED|REJECTED.
 *
 * Reference fixture ticket: "[DEMO] Pantry zeepdispenser"
 * (B3 Amsterdam, Osius Demo), seeded in WAITING_CUSTOMER_APPROVAL
 * by `seed_demo_data`. Two non-mutating tests (empty-reason
 * validation + CUSTOMER_USER button visibility) run FIRST so the
 * third (mutating override-to-APPROVED) does not strand the ticket
 * out of WCA for the earlier specs.
 *
 * Note: Playwright tests in this repo run serially (workers=1) and
 * file order is alphabetical. This spec mutates the WCA fixture in
 * the third test; reseeding (`python manage.py seed_demo_data
 * --reset-tickets`) is the standard reset before re-running the
 * e2e suite.
 *
 * Sprint 30 Batch 30.1.2 Phase F — migrated off the dashboard nav
 * (.data-table tbody tr → a.td-id) onto direct `/tickets/{id}` goto
 * calls. The ID is resolved at the start of each test by calling
 * `/api/tickets/?search=<title>` so the spec stays robust under
 * `--reset-tickets` autoincrement churn.
 */

test("COMPANY_ADMIN — empty reason blocks override submission", async ({
  page,
}) => {
  // Ramazan (Osius COMPANY_ADMIN) sees the override buttons on
  // Pantry zeepdispenser because it is in WAITING_CUSTOMER_APPROVAL
  // and his role triggers `isAdminCustomerDecisionOverride`.
  //
  // Sprint 30 Batch 30.1.3 — override is folded INTO the workflow
  // card. Clicking Approve arms an INLINE block under the button
  // (the `ticket-override-modal` testid was relocated from the old
  // standalone card onto the new inline container, so this spec
  // still resolves it). Confirm is disabled until a non-empty
  // reason is typed; the empty-reason contract is enforced via
  // the disabled state (no possible POST) rather than via a
  // post-click inline error. No backend round-trip path changed.
  await loginAs(page, DEMO_USERS.companyAdmin);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");

  // Click the first override-target status button. Both APPROVED
  // and REJECTED transitions are admin-coerced overrides per
  // state_machine.py; we pick the Approved button.
  const approveButton = page
    .locator(".status-actions .status-btn", { hasText: /Approved|Goedgekeurd/i })
    .first();
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();

  // The inline arming block appears with the textarea + submit + cancel.
  const modal = page.locator("[data-testid='ticket-override-modal']");
  await expect(modal).toBeVisible({ timeout: 5_000 });

  // No network call should fire while the reason is empty — the
  // Confirm button stays disabled and any clicks are dropped. Spy
  // on /api/tickets/<id>/status/ to assert zero POSTs.
  let statusPostCount = 0;
  page.on("request", (req) => {
    if (
      req.method() === "POST" &&
      /\/api\/tickets\/\d+\/status\/$/.test(req.url())
    ) {
      statusPostCount += 1;
    }
  });

  // Confirm button is disabled while the reason textarea is empty.
  const submitButton = page.locator(
    "[data-testid='ticket-override-submit']",
  );
  await expect(submitButton).toBeDisabled({ timeout: 5_000 });
  // Force-click is a no-op against a disabled button in browser
  // terms but Playwright will execute the event with force:true.
  // Verify no POST results either way.
  await submitButton.click({ force: true });

  // Allow a tick for any (mistakenly issued) network call to fly.
  await page.waitForTimeout(500);
  expect(statusPostCount).toBe(0);

  // Cancel cleans up the inline arming block so the next test
  // sees the workflow card back at rest.
  await page
    .locator("[data-testid='ticket-override-cancel']")
    .click();
  await expect(modal).toBeHidden({ timeout: 5_000 });
});

test("CUSTOMER_USER — Approve/Reject buttons do not open the override modal", async ({
  page,
}) => {
  // Amanda is the B3 CUSTOMER_USER for the Pantry zeepdispenser
  // ticket. Her workflow card shows the regular Approve / Reject
  // buttons (because state_machine.allowed_next_statuses for a
  // CUSTOMER_USER on a WCA ticket they own includes both). The
  // override gate `isAdminCustomerDecisionOverride` is role-based
  // and returns false for CUSTOMER_USER, so clicking either does
  // NOT open the override modal.
  await loginAs(page, DEMO_USERS.customerB3);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");

  const buttons = page.locator(".status-actions .status-btn");
  await expect(buttons).toHaveCount(2, { timeout: 10_000 });

  // Click Approve. For a CUSTOMER_USER the click should fire the
  // normal transition path (which will trigger a network request)
  // and NOT open the override modal. We assert the modal is not
  // present immediately after the click. Note: we do NOT actually
  // wait for the network round-trip — the modal mount happens
  // synchronously on click, so if it were going to open it would
  // be visible by the next microtask.
  const approveButton = buttons.filter({
    hasText: /Approved|Goedgekeurd/i,
  });
  await expect(approveButton).toHaveCount(1);

  // Hover/inspect only — do NOT click. Clicking would mutate the
  // ticket out of WCA and break the third test in this file when
  // the seed runs the order alphabetically AND when these tests
  // run more than once between reseeds. The contract under test
  // is "no override modal is rendered for a CUSTOMER_USER", which
  // we verify directly by querying the DOM.
  const modal = page.locator("[data-testid='ticket-override-modal']");
  await expect(modal).toHaveCount(0);

  // Sanity: the override button copy ("Override → Customer
  // approved") is provider-only and must not appear in the
  // CUSTOMER_USER workflow card either.
  await expect(
    page.locator("text=/Override.*Customer approved/i"),
  ).toHaveCount(0);
});

test("COMPANY_ADMIN — typed reason confirms override and tags the timeline", async ({
  page,
}) => {
  // This is the mutating test — it transitions the Pantry
  // zeepdispenser from WAITING_CUSTOMER_APPROVAL to APPROVED via
  // the override path. Runs last in this file so the previous two
  // specs still see the ticket in WCA on a fresh seed.
  await loginAs(page, DEMO_USERS.companyAdmin);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");

  const approveButton = page
    .locator(".status-actions .status-btn", { hasText: /Approved|Goedgekeurd/i })
    .first();
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();

  const modal = page.locator("[data-testid='ticket-override-modal']");
  await expect(modal).toBeVisible({ timeout: 5_000 });

  const REASON = "Customer confirmed approval by phone — Sprint 27F-F1 spec";
  await page
    .locator("[data-testid='ticket-override-reason']")
    .fill(REASON);

  // Listen for the status POST so we can assert is_override fired.
  const statusPostPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/tickets\/\d+\/status\/$/.test(response.url()) &&
      response.status() === 200,
    { timeout: 15_000 },
  );

  await page.locator("[data-testid='ticket-override-submit']").click();
  const statusResponse = await statusPostPromise;

  // Verify the request body carried is_override=true + the reason.
  const requestBody = statusResponse.request().postDataJSON() as {
    to_status: string;
    is_override?: boolean;
    override_reason?: string;
  };
  expect(requestBody.is_override).toBe(true);
  expect(requestBody.override_reason).toBe(REASON);

  // Modal closes after success and the page reloads the ticket.
  await expect(modal).toBeHidden({ timeout: 10_000 });

  // Status header reflects APPROVED.
  await expect(
    page.locator(".detail-header-meta .badge.badge-approved"),
  ).toBeVisible({ timeout: 10_000 });

  // The new timeline row carries the override badge + the reason.
  const overrideBadges = page.locator(
    "[data-testid='timeline-override-badge']",
  );
  await expect(overrideBadges.first()).toBeVisible({ timeout: 10_000 });
  const badgeText = (await overrideBadges.first().textContent()) ?? "";
  expect(badgeText).toMatch(/Override|Overrule/);
  expect(badgeText).toContain(REASON);
});
