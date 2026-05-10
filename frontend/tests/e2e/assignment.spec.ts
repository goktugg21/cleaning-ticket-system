import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 17 — assignment card role and scope rules.
 *
 *   1. Customer-users do NOT see the assignment <select> at all.
 *      Backend also 403's `assign` and `assignable-managers`
 *      (`TicketViewSet`).
 *   2. Staff users see ONLY managers assigned to the ticket's
 *      building in the dropdown. The seeded shape is:
 *
 *        B1 ticket → assignable: Gokhan (B1+B2+B3), Murat (B1)
 *        B2 ticket → assignable: Gokhan, Isa
 *        B3 ticket → assignable: Gokhan
 *
 *      We use the B3 "[DEMO] Pantry zeepdispenser" ticket because
 *      its dropdown should NOT contain Murat or Isa.
 */

const B3_TICKET_TITLE = "Pantry zeepdispenser";

async function openTicketByTitle(
  page: import("@playwright/test").Page,
  title: string,
) {
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: title })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  await page.waitForLoadState("networkidle");
}

test("Staff sees only building-assigned managers in the assign dropdown", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await openTicketByTitle(page, B3_TICKET_TITLE);

  const select = page.locator(".assign-select");
  await expect(select).toBeVisible({ timeout: 10_000 });
  const options = (await select.locator("option").allTextContents()).map(
    (s) => s.trim(),
  );

  // The dropdown contains the "Unassigned" placeholder + every
  // manager assigned to THIS ticket's building. We do NOT assert a
  // strict count because the demo database can contain extra legacy
  // Gokhan rows seeded by earlier sprints (e.g.
  // `seed_b_amsterdam_demo`). The scope rule we DO test is that no
  // out-of-building manager appears.
  expect(options.length).toBeGreaterThanOrEqual(2);
  // Sanity: at least one Gokhan present (he is assigned to B3 in the
  // current seed). ASCII-safe substring check.
  expect(options.some((o) => o.toLowerCase().includes("gokhan"))).toBe(true);
  // Murat (B1) and the shared "Uğurlu" surname both Murat and Isa
  // carry — locating by surname avoids the Turkish "İ" lowercase
  // quirk on Isa's first name. Either of these strings appearing
  // would mean a B1- or B2-only manager leaked into the B3 dropdown.
  for (const denied of ["Murat", "Uğurlu"]) {
    expect(options.some((o) => o.includes(denied))).toBe(false);
  }
});

test("Customer-user (Amanda) does NOT see the assignment dropdown", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await openTicketByTitle(page, B3_TICKET_TITLE);
  await expect(page.locator(".assign-select")).toHaveCount(0);
});
