import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import {
  DEMO_TICKET_TITLES,
  resolveDemoTicketId,
} from "./fixtures/tickets";

/**
 * Sprint 17 — public reply / internal note UX.
 *
 * Confirms the role-gated behaviour of the message composer on the
 * ticket detail page:
 *
 *   - Staff (here: company-admin) see the private-note toggle.
 *   - Customer-users do NOT see the toggle and cannot post internal
 *     notes (backend also enforces, see `TicketMessageSerializer`).
 *
 * We use the seeded "[DEMO] Pantry zeepdispenser" ticket because it
 * is in WAITING_CUSTOMER_APPROVAL — both staff and Amanda (B3
 * pair-access customer-user) can reach it.
 *
 * FE-3 — the ticket is opened by id via the API fixture. The composer
 * sits in the messages card of the Overview tab. The old
 * `.composer-toggle` class selector is retired here: the same class
 * now also styles the page's tab pill bar, so it would match on every
 * ticket for every role. The private toggle has its own testid.
 */

async function openDemoTicket(page: import("@playwright/test").Page) {
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await expect(page.locator('[data-testid="ticket-composer"]')).toBeVisible({
    timeout: 10_000,
  });
}

test("Staff (company-admin) sees the private-note toggle on a ticket", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await openDemoTicket(page);
  // The switch's `data-testid` sits on the (visually hidden) checkbox
  // input; the label around it is the visible control.
  await expect(page.locator("label.composer-private-toggle")).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.locator('[data-testid="composer-private-toggle"]'),
  ).toHaveCount(1);
});

test("Customer-user (Amanda) does NOT see the private-note toggle", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await openDemoTicket(page);
  // The composer textarea is visible (customer can post a public reply)
  // but the private toggle is not rendered.
  await expect(page.locator(".notes-textarea")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.locator("label.composer-private-toggle")).toHaveCount(0);
  await expect(
    page.locator('[data-testid="composer-private-toggle"]'),
  ).toHaveCount(0);
});
