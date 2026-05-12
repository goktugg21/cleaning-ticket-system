import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 24A — admin write surface for StaffProfile +
 * BuildingStaffVisibility.
 *
 * Coverage:
 *   1. SUPER_ADMIN / COMPANY_ADMIN can PATCH a STAFF profile and
 *      list / mutate that staff member's BuildingStaffVisibility
 *      rows via API. Each mutation restores the seeded state in the
 *      same test body so later specs see the canonical baseline.
 *   2. Cross-company isolation — Osius COMPANY_ADMIN cannot reach
 *      Bright's STAFF; the request fails with 403.
 *   3. STAFF cannot patch their own visibility (class-level role
 *      gate returns 403).
 *   4. COMPANY_ADMIN opening a STAFF user edit page sees the new
 *      `Staff details` section + the building visibility editor.
 *   5. Mobile viewport 430x932 on the same page renders without a
 *      horizontal body scroll (Sprint 22 invariant).
 *   6. No raw i18n keys (`staff_admin.*`) leak into the rendered
 *      page — every key must resolve to a translation.
 */

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  // Sprint 23C — 429 backoff. Same shape as the existing spec helpers
  // so a full Playwright run that crosses the 20/min auth_token
  // throttle still completes deterministically.
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

interface StaffProfileBody {
  id: number;
  user_id: number;
  user_email: string;
  phone: string;
  internal_note: string;
  can_request_assignment: boolean;
  is_active: boolean;
}
interface VisibilityBody {
  id: number;
  user_id: number;
  building_id: number;
  building_name: string;
  can_request_assignment: boolean;
}
interface BuildingListItem {
  id: number;
  name: string;
  company: number;
  is_active: boolean;
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

async function listVisibility(
  api: APIRequestContext,
  userId: number,
): Promise<VisibilityBody[]> {
  const response = await api.get(`/api/users/${userId}/staff-visibility/`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: VisibilityBody[] };
  return body.results;
}

async function findBuildingByName(
  api: APIRequestContext,
  name: string,
): Promise<BuildingListItem> {
  const response = await api.get("/api/buildings/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: BuildingListItem[] };
  const match = body.results.find((b) => b.name === name);
  expect(match, `building ${name} present`).toBeTruthy();
  return match!;
}

// =====================================================================
// API gate — StaffProfile PATCH
// =====================================================================

test.describe("Sprint 24A → StaffProfile PATCH gate", () => {
  test("SUPER_ADMIN can PATCH a STAFF profile (round-trip restore)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    try {
      const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
      const before = await sa.get(`/api/users/${staffId}/staff-profile/`);
      expect(before.status()).toBe(200);
      const original = (await before.json()) as StaffProfileBody;
      const newPhone = "+31 6 0000 0001";

      const update = await sa.patch(
        `/api/users/${staffId}/staff-profile/`,
        { data: { phone: newPhone } },
      );
      expect(update.status()).toBe(200);
      const updated = (await update.json()) as StaffProfileBody;
      expect(updated.phone).toBe(newPhone);

      // Restore so other specs see the seeded baseline.
      const restore = await sa.patch(
        `/api/users/${staffId}/staff-profile/`,
        { data: { phone: original.phone } },
      );
      expect(restore.status()).toBe(200);
    } finally {
      await sa.dispose();
    }
  });

  test("COMPANY_ADMIN can PATCH own-company STAFF profile", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    const before = (await (
      await sa.get(`/api/users/${staffId}/staff-profile/`)
    ).json()) as StaffProfileBody;
    await sa.dispose();

    const ca = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    try {
      const update = await ca.patch(
        `/api/users/${staffId}/staff-profile/`,
        {
          data: {
            internal_note: "Sprint 24A — owns evening shift.",
          },
        },
      );
      expect(update.status()).toBe(200);
      const body = (await update.json()) as StaffProfileBody;
      expect(body.internal_note).toBe("Sprint 24A — owns evening shift.");

      // Restore.
      const restore = await ca.patch(
        `/api/users/${staffId}/staff-profile/`,
        { data: { internal_note: before.internal_note } },
      );
      expect(restore.status()).toBe(200);
    } finally {
      await ca.dispose();
    }
  });

  test("COMPANY_ADMIN cannot PATCH cross-company STAFF profile", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const brightStaffId = await resolveUserId(
      sa,
      DEMO_USERS.staffBright.email,
    );
    await sa.dispose();

    const osiusAdmin = await apiAs(
      baseURL!,
      DEMO_USERS.companyAdmin.email,
    );
    const response = await osiusAdmin.patch(
      `/api/users/${brightStaffId}/staff-profile/`,
      { data: { phone: "stolen" } },
    );
    await osiusAdmin.dispose();
    expect(response.status()).toBe(403);
  });

  test("CUSTOMER_USER cannot PATCH a STAFF profile (class-level gate)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const cu = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await cu.patch(
      `/api/users/${staffId}/staff-profile/`,
      { data: { phone: "should-fail" } },
    );
    await cu.dispose();
    expect(response.status()).toBe(403);
  });

  test("STAFF cannot PATCH their own profile", async ({ baseURL }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const staff = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const response = await staff.patch(
      `/api/users/${staffId}/staff-profile/`,
      { data: { phone: "self-edit-attempt" } },
    );
    await staff.dispose();
    expect(response.status()).toBe(403);
  });
});

// =====================================================================
// API gate — BuildingStaffVisibility list / add / remove
// =====================================================================

test.describe("Sprint 24A → BuildingStaffVisibility CRUD gate", () => {
  test("COMPANY_ADMIN can add and remove visibility for own-company STAFF (round-trip restore)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    const seeded = await listVisibility(sa, staffId);
    // Ahmet is seeded with B1, B2, B3 — pick B1 to round-trip on.
    const target = seeded.find((v) => v.building_name === "B1 Amsterdam");
    expect(target, "Ahmet must have a B1 visibility row").toBeTruthy();
    await sa.dispose();

    const ca = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    try {
      // Remove and re-add (restore) so the seeded state survives the
      // test. The restore POST returns 201 on the new row.
      const remove = await ca.delete(
        `/api/users/${staffId}/staff-visibility/${target!.building_id}/`,
      );
      expect(remove.status()).toBe(204);

      const after = await listVisibility(ca, staffId);
      expect(
        after.some((v) => v.building_id === target!.building_id),
      ).toBe(false);

      const restore = await ca.post(
        `/api/users/${staffId}/staff-visibility/`,
        { data: { building_id: target!.building_id } },
      );
      expect(restore.status()).toBe(201);
      const restored = await listVisibility(ca, staffId);
      expect(
        restored.some((v) => v.building_id === target!.building_id),
      ).toBe(true);
    } finally {
      await ca.dispose();
    }
  });

  test("COMPANY_ADMIN cannot assign a building from another company", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ahmetId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    const rotterdamBuilding = await findBuildingByName(sa, "R1 Rotterdam");
    await sa.dispose();

    const osiusAdmin = await apiAs(
      baseURL!,
      DEMO_USERS.companyAdmin.email,
    );
    const response = await osiusAdmin.post(
      `/api/users/${ahmetId}/staff-visibility/`,
      { data: { building_id: rotterdamBuilding.id } },
    );
    await osiusAdmin.dispose();
    // Backend rejects with 400 because the building lives in another
    // company; the same-company guard fires before the row is created.
    expect(response.status()).toBe(400);
  });

  test("Osius COMPANY_ADMIN cannot touch Bright STAFF visibility", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const noahId = await resolveUserId(sa, DEMO_USERS.staffBright.email);
    await sa.dispose();

    const osiusAdmin = await apiAs(
      baseURL!,
      DEMO_USERS.companyAdmin.email,
    );
    const list = await osiusAdmin.get(
      `/api/users/${noahId}/staff-visibility/`,
    );
    expect(list.status()).toBe(403);

    // Also block PATCH and DELETE on whatever (user, building) pair
    // Bright happens to have.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const noahVisibility = await listVisibility(sa2, noahId);
    await sa2.dispose();
    expect(noahVisibility.length).toBeGreaterThan(0);
    const patch = await osiusAdmin.patch(
      `/api/users/${noahId}/staff-visibility/${noahVisibility[0].building_id}/`,
      { data: { can_request_assignment: false } },
    );
    expect(patch.status()).toBe(403);
    const remove = await osiusAdmin.delete(
      `/api/users/${noahId}/staff-visibility/${noahVisibility[0].building_id}/`,
    );
    expect(remove.status()).toBe(403);
    await osiusAdmin.dispose();
  });

  test("STAFF cannot patch their own visibility (class-level gate)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ahmetId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    const visibility = await listVisibility(sa, ahmetId);
    await sa.dispose();
    expect(visibility.length).toBeGreaterThan(0);
    const buildingId = visibility[0].building_id;

    const staff = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const patch = await staff.patch(
      `/api/users/${ahmetId}/staff-visibility/${buildingId}/`,
      { data: { can_request_assignment: false } },
    );
    const remove = await staff.delete(
      `/api/users/${ahmetId}/staff-visibility/${buildingId}/`,
    );
    await staff.dispose();
    expect(patch.status()).toBe(403);
    expect(remove.status()).toBe(403);
  });
});

// =====================================================================
// UI surface — UserFormPage exposes the Sprint 24A editor for STAFF
// =====================================================================

test.describe("Sprint 24A → UserFormPage Staff details UI", () => {
  test("COMPANY_ADMIN sees Staff details and visibility editor for own-company STAFF", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/users/${staffId}`);
    await expect(
      page.locator('[data-testid="staff-details-section"]'),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator('[data-testid="staff-profile-form"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="staff-phone-input"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="staff-visibility-section"]'),
    ).toBeVisible();
    // At least one seeded visibility row should be present (Ahmet has
    // B1 / B2 / B3 from the seed). At desktop width this is a table
    // row; the mobile parallel <li> is also emitted but hidden.
    await expect(
      page
        .locator('[data-testid="staff-visibility-row"]')
        .first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("COMPANY_ADMIN can toggle and revert a visibility row's can_request flag from the UI", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    // Discover the B1 row id ahead of time so we can drive the
    // checkbox toggle deterministically. The UI lists rows ordered by
    // building name, so B1 is the first row.
    const seeded = await listVisibility(sa, staffId);
    const b1 = seeded.find((v) => v.building_name === "B1 Amsterdam")!;
    const originalCanRequest = b1.can_request_assignment;
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/users/${staffId}`);
    const row = page
      .locator('[data-testid="staff-visibility-row"]')
      .filter({ hasText: "B1 Amsterdam" })
      .first();
    await expect(row).toBeVisible({ timeout: 15_000 });
    const checkbox = row.locator(
      '[data-testid="staff-visibility-can-request"]',
    );
    await expect(checkbox).toBeVisible();
    await expect(checkbox).toBeChecked({ checked: originalCanRequest });

    // Flip via the UI and wait for the PATCH to round-trip.
    const patchPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/users/${staffId}/staff-visibility/`) &&
        r.request().method() === "PATCH",
      { timeout: 10_000 },
    );
    await checkbox.click();
    const patchResponse = await patchPromise;
    expect(patchResponse.status()).toBe(200);

    // Restore via API so the seed state survives for later specs.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const restore = await sa2.patch(
      `/api/users/${staffId}/staff-visibility/${b1.building_id}/`,
      { data: { can_request_assignment: originalCanRequest } },
    );
    expect(restore.status()).toBe(200);
    await sa2.dispose();
  });

  test("No raw `staff_admin.*` i18n keys leak on the UserFormPage for a STAFF user", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/users/${staffId}`);
    await expect(
      page.locator('[data-testid="staff-details-section"]'),
    ).toBeVisible({ timeout: 15_000 });

    const bodyText = (await page.locator("body").textContent()) ?? "";
    // Each key should resolve to a translation; the raw key literal
    // must not appear anywhere on the page.
    const RAW_KEYS = [
      "staff_admin.profile_title",
      "staff_admin.profile_desc",
      "staff_admin.field_phone",
      "staff_admin.field_internal_note",
      "staff_admin.field_can_request_assignment",
      "staff_admin.field_is_active",
      "staff_admin.visibility_title",
      "staff_admin.visibility_desc",
      "staff_admin.visibility_add",
      "staff_admin.visibility_can_request_label",
      "staff_admin.visibility_remove_button",
    ];
    for (const key of RAW_KEYS) {
      expect(
        bodyText.includes(key),
        `Raw i18n key "${key}" leaked into rendered text — check src/i18n/{en,nl}/common.json`,
      ).toBe(false);
    }
  });
});

// =====================================================================
// Mobile invariant — no horizontal body overflow at 430x932
// =====================================================================

test("UserFormPage Staff details: no horizontal body overflow at 430x932", async ({
  baseURL,
  page,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
  await sa.dispose();

  await page.setViewportSize({ width: 430, height: 932 });
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/users/${staffId}`);
  await expect(
    page.locator('[data-testid="staff-details-section"]'),
  ).toBeVisible({ timeout: 15_000 });

  // The mobile card list must be attached at this viewport (CSS media
  // query swaps the desktop table for the card list at <=600px).
  await expect(
    page.locator('[data-testid="staff-visibility-card-list"]'),
  ).toBeAttached({ timeout: 10_000 });

  // Sprint 22 invariant: body scrollWidth must not exceed the viewport
  // width (with the same +1 rounding tolerance every Sprint 23C
  // hardening test uses).
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(scrollWidth).toBeLessThanOrEqual(430 + 1);
});
