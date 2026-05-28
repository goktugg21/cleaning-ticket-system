import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.6 — Users view-first.
 *
 * `/admin/users/:id` no longer mounts the form; it renders the new
 * read-only `UserDetailPage`. An explicit, role-gated Edit button
 * navigates to `/admin/users/:id/edit`, which still mounts the
 * `UserFormPage`. Cancel on the edit page returns to detail without
 * saving.
 *
 * This is the fourth instance of the 29.3 (Companies) / 29.4
 * (Buildings) pattern. Test footprint mirrors 29.4 verbatim swapping
 * URLs and entity names:
 *   1. Detail page renders with the locked read-only testids and the
 *      form-only fingerprints are absent.
 *   2. SUPER_ADMIN sees the Edit button and it routes to .../edit
 *      with the form (including the memberships read-out) mounted.
 *   3. Cancel on the edit form returns to detail without persisting
 *      the typed-over full_name.
 *   4. A COMPANY_ADMIN does NOT see the Edit / lifecycle affordances
 *      on a SUPER_ADMIN user (mirrors UserFormPage L118–119 role-
 *      gating).
 */
async function resolveUserIdByEmail(
  api: APIRequestContext,
  email: string,
): Promise<number> {
  const response = await api.get(
    `/api/users/?search=${encodeURIComponent(email)}&page_size=50`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; email: string }>;
  };
  const match = body.results.find((row) => row.email === email);
  expect(match, `demo seed has user with email "${email}"`).toBeTruthy();
  return match!.id;
}

test.describe("Sprint 29 Batch 29.6 — Users view-first", () => {
  test("detail page renders read-only with the locked testids", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    // Use a non-super-admin demo user so this test also exercises
    // the membership card path (the SA spans both companies). Tom is
    // CUSTOMER_USER with non-empty customer_ids so the Customer
    // access card also renders here as a bonus assertion.
    const userId = await resolveUserIdByEmail(sa, DEMO_USERS.customerAll.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/users/${userId}`);

    // The detail page wrapper.
    await expect(
      page.locator('[data-testid="user-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Read-only cards (memberships + customer access render because
    // Tom is a CUSTOMER_USER with a non-empty customer_ids array).
    await expect(
      page.locator('[data-testid="user-detail-about-card"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="user-detail-memberships-card"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="user-detail-customer-access-card"]'),
    ).toBeVisible();

    // The form must NOT be on this URL. The form's `#user-full-name`
    // input and the form-specific `form-actions` Save button are its
    // fingerprints; neither should appear on the read-only detail
    // page.
    await expect(page.locator("input#user-full-name")).toHaveCount(0);
    await expect(page.locator("input#user-email")).toHaveCount(0);
  });

  test("super admin sees Edit and it routes to /edit", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const userId = await resolveUserIdByEmail(sa, DEMO_USERS.customerAll.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/users/${userId}`);

    const editLink = page.locator('[data-testid="user-edit-link"]');
    await expect(editLink).toBeVisible({ timeout: 10_000 });

    const href = await editLink.getAttribute("href");
    expect(href).toBe(`/admin/users/${userId}/edit`);

    await editLink.click();
    await page.waitForURL((url) =>
      url.pathname === `/admin/users/${userId}/edit`,
    );

    // The form must mount at /edit — the full-name input is the
    // edit-only fingerprint.
    await expect(page.locator("input#user-full-name")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("Cancel discards the edit and returns to detail", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const userId = await resolveUserIdByEmail(sa, DEMO_USERS.customerAll.email);

    // Capture the canonical full_name from the API so we can prove
    // the Cancel flow did NOT persist the typed-over value.
    const fetched = await sa.get(`/api/users/${userId}/`);
    expect(fetched.status()).toBe(200);
    const original = (await fetched.json()) as { full_name: string };
    await sa.dispose();
    const originalName = original.full_name;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/users/${userId}/edit`);

    const nameInput = page.locator("input#user-full-name");
    await expect(nameInput).toBeVisible({ timeout: 10_000 });
    await nameInput.fill(`${originalName} ___DIRTY___`);

    const cancel = page.locator('[data-testid="user-edit-cancel"]');
    await expect(cancel).toBeVisible();
    await cancel.click();

    await page.waitForURL((url) =>
      url.pathname === `/admin/users/${userId}`,
    );
    await expect(
      page.locator('[data-testid="user-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Re-fetch via the API to prove the original name is intact, and
    // round-trip back to the edit form to confirm the input value
    // reflects server state (not the typed-over value).
    const sa2 = await apiAs(DEMO_USERS.super.email);
    const refetched = await sa2.get(`/api/users/${userId}/`);
    expect(refetched.status()).toBe(200);
    const refetchedBody = (await refetched.json()) as { full_name: string };
    expect(refetchedBody.full_name).toBe(originalName);
    await sa2.dispose();

    await page.goto(`/admin/users/${userId}/edit`);
    await expect(page.locator("input#user-full-name")).toHaveValue(
      originalName,
      { timeout: 10_000 },
    );
  });

  test("COMPANY_ADMIN does not see Edit on a SUPER_ADMIN user", async ({
    page,
  }) => {
    // COMPANY_ADMIN (Sophie of Company B) viewing the SUPER_ADMIN
    // user's detail page. The route guard (`AdminRoute`) admits any
    // COMPANY_ADMIN, so the detail page should mount. But the
    // in-page `canEdit` gate must reject — COMPANY_ADMIN cannot
    // manage SUPER_ADMIN-role users (mirrors UserFormPage L118–119
    // and the backend's role-management guard). Lifecycle actions
    // are SUPER_ADMIN-only, so those affordances must also be
    // absent.
    const sa = await apiAs(DEMO_USERS.super.email);
    const superAdminId = await resolveUserIdByEmail(sa, DEMO_USERS.super.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdminB);
    await page.goto(`/admin/users/${superAdminId}`);

    // The detail page must mount (cross-role read access for any
    // user record is admitted by the backend list endpoint; the
    // detail page itself does not require edit rights).
    await expect(
      page.locator('[data-testid="user-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // The role-gated affordances must be absent: this admin cannot
    // manage a SUPER_ADMIN target.
    await expect(
      page.locator('[data-testid="user-edit-link"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="deactivate-button"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="reactivate-button"]'),
    ).toHaveCount(0);
  });
});
