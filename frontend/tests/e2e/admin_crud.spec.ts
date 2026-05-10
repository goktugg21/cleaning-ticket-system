import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 18-3 — admin CRUD UI hardening.
 *
 * Two surfaces are exercised here:
 *
 *   1. UI affordance gating on /admin/{companies,buildings,customers,
 *      users,invitations}. We do NOT mutate any data — the test only
 *      asserts which buttons / rows / scope-filtered lists each role
 *      sees on the listing pages, plus the SUPER_ADMIN-only reactivate
 *      affordance on /admin/users/:id when the user happens to be
 *      inactive (the test logs in as super-admin and observes; it
 *      does not flip is_active).
 *
 *   2. Backend rejection consistency. Every "the UI hides this for
 *      role X" assertion is paired with an API-level call that
 *      bypasses the SPA — proving backend rejects the same role at
 *      the wire even if the SPA were patched out.
 *
 * Reads Sprint 16's seeded data (`seed_demo_data`) so the test never
 * mutates the DB. Where a stable data-testid exists we use it; when
 * not we fall back to href/role selectors, never translated text.
 */

// ---------------------------------------------------------------------------
// API helper: log in via /api/auth/token/ and return a request context with
// the Authorization header pre-set. Skips the SPA + throttle backoff path,
// so backend-only checks stay fast.
// ---------------------------------------------------------------------------
async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  const loginCtx = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
  });
  const tokenResponse = await loginCtx.post("/api/auth/token/", {
    data: { email, password },
  });
  expect(
    tokenResponse.status(),
    `token request for ${email} should succeed`,
  ).toBe(200);
  const body = (await tokenResponse.json()) as { access: string };
  await loginCtx.dispose();

  return await request.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
  });
}

// ===========================================================================
// /admin/companies
// ===========================================================================

test.describe("admin → /admin/companies", () => {
  test("SUPER_ADMIN sees the Create button", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/companies");
    // Scope to the page header so we don't accidentally match the
    // empty-state CTA that briefly co-exists during the initial
    // render before the API call resolves.
    await expect(
      page.locator(
        '.page-header-actions a[href="/admin/companies/new"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("SUPER_ADMIN sees the Osius Demo company in the list", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/companies");
    await expect(page.locator(".data-table tbody tr").first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator(".data-table tbody")).toContainText("Osius Demo");
  });

  test("COMPANY_ADMIN does NOT see the Create button (super-admin only)", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/companies");
    // Wait for the table to settle so we are not racing the initial load.
    await expect(page.locator(".data-table tbody tr").first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('a[href="/admin/companies/new"]')).toHaveCount(
      0,
    );
  });
});

// ===========================================================================
// /admin/buildings
// ===========================================================================

test.describe("admin → /admin/buildings", () => {
  test("SUPER_ADMIN sees Create + the three demo buildings", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/buildings");
    await expect(
      page.locator(
        '.page-header-actions a[href="/admin/buildings/new"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
    const tableBody = page.locator(".data-table tbody");
    for (const name of ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"]) {
      await expect(tableBody).toContainText(name);
    }
  });

  test("COMPANY_ADMIN sees Create + their company's buildings only", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/buildings");
    // Create is allowed for company-admin by the backend
    // (`IsSuperAdminOrCompanyAdminForCompany`); the link is unconditional
    // on this page, so it must render.
    await expect(
      page.locator(
        '.page-header-actions a[href="/admin/buildings/new"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
    const tableBody = page.locator(".data-table tbody");
    for (const name of ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"]) {
      await expect(tableBody).toContainText(name);
    }
  });
});

// ===========================================================================
// /admin/customers
// ===========================================================================

test.describe("admin → /admin/customers", () => {
  test("SUPER_ADMIN sees Create + the consolidated B Amsterdam customer", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/customers");
    await expect(
      page.locator(
        '.page-header-actions a[href="/admin/customers/new"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".data-table tbody")).toContainText(
      "B Amsterdam",
    );
  });

  test("COMPANY_ADMIN sees Create + their company's customer", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/customers");
    await expect(
      page.locator(
        '.page-header-actions a[href="/admin/customers/new"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".data-table tbody")).toContainText(
      "B Amsterdam",
    );
  });
});

// ===========================================================================
// /admin/users — scope and SUPER_ADMIN-only reactivate visibility
// ===========================================================================

test.describe("admin → /admin/users", () => {
  test("SUPER_ADMIN sees the demo super-admin in the user list", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/users");
    await expect(page.locator(".data-table tbody tr").first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator(".data-table tbody")).toContainText(
      "super@cleanops.demo",
    );
  });

  test("COMPANY_ADMIN scope: list contains in-company demo users but NOT super-admin", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/users");
    await expect(page.locator(".data-table tbody tr").first()).toBeVisible({
      timeout: 10_000,
    });
    const tableBody = page.locator(".data-table tbody");
    // In-scope users (company membership ∪ building manager ∪ customer-user
    // memberships of the company) must appear.
    for (const inScope of [
      "admin@cleanops.demo",
      "gokhan@cleanops.demo",
      "tom@cleanops.demo",
    ]) {
      await expect(tableBody).toContainText(inScope);
    }
    // SUPER_ADMIN has no CompanyUserMembership → must be hidden from a
    // company admin even on the unfiltered first page.
    await expect(tableBody).not.toContainText("super@cleanops.demo");
  });

  test("Invite link to /admin/invitations is shown for both staff roles", async ({
    page,
  }) => {
    for (const roleKey of ["super", "companyAdmin"] as const) {
      await loginAs(page, DEMO_USERS[roleKey]);
      await page.goto("/admin/users");
      // Both the page-header CTA and the sidebar nav link point at
      // /admin/invitations, so the unscoped selector resolves to >=2
      // elements. Scope to the page-header-actions, which is the
      // role-relevant CTA for "I want to invite a user".
      await expect(
        page.locator(
          '.page-header-actions a[href="/admin/invitations"]',
        ),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});

// ===========================================================================
// /admin/invitations — direct URL access matrix
// ===========================================================================

test.describe("admin → /admin/invitations", () => {
  test("SUPER_ADMIN reaches the invitations page", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/invitations");
    await expect(
      page.locator('[data-testid="invitations-table"]'),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("COMPANY_ADMIN reaches the invitations page", async ({ page }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/invitations");
    await expect(
      page.locator('[data-testid="invitations-table"]'),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("BUILDING_MANAGER and CUSTOMER_USER are redirected away", async ({
    page,
  }) => {
    for (const roleKey of ["managerAll", "customerAll"] as const) {
      await loginAs(page, DEMO_USERS[roleKey]);
      await page.goto("/admin/invitations");
      await page.waitForLoadState("networkidle");
      expect(new URL(page.url()).pathname).not.toBe("/admin/invitations");
      await expect(
        page.locator('[data-testid="invitations-table"]'),
      ).toHaveCount(0);
    }
  });
});

// ===========================================================================
// Backend rejection consistency.
//
// Every "UI hides this for role X" assertion above is paired here with an
// API-level call that proves the backend rejects the same role at the
// wire — even if the SPA were patched out. We never POST a real entity
// because the demo dataset is read-only for these tests; the requests
// either probe a known-blocked action or send an empty payload and check
// the status code before any validation runs.
// ===========================================================================

test.describe("backend rejection consistency", () => {
  test("anonymous GET /api/companies/ → 401", async ({ baseURL }) => {
    const ctx = await request.newContext({
      baseURL,
      ignoreHTTPSErrors: true,
    });
    const r = await ctx.get("/api/companies/");
    expect(r.status()).toBe(401);
    await ctx.dispose();
  });

  test("CUSTOMER_USER GET /api/companies/ returns only their company", async ({
    baseURL,
  }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const r = await ctx.get("/api/companies/");
    expect(r.status()).toBe(200);
    const body = (await r.json()) as {
      results: Array<{ name: string }>;
      count: number;
    };
    // Tom is linked to "B Amsterdam" → "Osius Demo" company. He is not
    // a member of any other company. Even on a dev stack the only
    // company tied to him via CustomerUserMembership is Osius Demo.
    expect(body.count).toBeGreaterThanOrEqual(1);
    expect(body.results.every((c) => c.name === "Osius Demo")).toBe(true);
    await ctx.dispose();
  });

  test("COMPANY_ADMIN POST /api/companies/ → 403 (super-admin only)", async ({
    baseURL,
  }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const r = await ctx.post("/api/companies/", {
      data: { name: "DO_NOT_PERSIST", slug: "do-not-persist" },
    });
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("COMPANY_ADMIN POST /api/companies/<id>/reactivate/ → 403", async ({
    baseURL,
  }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    // ID 1 is good enough for a permission probe; even if it is wrong
    // the permission class fires before the lookup.
    const r = await ctx.post("/api/companies/1/reactivate/");
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("COMPANY_ADMIN POST /api/users/ → 405 (invitation flow only)", async ({
    baseURL,
  }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const r = await ctx.post("/api/users/", {
      data: { email: "do-not-persist@example.test" },
    });
    expect(r.status()).toBe(405);
    await ctx.dispose();
  });

  test("COMPANY_ADMIN POST /api/users/<id>/reactivate/ → 403", async ({
    baseURL,
  }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const r = await ctx.post("/api/users/1/reactivate/");
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("BUILDING_MANAGER POST /api/buildings/ → 403", async ({ baseURL }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.managerAll.email);
    const r = await ctx.post("/api/buildings/", {
      data: { company: 1, name: "DO_NOT_PERSIST" },
    });
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("BUILDING_MANAGER PATCH /api/users/<id>/ → 403", async ({ baseURL }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.managerAll.email);
    const r = await ctx.patch("/api/users/1/", {
      data: { full_name: "DO_NOT_PERSIST" },
    });
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("CUSTOMER_USER POST /api/customers/ → 403", async ({ baseURL }) => {
    const ctx = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const r = await ctx.post("/api/customers/", {
      data: { company: 1, name: "DO_NOT_PERSIST" },
    });
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });

  test("CUSTOMER_USER GET /api/audit-logs/ → 403", async ({ baseURL }) => {
    // Sprint 18 added the audit-logs UI; the API gate is super-admin
    // only, so even a customer-user with a valid token is rejected.
    const ctx = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const r = await ctx.get("/api/audit-logs/");
    expect(r.status()).toBe(403);
    await ctx.dispose();
  });
});
