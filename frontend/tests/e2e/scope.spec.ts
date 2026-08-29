import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs, logoutFromTopbar } from "./fixtures/login";
import { TICKETS_LIST_ALL } from "./fixtures/tickets";

/**
 * Sprint 16 — visibility scope smoke.
 *
 * Confirms the Sprint-14 customer-user pair check + Sprint-15 ticket
 * flow hardening hold end-to-end through the UI:
 *
 *   - A customer-user with access only to B3 (Amanda) sees only B3
 *     tickets in her list, only B3 as the building of the create
 *     form, and gets a "not found" / redirect when typing a B1-ticket
 *     URL directly.
 *   - A building manager assigned only to B1 (Murat) sees only B1
 *     tickets and not the B2/B3 ones.
 *
 * FE-4 / FE-6 — where each role's ticket LIST lives now:
 *   - provider roles (SA / CA / BM): `/tickets`, which opens on the
 *     Open tab for this month — the specs deep-link `TICKETS_LIST_ALL`
 *     so every seeded ticket in scope is on the page regardless of
 *     its status or when the seed ran. The building is the
 *     `.td-facility` cell.
 *   - customer roles: `/my/meldingen` (the dashboard at `/` is the
 *     customer Start page and `/tickets` redirects there). Rows carry
 *     `my-meldingen-row`; the building is a plain cell, so the row's
 *     text is what the scope assertions read.
 *   - the customer create form is the Melding flow: with ONE building
 *     the control is a fixed line (`melding-building-fixed`), with
 *     several it is a `<select data-testid="melding-building">`.
 *
 * The tests rely on `seed_demo_data` having run, which produces one
 * ticket per building.
 */

async function customerRowTexts(
  page: import("@playwright/test").Page,
): Promise<string[]> {
  await page.goto("/my/meldingen");
  await expect(
    page.locator('[data-testid="my-meldingen-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  await page.waitForLoadState("networkidle");
  const rows = page.locator('[data-testid="my-meldingen-row"]');
  const texts: string[] = [];
  for (let i = 0; i < (await rows.count()); i++) {
    texts.push(((await rows.nth(i).textContent()) ?? "").trim());
  }
  return texts;
}

test("Amanda (B3 only) sees only B3 tickets in her meldingen list", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  const rows = await customerRowTexts(page);
  // Amanda's seed pair: B3 only. The seed creates one ticket per
  // building (4 total), but only one of them is at B3 + B Amsterdam,
  // so Amanda's list has exactly that row.
  expect(rows.length).toBeGreaterThanOrEqual(1);
  for (const row of rows) {
    expect(row).toContain("B3 Amsterdam");
    expect(row).not.toContain("B1 Amsterdam");
    expect(row).not.toContain("B2 Amsterdam");
  }
});

test("Amanda gets 404 when navigating directly to a B1 ticket URL", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerAll);
  // Discover the IDs of B1 tickets while logged in as Tom (his own
  // tickets are all at B1). We grab any row whose text says
  // "B1 Amsterdam" and capture its ticket detail link.
  await page.goto("/my/meldingen");
  await expect(
    page.locator('[data-testid="my-meldingen-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  await page.waitForLoadState("networkidle");
  const b1Rows = page.locator('[data-testid="my-meldingen-row"]', {
    hasText: "B1 Amsterdam",
  });
  expect(await b1Rows.count()).toBeGreaterThan(0);
  const b1Link = b1Rows.first().locator('a[href^="/tickets/"]').first();
  const href = await b1Link.getAttribute("href");
  expect(href).toBeTruthy();

  // Now switch to Amanda. Logout via the user menu is the cleanest
  // path — no token cleanup race because the AuthContext wipes
  // localStorage before re-redirecting to /login.
  await logoutFromTopbar(page);
  await loginAs(page, DEMO_USERS.customerB3);
  await page.goto(href!);
  // The detail page surfaces an error / not-found banner. We assert
  // the visible result text rather than the HTTP status because the
  // SPA handles the 404 internally.
  await expect(
    page.locator(".alert-error, .empty-state").first(),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[data-testid="ticket-facts"]')).toHaveCount(0);
});

test("Murat (B1 only) does not see B2/B3 tickets", async ({ page }) => {
  await loginAs(page, DEMO_USERS.managerB1);
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const text of cells) {
    expect(text).not.toContain("B2 Amsterdam");
    expect(text).not.toContain("B3 Amsterdam");
  }
});

test("Building dropdown on /tickets/new respects manager scope", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.managerB1);
  await page.goto("/tickets/new");
  // Wait for the building <select> to render at least one option.
  const select = page.locator("#f-building");
  await expect(select).toBeVisible({ timeout: 10_000 });
  const optionLabels = await select.locator("option").allTextContents();
  // At least the placeholder + B1. No B2 or B3 should leak in.
  expect(optionLabels.some((t) => t.includes("B1 Amsterdam"))).toBe(true);
  expect(optionLabels.some((t) => t.includes("B2 Amsterdam"))).toBe(false);
  expect(optionLabels.some((t) => t.includes("B3 Amsterdam"))).toBe(false);
});

// ---------------------------------------------------------------------------
// Sprint 17 — extend the scope coverage to every persona.
//
// Each demo ticket lives at exactly one building (the seed creates
// one ticket per B1/B2/B3 plus a closed kitchen-tap at B1, four
// total). Every persona below should see exactly the buildings their
// role + access grants describe.
// ---------------------------------------------------------------------------

const DEMO_BUILDINGS = ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"];

async function listFacilityCells(
  page: import("@playwright/test").Page,
): Promise<string[]> {
  await page.goto(TICKETS_LIST_ALL);
  await expect(
    page.locator('[data-testid="dashboard-tickets-section"]'),
  ).toBeVisible({ timeout: 10_000 });
  await page.waitForLoadState("networkidle");
  // The skeleton rows give way to the real table once the list loads.
  await expect(page.locator('[data-testid="tickets-skeleton"]')).toHaveCount(0, {
    timeout: 10_000,
  });
  const rows = page.locator(".ticket-list-wrap .data-table tbody tr");
  const rowCount = await rows.count();
  const cells: string[] = [];
  for (let i = 0; i < rowCount; i++) {
    const cell = rows.nth(i).locator(".td-facility");
    if ((await cell.count()) > 0) {
      cells.push((await cell.textContent())?.trim() ?? "");
    }
  }
  return cells;
}

test("Super admin sees all 3 demo buildings in the ticket list", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  const cells = await listFacilityCells(page);
  for (const b of DEMO_BUILDINGS) {
    expect(cells.some((c) => c.includes(b))).toBe(true);
  }
});

test("Company admin sees all 3 demo buildings in the ticket list", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  const cells = await listFacilityCells(page);
  for (const b of DEMO_BUILDINGS) {
    expect(cells.some((c) => c.includes(b))).toBe(true);
  }
});

test("Gokhan (manager B1+B2+B3) sees all 3 buildings", async ({ page }) => {
  await loginAs(page, DEMO_USERS.managerAll);
  const cells = await listFacilityCells(page);
  for (const b of DEMO_BUILDINGS) {
    expect(cells.some((c) => c.includes(b))).toBe(true);
  }
});

test("Isa (manager B2 only) sees only B2 tickets", async ({ page }) => {
  await loginAs(page, DEMO_USERS.managerB2);
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const c of cells) {
    expect(c).toContain("B2 Amsterdam");
    expect(c).not.toContain("B1 Amsterdam");
    expect(c).not.toContain("B3 Amsterdam");
  }
});

test("Tom (plain CUSTOMER_USER, view_own) sees only tickets he created", async ({
  page,
}) => {
  // Sprint 23A tightened plain CUSTOMER_USER scope from "every ticket
  // at any (customer, building) pair I have access to" to "tickets I
  // myself created at those pairs" (`view_own`). Tom has CUSTOMER_USER
  // access_role on B1+B2+B3, but the demo seed has Iris creating the
  // B2 ticket and Amanda creating the B3 ticket, so Tom's list
  // shows only the B1 tickets he himself raised. Upgrading Tom's
  // per-building access_role to CUSTOMER_LOCATION_MANAGER (Sprint 23C)
  // is what unlocks the broader visibility — covered by
  // sprint23c_access_role_editor.spec.ts.
  await loginAs(page, DEMO_USERS.customerAll);
  const rows = await customerRowTexts(page);
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    expect(row).toContain("B1 Amsterdam");
  }
  expect(rows.some((c) => c.includes("B2 Amsterdam"))).toBe(false);
  expect(rows.some((c) => c.includes("B3 Amsterdam"))).toBe(false);
});

test("Iris (customer B1+B2 only) sees no B3 tickets", async ({ page }) => {
  await loginAs(page, DEMO_USERS.customerB1B2);
  const rows = await customerRowTexts(page);
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    expect(row).not.toContain("B3 Amsterdam");
  }
});

test("Customer melding form for Amanda is fixed to B3", async ({ page }) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await page.goto("/tickets/new");
  await expect(
    page.locator('[data-testid="melding-create-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  // One building → no dropdown at all; the form states the building.
  const fixed = page.locator('[data-testid="melding-building-fixed"]');
  await expect(fixed).toBeVisible({ timeout: 10_000 });
  await expect(fixed).toContainText("B3 Amsterdam");
  await expect(page.locator('[data-testid="melding-building"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="melding-create-page"]')).not.toContainText(
    "B1 Amsterdam",
  );
  await expect(page.locator('[data-testid="melding-create-page"]')).not.toContainText(
    "B2 Amsterdam",
  );
});
