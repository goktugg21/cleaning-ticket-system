import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 17 — public reply / internal note UX.
 *
 * Confirms the role-gated behaviour of the message composer on the
 * ticket detail page:
 *
 *   - Staff (here: company-admin) see the public/internal toggle.
 *   - Customer-users do NOT see the toggle and cannot post internal
 *     notes (backend also enforces, see `TicketMessageSerializer`).
 *
 * We use the seeded "[DEMO] Pantry zeepdispenser" ticket because it
 * is in WAITING_CUSTOMER_APPROVAL — both staff and Amanda (B3
 * pair-access customer-user) can reach it.
 */

const DEMO_TICKET_TITLE = "Pantry zeepdispenser";

async function openDemoTicket(page: import("@playwright/test").Page) {
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: DEMO_TICKET_TITLE })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  // Wait for the workflow card or the messages composer to mount.
  await page.waitForLoadState("networkidle");
}

test("Staff (company-admin) sees the public/internal toggle on a ticket", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await openDemoTicket(page);
  await expect(page.locator(".composer-toggle")).toBeVisible({
    timeout: 10_000,
  });
});

test("Customer-user (Amanda) does NOT see the public/internal toggle", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await openDemoTicket(page);
  // The composer textarea is visible (customer can post a public reply)
  // but the toggle row is not rendered.
  await expect(page.locator(".notes-textarea")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.locator(".composer-toggle")).toHaveCount(0);
});
