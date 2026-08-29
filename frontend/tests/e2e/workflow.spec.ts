import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import {
  DEMO_TICKET_TITLES,
  openWorkflowFolds,
  resolveDemoTicketId,
  restorePantryToWaitingCustomerApproval,
} from "./fixtures/tickets";

/**
 * Sprint 16 — workflow buttons match backend.allowed_next_statuses.
 *
 * Sprint 15 removed the SUPER_ADMIN_UI_NEXT_STATUS frontend table and
 * made the page render whatever the API returns. These tests prove
 * the contract end-to-end:
 *
 *   - Amanda (B3 access only) on a B3 WAITING_CUSTOMER_APPROVAL ticket
 *     sees Approve / Reject buttons.
 *   - Iris (B1+B2) on the same B3 ticket cannot reach the page
 *     (queryset gate fires before render).
 *
 * Sprint 30 Batch 30.1.2 Phase F — migrated off the dashboard nav
 * (.data-table tbody tr → a.td-id) onto direct `/tickets/{id}` goto
 * calls. The ID is resolved at the start of each test by calling
 * `/api/tickets/?search=<title>` so the spec stays robust under
 * `--reset-tickets` autoincrement churn.
 *
 * FE-3 — every transition button carries `workflow-move-<STATUS>`.
 * The ONE primary action (for Amanda: Approve, with Reject beside it)
 * sits in the phase banner at the top of the page; corrections and
 * provider overrides sit behind the "Geavanceerd" / "Advanced" fold
 * and further forward steps behind "other steps". `openWorkflowFolds`
 * opens whichever folds exist so a spec can see every button; the
 * `.status-actions .status-btn` selector alone no longer reaches the
 * banner buttons.
 */

const MOVE_BUTTONS = '[data-testid^="workflow-move-"]';

// sprint27f's mutating test approves the pantry ticket; make sure the
// fixture is back in WAITING_CUSTOMER_APPROVAL before reading it here.
test.beforeAll(async () => {
  await restorePantryToWaitingCustomerApproval();
});

test("Amanda sees Approve/Reject on the B3 waiting ticket", async ({
  page,
}) => {
  // "[DEMO] Pantry zeepdispenser" (B3 Amsterdam,
  // WAITING_CUSTOMER_APPROVAL). Amanda is the B3 CUSTOMER_USER that
  // owns this ticket so allowed_next_statuses on a WCA row includes
  // both APPROVED and REJECTED for her.
  await loginAs(page, DEMO_USERS.customerB3);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");

  // Both decisions are the customer's primary action: they render as
  // banner buttons, no fold to open.
  await expect(
    page.locator('[data-testid="workflow-move-APPROVED"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('[data-testid="workflow-move-REJECTED"]'),
  ).toBeVisible();
  await expect(page.locator(MOVE_BUTTONS)).toHaveCount(2);
});

test("Iris cannot reach Amanda's B3 waiting ticket", async ({ page }) => {
  // Sprint 23A tightened plain CUSTOMER_USER scope to view_own; Tom
  // (used previously to discover the B3 ticket id) no longer sees
  // tickets created by other customer users. We discover the id
  // through the SUPER_ADMIN API (Iris cannot list it herself) and
  // then probe whether her browser can reach the detail page.
  await loginAs(page, DEMO_USERS.super);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );

  // Log out the super-admin session and switch to Iris.
  await loginAs(page, DEMO_USERS.customerB1B2);
  await page.goto(`/tickets/${ticketId}`);

  // The detail page renders the not-found / scope-error path. We
  // assert the absence of the workflow buttons (and of the fact
  // block) rather than HTTP code, because the SPA handles the API 404
  // internally.
  await expect(
    page.locator(".alert-error, .empty-state").first(),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(MOVE_BUTTONS)).toHaveCount(0);
  await expect(page.locator('[data-testid="ticket-facts"]')).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// Sprint 17 — additional workflow-button coverage.
//
// These confirm the UI mirrors `state_machine.allowed_next_statuses`
// for staff actors as well as the customer-user pair-aware case the
// existing tests cover.
// ---------------------------------------------------------------------------

test("Building manager sees no Approve/Reject on a WAITING_CUSTOMER_APPROVAL ticket", async ({
  page,
}) => {
  // Gokhan (manager B1+B2+B3) can REACH the B3 ticket but the state
  // machine does not let a building manager approve/reject — those
  // are SCOPE_CUSTOMER_LINKED transitions reserved for customer-users
  // (with admin override available to SA / COMPANY_ADMIN only). The
  // button set, folds included, must not contain APPROVED or REJECTED.
  await loginAs(page, DEMO_USERS.managerAll);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await expect(page.locator('[data-testid="ticket-facts"]')).toBeVisible({
    timeout: 10_000,
  });
  await openWorkflowFolds(page);

  await expect(
    page.locator('[data-testid="workflow-move-APPROVED"]'),
  ).toHaveCount(0);
  await expect(
    page.locator('[data-testid="workflow-move-REJECTED"]'),
  ).toHaveCount(0);
});

test("ticket detail timeline does NOT leak seed_demo_data internal note", async ({
  page,
}) => {
  // Sprint 22 final mobile + copy polish: the canonical seed writes
  // `note=f"seed_demo_data → {stop}"` on every transition row it
  // walks through. `sanitizeStatusNote()` on TicketDetailPage filters
  // those out at render time so demo users never see the marker. Pick
  // the [DEMO] Closed kitchen tap ticket — it walks through 4
  // transitions, so every history row's note is populated.
  //
  // RF-4 — the activity timeline is folded by default; open it first.
  await loginAs(page, DEMO_USERS.companyAdmin);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.kitchen_closed,
  );
  await page.goto(`/tickets/${ticketId}`);
  const toggle = page.locator('[data-testid="ticket-activity-toggle"]');
  await expect(toggle).toBeVisible({ timeout: 10_000 });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  const timeline = page.locator(".timeline").first();
  await expect(timeline).toBeVisible({ timeout: 10_000 });
  const text = (await timeline.textContent()) ?? "";
  expect(text).not.toContain("seed_demo_data");
});

test("Super admin sees REOPENED_BY_ADMIN button on a CLOSED ticket", async ({
  page,
}) => {
  // "[DEMO] Closed kitchen tap" (B1 Amsterdam, CLOSED).
  // Super admin's allowed_next_statuses for CLOSED includes every
  // other status; reopening is a correction, so it sits behind the
  // Advanced fold of the workflow card.
  await loginAs(page, DEMO_USERS.super);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.kitchen_closed,
  );
  await page.goto(`/tickets/${ticketId}`);
  // Wait until the workflow card finishes rendering. networkidle
  // alone is not enough — the page does several Promise.all sets and
  // the buttons appear only after `loadTicket` resolves.
  await expect(page.locator('[data-testid="side-card-workflow"]')).toBeVisible({
    timeout: 15_000,
  });
  await openWorkflowFolds(page);

  const reopen = page.locator('[data-testid="workflow-move-REOPENED_BY_ADMIN"]');
  await expect(reopen).toBeVisible({ timeout: 10_000 });
  expect(await page.locator(MOVE_BUTTONS).count()).toBeGreaterThan(0);
});
