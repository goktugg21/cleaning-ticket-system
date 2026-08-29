import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import {
  DEMO_TICKET_TITLES,
  openTicketTab,
  resolveDemoTicketId,
} from "./fixtures/tickets";

/**
 * Sprint 17 — assignment card role and scope rules.
 *
 *   1. Customer-users do NOT see the manager-assignment surface at
 *      all. Backend also 403's `assign` and `assignable-managers`
 *      (`TicketViewSet`).
 *   2. Staff users see ONLY managers assigned to the ticket's
 *      building as candidates. The seeded shape is:
 *
 *        B1 ticket → assignable: Gokhan (B1+B2+B3), Murat (B1)
 *        B2 ticket → assignable: Gokhan, Isa
 *        B3 ticket → assignable: Gokhan
 *
 *      We use the B3 "[DEMO] Pantry zeepdispenser" ticket because
 *      its candidate list should NOT contain Murat or Isa.
 *
 * FE-3 / W13 — the single `.assign-select` dropdown is gone. Manager
 * assignment is the "Responsible managers" section on the ticket's
 * People tab: a list of assigned managers plus an Add picker (a
 * dialog with one checkbox per eligible manager). The scope rule is
 * the same; it is now asserted over the union of the already-assigned
 * rows and the picker's candidates. The ticket is opened by id via the
 * API fixture instead of by hunting a row on the dashboard (which no
 * longer carries a ticket table).
 */

/**
 * Every manager name the section offers: the assigned rows plus the
 * candidates in the Add picker (the picker hides managers who are
 * already assigned, so neither list alone is the full building scope).
 */
async function responsibleManagerNames(
  page: import("@playwright/test").Page,
): Promise<string[]> {
  const names: string[] = [];
  const rows = page.locator('[data-testid="responsible-manager-row"]');
  for (let i = 0; i < (await rows.count()); i++) {
    names.push(((await rows.nth(i).textContent()) ?? "").trim());
  }
  // Open the picker: "Add" on a non-empty list, "Add first" on an
  // empty one. Exactly one of the two renders.
  const opener = page.locator(
    '[data-testid="responsible-managers-add-open"], [data-testid="responsible-managers-add-first"]',
  );
  await expect(opener.first()).toBeVisible({ timeout: 10_000 });
  await opener.first().click();
  await expect(
    page.locator('[data-testid="responsible-managers-dialog"]'),
  ).toBeVisible({ timeout: 5_000 });
  const candidates = page.locator(
    '[data-testid="responsible-managers-dialog"] .assign-picker-row',
  );
  for (let i = 0; i < (await candidates.count()); i++) {
    names.push(((await candidates.nth(i).textContent()) ?? "").trim());
  }
  await page.locator('[data-testid="responsible-managers-cancel"]').click();
  return names;
}

test("Staff sees only building-assigned managers in the responsible-managers picker", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await openTicketTab(page, "people");

  const section = page.locator(
    '[data-testid="responsible-managers-list"], [data-testid="responsible-managers-empty"]',
  );
  await expect(section.first()).toBeVisible({ timeout: 10_000 });

  const names = await responsibleManagerNames(page);

  // The section offers every manager assigned to THIS ticket's
  // building. We do NOT assert a strict count because the demo
  // database can contain extra legacy Gokhan rows seeded by earlier
  // sprints (e.g. `seed_b_amsterdam_demo`). The scope rule we DO test
  // is that no out-of-building manager appears.
  expect(names.length).toBeGreaterThanOrEqual(1);
  // Sanity: at least one Gokhan present (he is assigned to B3 in the
  // current seed). ASCII-safe substring check.
  expect(names.some((o) => o.toLowerCase().includes("gokhan"))).toBe(true);
  // Murat (B1) and the shared "Uğurlu" surname both Murat and Isa
  // carry — locating by surname avoids the Turkish "İ" lowercase
  // quirk on Isa's first name. Either of these strings appearing
  // would mean a B1- or B2-only manager leaked into the B3 scope.
  for (const denied of ["Murat", "Uğurlu"]) {
    expect(names.some((o) => o.includes(denied))).toBe(false);
  }
});

test("Customer-user (Amanda) does NOT see the responsible-managers surface", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  const ticketId = await resolveDemoTicketId(
    page,
    DEMO_TICKET_TITLES.pantry_wca,
  );
  await page.goto(`/tickets/${ticketId}`);
  await openTicketTab(page, "people");
  // The People tab mounts (the read-only assigned-staff card is the
  // customer's one staffing surface) but the manager section returns
  // null for a non-management role.
  await expect(
    page.locator('[data-testid="assigned-staff-card"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('[data-testid^="responsible-managers-"]'),
  ).toHaveCount(0);
});
