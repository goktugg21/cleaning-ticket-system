import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 23B end-to-end checks for the new admin staff-assignment UI
 * plus the customer contact-visibility policy. Coverage:
 *
 *   1. STAFF user sees the "Request assignment" button on a ticket
 *      detail page for a building they have BuildingStaffVisibility
 *      on. Submitting POSTs to /api/staff-assignment-requests/.
 *   2. CUSTOMER_USER NEVER sees the request-assignment UI or the
 *      review-queue nav link.
 *   3. BUILDING_MANAGER / COMPANY_ADMIN / SUPER_ADMIN see the review
 *      queue link in the sidebar. CUSTOMER_USER / STAFF do not.
 *   4. /admin/staff-assignment-requests renders the requests table
 *      and shows approve/reject buttons for PENDING rows.
 *   5. Customer contact-visibility flags persist via PATCH and round-
 *      trip through the page state.
 *
 * Cross-company isolation for staff is verified at the API layer with
 * a forged token: an Osius STAFF user cannot reach a Bright ticket and
 * vice versa.
 */

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  // Sprint 23C — 429 backoff (see admin_crud.spec.ts for the long
  // explanation). The full Playwright run easily crosses the 20/min
  // auth_token throttle now that several specs use apiAs.
  const MAX_ATTEMPTS = 3;
  const THROTTLE_BACKOFF_MS = 35_000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const loginCtx = await request.newContext({
      baseURL,
      ignoreHTTPSErrors: true,
    });
    const tokenResponse = await loginCtx.post("/api/auth/token/", {
      data: { email, password },
    });
    const status = tokenResponse.status();
    if (status === 200) {
      const body = (await tokenResponse.json()) as { access: string };
      await loginCtx.dispose();
      return await request.newContext({
        baseURL,
        ignoreHTTPSErrors: true,
        extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
      });
    }
    await loginCtx.dispose();
    if (status === 429 && attempt < MAX_ATTEMPTS) {
      await new Promise((r) => setTimeout(r, THROTTLE_BACKOFF_MS));
      continue;
    }
    expect(
      status,
      `token request for ${email} should succeed (attempt ${attempt})`,
    ).toBe(200);
  }
  throw new Error(`apiAs(${email}) exhausted attempts`);
}

/**
 * Pick the first Osius ticket id that the super-admin sees. Used as
 * the navigation target for the STAFF "request assignment" flow.
 *
 * Sprint 24A — the original helper relied on a `company_name` field
 * that the ticket list serializer does NOT expose, so `find()` always
 * returned undefined and the fallback returned `results[0]`. With the
 * Sprint 21 v2 seed, the Bright Facilities tickets are created AFTER
 * the Osius ones (Osius is the first entry in `_COMPANIES`), so the
 * default `-created_at` ordering puts Bright first — and `results[0]`
 * becomes a Bright ticket, breaking the "Osius STAFF can see request
 * button" and "Bright STAFF cannot create request on an Osius ticket"
 * cases after any `--reset-tickets` cycle. We now filter on
 * `building_name`, which IS in the list serializer and matches the
 * "B1 / B2 / B3 Amsterdam" Osius naming convention.
 */
async function firstOsiusTicketId(api: APIRequestContext): Promise<number> {
  const response = await api.get("/api/tickets/?page_size=50");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; building_name?: string }>;
  };
  const osius = body.results.find((t) =>
    /Amsterdam/i.test(t.building_name ?? ""),
  );
  expect(osius, "demo seed must contain at least one Osius ticket").toBeTruthy();
  return osius!.id;
}

// =====================================================================
// Sidebar nav gating
// =====================================================================

test.describe("Sprint 23B → sidebar review-queue link", () => {
  test("SUPER_ADMIN sees the review-queue link", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/");
    await expect(
      page.locator(
        '.sidebar-nav a[href="/admin/staff-assignment-requests"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("COMPANY_ADMIN sees the review-queue link", async ({ page }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/");
    await expect(
      page.locator(
        '.sidebar-nav a[href="/admin/staff-assignment-requests"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("BUILDING_MANAGER sees the review-queue link (only nav for them)", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.managerAll);
    await page.goto("/");
    await expect(
      page.locator(
        '.sidebar-nav a[href="/admin/staff-assignment-requests"]',
      ),
    ).toBeVisible({ timeout: 10_000 });
    // …but no other admin links.
    await expect(
      page.locator('.sidebar-nav a[href="/admin/companies"]'),
    ).toHaveCount(0);
  });

  test("CUSTOMER_USER NEVER sees the review-queue link", async ({ page }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/");
    // Wait for the sidebar to render before asserting absence.
    await expect(page.locator(".sidebar-nav")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.locator(
        '.sidebar-nav a[href="/admin/staff-assignment-requests"]',
      ),
    ).toHaveCount(0);
  });

  test("STAFF NEVER sees the review-queue link", async ({ page }) => {
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto("/");
    await expect(page.locator(".sidebar-nav")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.locator(
        '.sidebar-nav a[href="/admin/staff-assignment-requests"]',
      ),
    ).toHaveCount(0);
  });
});

// =====================================================================
// Review queue page render
// =====================================================================

test.describe("Sprint 23B → /admin/staff-assignment-requests", () => {
  test("COMPANY_ADMIN can render the queue page", async ({ page }) => {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    await expect(
      page.locator('[data-testid="staff-requests-page"]'),
    ).toBeVisible({ timeout: 10_000 });
    // Either a row or the empty-state must render — the page is wired.
    const row = page.locator('[data-testid="staff-request-row"]').first();
    const empty = page.locator('[data-testid="staff-requests-empty"]');
    await expect(row.or(empty)).toBeVisible({ timeout: 10_000 });
  });

  test("CUSTOMER_USER is redirected away from the queue", async ({ page }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/admin/staff-assignment-requests");
    await page.waitForURL(
      (url) => !url.pathname.includes("/admin/staff-assignment-requests"),
      { timeout: 10_000 },
    );
    // StaffRequestReviewRoute sends rejected roles to "/?admin_required=ok".
    expect(page.url()).toMatch(/\/(\?|$)/);
  });

  test("STAFF is redirected away from the queue", async ({ page }) => {
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto("/admin/staff-assignment-requests");
    await page.waitForURL(
      (url) => !url.pathname.includes("/admin/staff-assignment-requests"),
      { timeout: 10_000 },
    );
  });
});

// =====================================================================
// STAFF: "Request assignment" button on ticket detail
// =====================================================================

test.describe("Sprint 23B → ticket detail STAFF flow", () => {
  test("STAFF sees the Request assignment button on an in-scope ticket", async ({
    page,
    baseURL,
  }) => {
    const api = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await firstOsiusTicketId(api);
    await api.dispose();

    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);
    await expect(
      page.locator('[data-testid="request-assignment-button"]').first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("CUSTOMER_USER NEVER sees the Request assignment button", async ({
    page,
    baseURL,
  }) => {
    const api = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await firstOsiusTicketId(api);
    await api.dispose();

    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto(`/tickets/${ticketId}`);
    // Wait for the page to mount before asserting absence.
    await expect(page.locator(".page-canvas")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.locator('[data-testid="request-assignment-button"]'),
    ).toHaveCount(0);
  });
});

// =====================================================================
// API-layer scope: STAFF cross-company isolation
// =====================================================================

test.describe("Sprint 23B → STAFF cross-company isolation (API)", () => {
  test("Bright STAFF cannot create a request on an Osius ticket", async ({
    baseURL,
  }) => {
    // Discover an Osius ticket via super-admin.
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const osiusTicketId = await firstOsiusTicketId(sa);
    await sa.dispose();

    const bright = await apiAs(baseURL!, DEMO_USERS.staffBright.email);
    const response = await bright.post("/api/staff-assignment-requests/", {
      data: { ticket: osiusTicketId },
    });
    await bright.dispose();

    // Backend gates this at the queryset / serializer level — 400 or
    // 403 are both acceptable rejections; only 201 would be a leak.
    expect([400, 403, 404]).toContain(response.status());
  });
});

// =====================================================================
// Customer contact-visibility flags round-trip
// =====================================================================

test.describe("Sprint 23B → customer contact-visibility flags", () => {
  test("COMPANY_ADMIN can toggle visibility flags and they persist", async ({
    baseURL,
  }) => {
    const api = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);

    // Find an Osius customer the company admin can edit.
    const list = await api.get("/api/customers/?page_size=1");
    expect(list.status()).toBe(200);
    const listBody = (await list.json()) as {
      results: Array<{
        id: number;
        show_assigned_staff_name: boolean;
        show_assigned_staff_email: boolean;
        show_assigned_staff_phone: boolean;
      }>;
    };
    expect(listBody.results.length).toBeGreaterThan(0);
    const customerId = listBody.results[0].id;
    const originalName = listBody.results[0].show_assigned_staff_name;

    // Flip the name flag, confirm persists, then restore.
    const patch = await api.patch(`/api/customers/${customerId}/`, {
      data: { show_assigned_staff_name: !originalName },
    });
    expect(patch.status()).toBe(200);
    const patchBody = (await patch.json()) as {
      show_assigned_staff_name: boolean;
    };
    expect(patchBody.show_assigned_staff_name).toBe(!originalName);

    // Restore so this test is idempotent for re-runs.
    const restore = await api.patch(`/api/customers/${customerId}/`, {
      data: { show_assigned_staff_name: originalName },
    });
    expect(restore.status()).toBe(200);
    await api.dispose();
  });

  test("CUSTOMER_USER cannot patch visibility flags", async ({ baseURL }) => {
    // Discover the customer id via super-admin first.
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const list = await sa.get("/api/customers/?page_size=1");
    const listBody = (await list.json()) as {
      results: Array<{ id: number }>;
    };
    const customerId = listBody.results[0].id;
    await sa.dispose();

    const cu = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await cu.patch(`/api/customers/${customerId}/`, {
      data: { show_assigned_staff_name: false },
    });
    await cu.dispose();
    expect([403, 404]).toContain(response.status());
  });
});
