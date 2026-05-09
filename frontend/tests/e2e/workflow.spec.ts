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
