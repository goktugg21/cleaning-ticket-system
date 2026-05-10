import { expect, test } from "@playwright/test";

import {
  COMPANY_A_BUILDINGS,
  COMPANY_A_NAME,
  COMPANY_B_BUILDINGS,
  COMPANY_B_NAME,
  DEMO_USERS,
} from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 21 — cross-company isolation suite.
 *
 * The Sprint 21 `seed_demo_data` provisions two isolated demo
 * companies: Osius Demo (B1/B2/B3 Amsterdam) and Bright Facilities
 * (R1/R2 Rotterdam). These tests assert that:
 *
 *   1. SUPER_ADMIN sees tickets / buildings from BOTH companies.
 *   2. The COMPANY_ADMIN of Company A only sees Company A; same for B.
 *   3. Building managers and customer users in Company B never see
 *      any Company A building name on the dashboard, on /tickets, or
 *      on the ticket-create building dropdown — and vice versa.
 *   4. A Company A admin who guesses a Company B ticket's URL (or
 *      hits the API directly) gets a 404 / blocked response.
 *   5. The reports page (`/reports`) renders disjoint data for the
 *      two companies — there is no cross-tenant data leak in the
 *      backend report aggregations.
 *
 * The tests rely on the canonical `seed_demo_data` having run
 * against the target stack (the prod-shaped demo stack the rest of
 * the e2e suite uses). All tests use the throttle-aware loginAs
 * helper, so they tolerate the 20/minute auth-token rate limit
 * inside a single Playwright worker.
 */

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

test("Super admin sees tickets from both demo companies", async ({ page }) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/tickets");
  const cells = await listFacilityCells(page);
  // At least one ticket from a Company A building AND at least one
  // from a Company B building must appear.
  const seesCompanyA = COMPANY_A_BUILDINGS.some((b) =>
    cells.some((c) => c.includes(b)),
  );
  const seesCompanyB = COMPANY_B_BUILDINGS.some((b) =>
    cells.some((c) => c.includes(b)),
  );
  expect(seesCompanyA).toBe(true);
  expect(seesCompanyB).toBe(true);
});

test("Company A admin sees only Company A buildings on /tickets", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/tickets");
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const c of cells) {
    for (const b of COMPANY_B_BUILDINGS) {
      expect(c).not.toContain(b);
    }
  }
});

test("Company B admin sees only Company B buildings on /tickets", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdminB);
  await page.goto("/tickets");
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const c of cells) {
    for (const b of COMPANY_A_BUILDINGS) {
      expect(c).not.toContain(b);
    }
  }
});

test("Company B manager only sees R1/R2 buildings on /tickets", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.managerB);
  await page.goto("/tickets");
  const cells = await listFacilityCells(page);
  expect(cells.length).toBeGreaterThan(0);
  for (const c of cells) {
    // Only Rotterdam buildings allowed.
    const matchesB = COMPANY_B_BUILDINGS.some((b) => c.includes(b));
    expect(matchesB).toBe(true);
    for (const b of COMPANY_A_BUILDINGS) {
      expect(c).not.toContain(b);
    }
  }
});

test("Company B customer's /tickets/new building dropdown lists only R1/R2", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerBCo);
  await page.goto("/tickets/new");
  const select = page.locator("#f-building");
  await expect(select).toBeVisible({ timeout: 10_000 });
  const optionLabels = await select.locator("option").allTextContents();
  for (const b of COMPANY_B_BUILDINGS) {
    expect(optionLabels.some((t) => t.includes(b))).toBe(true);
  }
  for (const b of COMPANY_A_BUILDINGS) {
    expect(optionLabels.some((t) => t.includes(b))).toBe(false);
  }
});

test("Cross-company ticket detail API access returns 404 for Company A admin", async ({
  page,
  request,
}) => {
  // Step 1: log in as super admin and discover a Company B ticket id
  // via the /api/tickets/ endpoint with the building filter set to R1.
  await loginAs(page, DEMO_USERS.super);
  // Pull the super-admin access token out of localStorage so we can
  // issue the discovery call.
  const superToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  expect(superToken).toBeTruthy();
  const ticketsResp = await request.get("/api/tickets/", {
    headers: { Authorization: `Bearer ${superToken}` },
  });
  expect(ticketsResp.ok()).toBe(true);
  const ticketsBody = (await ticketsResp.json()) as {
    results: Array<{
      id: number;
      building: { name?: string } | null;
      building_name?: string;
    }>;
  };
  const isR1Or = (t: (typeof ticketsBody.results)[number]): boolean => {
    const name = t.building?.name ?? t.building_name ?? "";
    return COMPANY_B_BUILDINGS.some((b) => name.includes(b));
  };
  const companyBTicket = ticketsBody.results.find(isR1Or);
  expect(companyBTicket).toBeTruthy();

  // Step 2: log in as Company A admin and try to fetch that ticket.
  // The backend must respond with 404 (or 403). The SPA's detail page
  // renders an error/empty state — but we hit the API directly to
  // catch backend leaks that the UI might hide.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.companyAdmin);
  const adminAToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  expect(adminAToken).toBeTruthy();
  const detailResp = await request.get(
    `/api/tickets/${companyBTicket!.id}/`,
    { headers: { Authorization: `Bearer ${adminAToken}` } },
  );
  expect([403, 404]).toContain(detailResp.status());
});

test("Cross-company ticket detail URL renders not-found for Company A admin", async ({
  page,
  request,
}) => {
  // Same discovery as above, but assert the SPA shows an error state
  // when the URL is opened directly.
  await loginAs(page, DEMO_USERS.super);
  const superToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  const ticketsResp = await request.get("/api/tickets/", {
    headers: { Authorization: `Bearer ${superToken}` },
  });
  const ticketsBody = (await ticketsResp.json()) as {
    results: Array<{
      id: number;
      building: { name?: string } | null;
      building_name?: string;
    }>;
  };
  const companyBTicket = ticketsBody.results.find((t) => {
    const name = t.building?.name ?? t.building_name ?? "";
    return COMPANY_B_BUILDINGS.some((b) => name.includes(b));
  });
  expect(companyBTicket).toBeTruthy();

  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/tickets/${companyBTicket!.id}`);
  await expect(
    page.locator(".alert-error, .empty-state, .detail-not-found").first(),
  ).toBeVisible({ timeout: 10_000 });
});

test("Reports endpoint returns disjoint datasets for the two admins", async ({
  page,
  request,
}) => {
  // /api/reports/tickets-by-building/ is a good probe — its result is
  // one row per building visible to the caller, so a leak would show
  // up as a row with the other company's building name.
  await loginAs(page, DEMO_USERS.companyAdmin);
  const adminAToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  expect(adminAToken).toBeTruthy();
  const aReport = await request.get(
    "/api/reports/tickets-by-building/",
    { headers: { Authorization: `Bearer ${adminAToken}` } },
  );
  expect(aReport.ok()).toBe(true);
  const aBody = (await aReport.json()) as {
    results?: Array<{ building_name?: string }>;
  } | Array<{ building_name?: string }>;
  const aRows = Array.isArray(aBody) ? aBody : aBody.results ?? [];
  for (const row of aRows) {
    for (const b of COMPANY_B_BUILDINGS) {
      expect(row.building_name ?? "").not.toContain(b);
    }
  }

  // Swap to Company B admin and run the same probe.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.companyAdminB);
  const adminBToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  expect(adminBToken).toBeTruthy();
  const bReport = await request.get(
    "/api/reports/tickets-by-building/",
    { headers: { Authorization: `Bearer ${adminBToken}` } },
  );
  expect(bReport.ok()).toBe(true);
  const bBody = (await bReport.json()) as {
    results?: Array<{ building_name?: string }>;
  } | Array<{ building_name?: string }>;
  const bRows = Array.isArray(bBody) ? bBody : bBody.results ?? [];
  for (const row of bRows) {
    for (const b of COMPANY_A_BUILDINGS) {
      expect(row.building_name ?? "").not.toContain(b);
    }
  }
});

test("Admin companies list shows both for super admin, one for company admins", async ({
  page,
  request,
}) => {
  // Super admin sees both names in the /api/companies/ list.
  await loginAs(page, DEMO_USERS.super);
  const superToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  const superResp = await request.get("/api/companies/", {
    headers: { Authorization: `Bearer ${superToken}` },
  });
  expect(superResp.ok()).toBe(true);
  const superBody = (await superResp.json()) as {
    results?: Array<{ name: string }>;
  } | Array<{ name: string }>;
  const superRows = Array.isArray(superBody)
    ? superBody
    : superBody.results ?? [];
  const superNames = superRows.map((r) => r.name);
  expect(superNames).toContain(COMPANY_A_NAME);
  expect(superNames).toContain(COMPANY_B_NAME);

  // Company A admin sees only Company A.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.companyAdmin);
  const adminAToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  const aResp = await request.get("/api/companies/", {
    headers: { Authorization: `Bearer ${adminAToken}` },
  });
  expect(aResp.ok()).toBe(true);
  const aBody = (await aResp.json()) as {
    results?: Array<{ name: string }>;
  } | Array<{ name: string }>;
  const aRows = Array.isArray(aBody) ? aBody : aBody.results ?? [];
  const aNames = aRows.map((r) => r.name);
  expect(aNames).toContain(COMPANY_A_NAME);
  expect(aNames).not.toContain(COMPANY_B_NAME);

  // Company B admin sees only Company B.
  await page.locator(".topbar-right .btn").click();
  await loginAs(page, DEMO_USERS.companyAdminB);
  const adminBToken = await page.evaluate(() =>
    localStorage.getItem("accessToken"),
  );
  const bResp = await request.get("/api/companies/", {
    headers: { Authorization: `Bearer ${adminBToken}` },
  });
  expect(bResp.ok()).toBe(true);
  const bBody = (await bResp.json()) as {
    results?: Array<{ name: string }>;
  } | Array<{ name: string }>;
  const bRows = Array.isArray(bBody) ? bBody : bBody.results ?? [];
  const bNames = bRows.map((r) => r.name);
  expect(bNames).toContain(COMPANY_B_NAME);
  expect(bNames).not.toContain(COMPANY_A_NAME);
});
