import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { COMPANY_A_NAME, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.4 — Buildings view-first.
 *
 * `/admin/buildings/:id` no longer mounts the form; it renders the
 * new read-only `BuildingDetailPage`. An explicit, role-gated Edit
 * button navigates to `/admin/buildings/:id/edit`, which still mounts
 * the `BuildingFormPage`. Cancel on the edit page returns to detail
 * without saving.
 *
 * This is the second instance of the 29.3 (Companies) pattern. Test
 * footprint mirrors 29.3 verbatim swapping URLs and entity names:
 *   1. Detail page renders with the locked read-only testids and the
 *      form-only fingerprints are absent.
 *   2. SUPER_ADMIN sees the Edit button and it routes to .../edit
 *      with the form (including the `section-managers` card)
 *      mounted.
 *   3. Cancel on the edit form returns to detail without persisting
 *      the typed-over value.
 *   4. A COMPANY_ADMIN of a different company sees no Edit /
 *      lifecycle affordances on a building they don't belong to.
 */
async function resolveCompanyIdByName(
  api: APIRequestContext,
  name: string,
): Promise<number> {
  const response = await api.get("/api/companies/?page_size=50");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match = body.results.find((row) => row.name === name);
  expect(match, `demo seed has company named "${name}"`).toBeTruthy();
  return match!.id;
}

async function resolveBuildingForCompany(
  api: APIRequestContext,
  companyId: number,
): Promise<{ id: number; name: string; company: number }> {
  const response = await api.get("/api/buildings/?page_size=50");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string; company: number }>;
  };
  const match = body.results.find((row) => row.company === companyId);
  expect(
    match,
    `demo seed has at least one building under company id=${companyId}`,
  ).toBeTruthy();
  return match!;
}

test.describe("Sprint 29 Batch 29.4 — Buildings view-first", () => {
  test("detail page renders read-only with the locked testids", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    const building = await resolveBuildingForCompany(sa, companyId);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/buildings/${building.id}`);

    // The detail page wrapper.
    await expect(
      page.locator('[data-testid="building-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Both read-only cards.
    await expect(
      page.locator('[data-testid="building-detail-about-card"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="building-detail-managers-card"]'),
    ).toBeVisible();

    // The form must NOT be on this URL. The form's `section-managers`
    // card and the building-name input are its fingerprints; neither
    // should appear on the read-only detail page.
    await expect(page.locator('[data-testid="section-managers"]'))
      .toHaveCount(0);
    await expect(page.locator("input#building-name")).toHaveCount(0);
  });

  test("super admin sees Edit and it routes to /edit", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    const building = await resolveBuildingForCompany(sa, companyId);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/buildings/${building.id}`);

    const editLink = page.locator('[data-testid="building-edit-link"]');
    await expect(editLink).toBeVisible({ timeout: 10_000 });

    const href = await editLink.getAttribute("href");
    expect(href).toBe(`/admin/buildings/${building.id}/edit`);

    await editLink.click();
    await page.waitForURL((url) =>
      url.pathname === `/admin/buildings/${building.id}/edit`,
    );

    // The form (including the managers section) must mount at /edit.
    await expect(page.locator("input#building-name")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.locator('[data-testid="section-managers"]'),
    ).toBeVisible();
  });

  test("Cancel discards the edit and returns to detail", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    const building = await resolveBuildingForCompany(sa, companyId);

    // Capture the canonical name from the API so we can prove the
    // Cancel flow did NOT persist the typed-over value.
    const fetched = await sa.get(`/api/buildings/${building.id}/`);
    expect(fetched.status()).toBe(200);
    const original = (await fetched.json()) as { name: string };
    await sa.dispose();
    const originalName = original.name;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/buildings/${building.id}/edit`);

    const nameInput = page.locator("input#building-name");
    await expect(nameInput).toBeVisible({ timeout: 10_000 });
    await nameInput.fill(`${originalName} ___DIRTY___`);

    const cancel = page.locator('[data-testid="building-edit-cancel"]');
    await expect(cancel).toBeVisible();
    await cancel.click();

    await page.waitForURL((url) =>
      url.pathname === `/admin/buildings/${building.id}`,
    );
    await expect(
      page.locator('[data-testid="building-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Re-fetch via the API to prove the original name is intact, and
    // round-trip back to the edit form to confirm the input value
    // reflects server state (not the typed-over value).
    const sa2 = await apiAs(DEMO_USERS.super.email);
    const refetched = await sa2.get(`/api/buildings/${building.id}/`);
    expect(refetched.status()).toBe(200);
    const refetchedBody = (await refetched.json()) as { name: string };
    expect(refetchedBody.name).toBe(originalName);
    await sa2.dispose();

    await page.goto(`/admin/buildings/${building.id}/edit`);
    await expect(page.locator("input#building-name")).toHaveValue(
      originalName,
      { timeout: 10_000 },
    );
  });

  test("an admin of a different company does not see the Edit button", async ({
    page,
  }) => {
    // COMPANY_ADMIN of Company B (Bright Facilities) viewing a
    // building in Company A (Osius Demo). The route guard
    // (`AdminRoute`) admits any SUPER_ADMIN or COMPANY_ADMIN — but
    // the in-page `canEdit` gate requires the admin to be a member of
    // the building's company. So the Edit / lifecycle affordances
    // must NOT render. Backend enforces the same on the PATCH path
    // independently; this asserts the UX mirror.
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyAId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    const buildingA = await resolveBuildingForCompany(sa, companyAId);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdminB);
    await page.goto(`/admin/buildings/${buildingA.id}`);

    // The detail page must mount (cross-company read access via the
    // buildings list endpoint is allowed for any COMPANY_ADMIN; if a
    // future tightening blocks this, the test will tell us).
    await expect(
      page.locator('[data-testid="building-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // The role-gated affordances must be absent: this user is not a
    // member of Company A, and is not a SUPER_ADMIN.
    await expect(
      page.locator('[data-testid="building-edit-link"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="deactivate-button"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="reactivate-button"]'),
    ).toHaveCount(0);
  });
});
