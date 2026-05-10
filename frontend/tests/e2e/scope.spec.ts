import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 16 — visibility scope smoke.
 *
 * Confirms the Sprint-14 customer-user pair check + Sprint-15 ticket
 * flow hardening hold end-to-end through the UI:
 *
 *   - A customer-user with access only to B3 (Amanda) sees only B3
 *     tickets in the dashboard list, only B3 in the building filter
 *     of the create-ticket form, and gets a "not found" / redirect
 *     when typing a B1-ticket URL directly.
 *   - A building manager assigned only to B1 (Murat) sees only B1
 *     tickets and not the B2/B3 ones.
 *
 * The tests rely on `seed_demo_data` having run, which produces one
 * ticket per building.
 */

test("Amanda (B3 only) sees only B3 tickets in the dashboard list", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  // Wait for the dashboard table to populate. The empty-state and the
  // table coexist; we wait for either rows or the empty card before
  // asserting on the row contents.
  await page.waitForLoadState("networkidle");
  const rows = page.locator(".data-table tbody tr");
  const rowCount = await rows.count();
  // Amanda's seed pair: B3 only. The seed creates one ticket per
  // building (4 total), but only one of them is at B3 + B Amsterdam,
  // so Amanda's list has exactly that row.
  expect(rowCount).toBeGreaterThanOrEqual(1);
  for (let i = 0; i < rowCount; i++) {
    const cell = rows.nth(i).locator(".td-facility");
    if ((await cell.count()) > 0) {
      await expect(cell).toContainText("B3 Amsterdam");
    }
  }
});

test("Amanda gets 404 when navigating directly to a B1 ticket URL", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerAll);
  // Discover the IDs of B1 tickets while logged in as Tom (full
  // access). We grab any row whose facility column says "B1 Amsterdam"
  // and capture its ticket detail link.
  await page.waitForLoadState("networkidle");
  const b1Rows = page.locator(".data-table tbody tr", { hasText: "B1 Amsterdam" });
  expect(await b1Rows.count()).toBeGreaterThan(0);
  const b1Link = b1Rows.first().locator("a.td-id");
  const href = await b1Link.getAttribute("href");
  expect(href).toBeTruthy();

  // Now switch to Amanda. Logout via the topbar Sign-out button is
  // the cleanest path — no token cleanup race because the AuthContext
  // wipes localStorage before re-redirecting to /login.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.customerB3);
  await page.goto(href!);
  // The detail page surfaces an error / not-found banner. We assert
  // the visible result text rather than the HTTP status because the
  // SPA handles the 404 internally.
  await expect(
    page
      .locator(".alert-error, .empty-state, .detail-not-found")
      .first(),
  ).toBeVisible({ timeout: 10_000 });
});

test("Murat (B1 only) does not see B2/B3 tickets", async ({ page }) => {
  await loginAs(page, DEMO_USERS.managerB1);
  await page.waitForLoadState("networkidle");
  const rows = page.locator(".data-table tbody tr");
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThan(0);
  for (let i = 0; i < rowCount; i++) {
    const cell = rows.nth(i).locator(".td-facility");
    if ((await cell.count()) > 0) {
      const text = (await cell.textContent())?.trim() ?? "";
      expect(text).not.toContain("B2 Amsterdam");
      expect(text).not.toContain("B3 Amsterdam");
    }
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
  await page.waitForLoadState("networkidle");
  const rows = page.locator(".data-table tbody tr");
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

test("Tom (customer B1+B2+B3) sees all 3 buildings' demo tickets", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerAll);
  const cells = await listFacilityCells(page);
  for (const b of DEMO_BUILDINGS) {
    expect(cells.some((c) => c.includes(b))).toBe(true);
  }
});

test("Iris (customer B1+B2 only) sees no B3 tickets", async ({ page }) => {
  await loginAs(page, DEMO_USERS.customerB1B2);
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const c of cells) {
    expect(c).not.toContain("B3 Amsterdam");
  }
});

test("Customer ticket-create dropdown for Amanda lists only B3", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await page.goto("/tickets/new");
  const select = page.locator("#f-building");
  await expect(select).toBeVisible({ timeout: 10_000 });
  const optionLabels = await select.locator("option").allTextContents();
  expect(optionLabels.some((t) => t.includes("B3 Amsterdam"))).toBe(true);
  expect(optionLabels.some((t) => t.includes("B1 Amsterdam"))).toBe(false);
  expect(optionLabels.some((t) => t.includes("B2 Amsterdam"))).toBe(false);
});
