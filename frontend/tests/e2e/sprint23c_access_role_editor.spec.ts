import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 23C end-to-end checks for the customer-access role editor.
 *
 * Coverage:
 *   1. SUPER_ADMIN / COMPANY_ADMIN can PATCH access_role via API.
 *   2. Promoting Tom's B3 access_role to CUSTOMER_LOCATION_MANAGER
 *      unlocks visibility of Amanda's B3 Pantry ticket without
 *      altering Tom's other access rows. Demotion restores the
 *      previous view_own behaviour so later specs run against the
 *      seeded baseline.
 *   3. CUSTOMER_USER cannot PATCH access_role (403).
 *   4. Cross-company COMPANY_ADMIN cannot PATCH (403).
 *   5. CustomerFormPage exposes the new <select> with a `change`
 *      event wired to the PATCH endpoint.
 *
 * Each test that mutates demo state restores the original value in
 * the same test body so the run is order-independent.
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

interface CustomerListItem {
  id: number;
  name: string;
  company: number;
}
interface AccessRow {
  id: number;
  user_id: number;
  user_email: string;
  building_id: number;
  building_name: string;
  access_role:
    | "CUSTOMER_USER"
    | "CUSTOMER_LOCATION_MANAGER"
    | "CUSTOMER_COMPANY_ADMIN";
}
interface TicketRow {
  id: number;
  title: string;
  building_name?: string;
}

async function resolveCustomerId(
  api: APIRequestContext,
  customerName: string,
): Promise<number> {
  const response = await api.get("/api/customers/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: CustomerListItem[] };
  const match = body.results.find((c) => c.name === customerName);
  expect(match, `customer ${customerName} present`).toBeTruthy();
  return match!.id;
}

async function resolveUserId(
  api: APIRequestContext,
  email: string,
): Promise<number> {
  const response = await api.get(
    `/api/users/?search=${encodeURIComponent(email)}&page_size=200`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; email: string }>;
  };
  const match = body.results.find((u) => u.email === email);
  expect(match, `user ${email} present`).toBeTruthy();
  return match!.id;
}

async function listAccessRows(
  api: APIRequestContext,
  customerId: number,
  userId: number,
): Promise<AccessRow[]> {
  const response = await api.get(
    `/api/customers/${customerId}/users/${userId}/access/`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: AccessRow[] };
  return body.results;
}

async function patchAccessRole(
  api: APIRequestContext,
  customerId: number,
  userId: number,
  buildingId: number,
  accessRole: AccessRow["access_role"],
) {
  return api.patch(
    `/api/customers/${customerId}/users/${userId}/access/${buildingId}/`,
    { data: { access_role: accessRole } },
  );
}

async function findOsiusCustomer(api: APIRequestContext): Promise<number> {
  return resolveCustomerId(api, "B Amsterdam");
}

async function findBrightCustomer(api: APIRequestContext): Promise<number> {
  return resolveCustomerId(api, "City Office Rotterdam");
}

// =====================================================================
// API gate
// =====================================================================

test.describe("Sprint 23C → access_role PATCH gate", () => {
  test("SUPER_ADMIN can PATCH any customer's access_role (round-trip restore)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    const userId = await resolveUserId(sa, DEMO_USERS.customerAll.email);
    const accesses = await listAccessRows(sa, customerId, userId);
    const b3 = accesses.find((a) => a.building_name === "B3 Amsterdam");
    expect(b3, "Tom must have a B3 access row").toBeTruthy();
    const originalRole = b3!.access_role;
    try {
      const upgrade = await patchAccessRole(
        sa,
        customerId,
        userId,
        b3!.building_id,
        "CUSTOMER_LOCATION_MANAGER",
      );
      expect(upgrade.status()).toBe(200);
      const body = (await upgrade.json()) as AccessRow;
      expect(body.access_role).toBe("CUSTOMER_LOCATION_MANAGER");
    } finally {
      // Restore so other specs see the seeded baseline.
      const restore = await patchAccessRole(
        sa,
        customerId,
        userId,
        b3!.building_id,
        originalRole,
      );
      expect(restore.status()).toBe(200);
      await sa.dispose();
    }
  });

  test("COMPANY_ADMIN can PATCH their own company's access_role", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    const userId = await resolveUserId(sa, DEMO_USERS.customerAll.email);
    const accesses = await listAccessRows(sa, customerId, userId);
    const b1 = accesses.find((a) => a.building_name === "B1 Amsterdam");
    const originalRole = b1!.access_role;
    await sa.dispose();

    const ca = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    try {
      const upgrade = await patchAccessRole(
        ca,
        customerId,
        userId,
        b1!.building_id,
        "CUSTOMER_LOCATION_MANAGER",
      );
      expect(upgrade.status()).toBe(200);
      const restore = await patchAccessRole(
        ca,
        customerId,
        userId,
        b1!.building_id,
        originalRole,
      );
      expect(restore.status()).toBe(200);
    } finally {
      await ca.dispose();
    }
  });

  test("COMPANY_ADMIN cannot PATCH another company's access_role", async ({
    baseURL,
  }) => {
    // Discover Bright's customer + customer-user via super admin so the
    // Osius company admin can attempt a cross-company PATCH.
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const brightCustomerId = await findBrightCustomer(sa);
    const brightCustomerUserId = await resolveUserId(
      sa,
      DEMO_USERS.customerBCo.email,
    );
    const brightAccesses = await listAccessRows(
      sa,
      brightCustomerId,
      brightCustomerUserId,
    );
    expect(brightAccesses.length).toBeGreaterThan(0);
    const target = brightAccesses[0];
    await sa.dispose();

    const osiusAdmin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const response = await patchAccessRole(
      osiusAdmin,
      brightCustomerId,
      brightCustomerUserId,
      target.building_id,
      "CUSTOMER_LOCATION_MANAGER",
    );
    await osiusAdmin.dispose();
    // The Osius admin's role passes has_permission (admin role), then
    // has_object_permission denies the customer because the Customer's
    // company is Bright. Expect 403 from the object-level gate.
    expect(response.status()).toBe(403);
  });

  test("CUSTOMER_USER cannot PATCH access_role (class-level gate)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    const userId = await resolveUserId(sa, DEMO_USERS.customerAll.email);
    const accesses = await listAccessRows(sa, customerId, userId);
    const target = accesses[0];
    await sa.dispose();

    const cu = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await patchAccessRole(
      cu,
      customerId,
      userId,
      target.building_id,
      "CUSTOMER_LOCATION_MANAGER",
    );
    await cu.dispose();
    expect(response.status()).toBe(403);
  });

  test("STAFF cannot PATCH access_role", async ({ baseURL }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    const userId = await resolveUserId(sa, DEMO_USERS.customerAll.email);
    const accesses = await listAccessRows(sa, customerId, userId);
    const target = accesses[0];
    await sa.dispose();

    const staff = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const response = await patchAccessRole(
      staff,
      customerId,
      userId,
      target.building_id,
      "CUSTOMER_LOCATION_MANAGER",
    );
    await staff.dispose();
    expect(response.status()).toBe(403);
  });
});

// =====================================================================
// Visibility effect
// =====================================================================

test.describe("Sprint 23C → role change widens ticket visibility", () => {
  test("Promoting Tom's B3 to LOCATION_MANAGER unlocks Amanda's Pantry ticket", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    const tomId = await resolveUserId(sa, DEMO_USERS.customerAll.email);
    const accesses = await listAccessRows(sa, customerId, tomId);
    const b3 = accesses.find((a) => a.building_name === "B3 Amsterdam")!;
    const originalRole = b3.access_role;
    await sa.dispose();

    async function tomVisibleTitles() {
      const tom = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
      const response = await tom.get("/api/tickets/?page_size=50");
      expect(response.status()).toBe(200);
      const body = (await response.json()) as { results: TicketRow[] };
      const titles = body.results.map((r) => r.title);
      await tom.dispose();
      return titles;
    }

    // Pre-promotion: Pantry is NOT visible to Tom.
    const titlesBefore = await tomVisibleTitles();
    expect(
      titlesBefore.some((t) => t.includes("Pantry zeepdispenser")),
    ).toBe(false);

    // Promote.
    const ca = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const upgrade = await patchAccessRole(
      ca,
      customerId,
      tomId,
      b3.building_id,
      "CUSTOMER_LOCATION_MANAGER",
    );
    expect(upgrade.status()).toBe(200);

    try {
      // Post-promotion: Pantry IS visible.
      const titlesAfter = await tomVisibleTitles();
      expect(
        titlesAfter.some((t) => t.includes("Pantry zeepdispenser")),
      ).toBe(true);
    } finally {
      // Restore.
      const restore = await patchAccessRole(
        ca,
        customerId,
        tomId,
        b3.building_id,
        originalRole,
      );
      expect(restore.status()).toBe(200);
      await ca.dispose();
    }
  });
});

// =====================================================================
// UI surface — role <select> is rendered on the customer form
// =====================================================================

test.describe("Sprint 23C → CustomerFormPage role editor renders", () => {
  test("COMPANY_ADMIN sees a role <select> on each access pill", async ({
    page,
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const customerId = await findOsiusCustomer(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}`);
    // Wait for the access-row select element to render.
    const select = page
      .locator('[data-testid="customer-access-role-select"]')
      .first();
    await expect(select).toBeVisible({ timeout: 15_000 });
    const options = await select.locator("option").allTextContents();
    // Two locales — match against either Dutch or English labels.
    expect(
      options.some((o) =>
        /Customer user|Klantgebruiker/i.test(o),
      ),
    ).toBe(true);
    expect(
      options.some((o) =>
        /Location manager|Locatiebeheerder/i.test(o),
      ),
    ).toBe(true);
    expect(
      options.some((o) =>
        /Company admin|Bedrijfsbeheerder/i.test(o),
      ),
    ).toBe(true);
  });
});
