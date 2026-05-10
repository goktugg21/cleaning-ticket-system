import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

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
 */

test("Amanda sees Approve/Reject on the B3 waiting ticket", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await page.waitForLoadState("networkidle");

  const waitingRow = page.locator(".data-table tbody tr", {
    hasText: "Pantry zeepdispenser",
  });
  expect(await waitingRow.count()).toBeGreaterThan(0);
  await waitingRow.first().locator("a.td-id").click();

  // Status-action buttons are rendered from ticket.allowed_next_statuses;
  // the labels are i18n'd ("Move to Approved" / "Move to Rejected").
  const statusActions = page.locator(".status-actions .status-btn");
  await expect(statusActions).toHaveCount(2, { timeout: 10_000 });

  const labels = (await statusActions.allTextContents()).map((s) => s.trim());
  // Tolerate the i18n label drift by matching on the status enum tail.
  expect(labels.some((l) => /Approved|Goedgekeurd/i.test(l))).toBe(true);
  expect(labels.some((l) => /Rejected|Afgewezen/i.test(l))).toBe(true);
});

test("Iris cannot reach Amanda's B3 waiting ticket", async ({ page }) => {
  // Fetch the B3 ticket id from Tom's view (Tom has access to all).
  await loginAs(page, DEMO_USERS.customerAll);
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: "Pantry zeepdispenser" })
    .first();
  const href = await row.locator("a.td-id").getAttribute("href");
  expect(href).toBeTruthy();

  // Logout, log in as Iris (B1 + B2 only), and navigate directly.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.customerB1B2);
  await page.goto(href!);

  // The detail page renders the not-found / scope-error path. We
  // assert the absence of the workflow buttons rather than HTTP code,
  // because the SPA handles the API 404 internally.
  await expect(
    page.locator(".status-actions .status-btn"),
  ).toHaveCount(0, { timeout: 10_000 });
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
  // (with admin override available to staff). The button list should
  // therefore not contain APPROVED or REJECTED, only no-ops or none.
  await loginAs(page, DEMO_USERS.managerAll);
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: "Pantry zeepdispenser" })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  await page.waitForLoadState("networkidle");

  const labels = (
    await page.locator(".status-actions .status-btn").allTextContents()
  ).map((s) => s.trim());
  // The label may be i18n'd; tolerate Dutch / English variants by
  // checking against the underlying status name in either language.
  for (const l of labels) {
    expect(/Approved|Goedgekeurd/i.test(l)).toBe(false);
    expect(/Rejected|Afgewezen/i.test(l)).toBe(false);
  }
});

test("Super admin sees REOPENED_BY_ADMIN button on a CLOSED ticket", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: "Closed kitchen tap" })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  // Wait until the workflow card finishes rendering. networkidle
  // alone is not enough — the page does several Promise.all sets and
  // the buttons appear only after `loadTicket` resolves and the
  // useMemo recomputes from non-null `ticket`.
  const statusActions = page.locator(".status-actions .status-btn");
  await expect(statusActions.first()).toBeVisible({ timeout: 15_000 });

  const labels = (await statusActions.allTextContents()).map((s) => s.trim());
  // The seeded ticket is in CLOSED status. allowed_next_statuses for
  // a super-admin is "every status except the current one", so the
  // button list should have at least one entry mentioning REOPENED.
  expect(labels.length).toBeGreaterThan(0);
  expect(
    labels.some((l) => /Reopened|Heropend/i.test(l)),
  ).toBe(true);
});
