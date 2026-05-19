import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import {
  COMPANY_A_NAME,
  COMPANY_B_NAME,
  DEMO_PASSWORD,
  DEMO_USERS,
} from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.3 — Companies view-first.
 *
 * `/admin/companies/:id` no longer mounts the form; it renders the
 * new read-only `CompanyDetailPage`. An explicit, role-gated Edit
 * button navigates to `/admin/companies/:id/edit`, which still mounts
 * the form. Cancel on the edit page returns to detail without saving.
 *
 * Pattern: this is the template for 29.4 (Buildings) and 29.5
 * (Customer Overview). Test footprint validates:
 *   1. Detail page renders with the locked read-only testids.
 *   2. SUPER_ADMIN sees the Edit button and it routes to .../edit.
 *   3. Cancel on the edit form returns to the detail without saving.
 *   4. A non-eligible admin (COMPANY_ADMIN of a different company)
 *      sees no Edit button on a company they don't belong to.
 */
const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:8000";

async function apiAs(
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  const loginCtx = await request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
  });
  const tokenResponse = await loginCtx.post("/api/auth/token/", {
    data: { email, password },
  });
  expect(tokenResponse.status()).toBe(200);
  const body = (await tokenResponse.json()) as { access: string };
  await loginCtx.dispose();
  return await request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
  });
}

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

test.describe("Sprint 29 Batch 29.3 — Companies view-first", () => {
  test("detail page renders read-only with the locked testids", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/companies/${companyId}`);

    // The detail page wrapper.
    await expect(
      page.locator('[data-testid="company-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Both read-only cards.
    await expect(
      page.locator('[data-testid="company-detail-about-card"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="company-detail-admins-card"]'),
    ).toBeVisible();

    // The form must NOT be on this URL — the form's section-admins
    // card is its only fingerprint that wouldn't collide with the
    // detail page. The legacy header reactivate position is also
    // gone; deactivate-button lives on the detail page (super-admin
    // sees it on active companies because of the button gate).
    await expect(page.locator('[data-testid="section-admins"]'))
      .toHaveCount(0);
    await expect(page.locator('input#company-name')).toHaveCount(0);
  });

  test("super admin sees Edit and it routes to /edit", async ({ page }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/companies/${companyId}`);

    const editLink = page.locator('[data-testid="company-edit-link"]');
    await expect(editLink).toBeVisible({ timeout: 10_000 });

    const href = await editLink.getAttribute("href");
    expect(href).toBe(`/admin/companies/${companyId}/edit`);

    await editLink.click();
    await page.waitForURL((url) =>
      url.pathname === `/admin/companies/${companyId}/edit`,
    );

    // The form must be mounted at /edit.
    await expect(page.locator('input#company-name')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('[data-testid="section-admins"]')).toBeVisible();
  });

  test("Cancel discards the edit and returns to detail", async ({
    page,
  }) => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);

    // Capture the canonical name from the API so we can prove the
    // Cancel flow did NOT persist the typed-over value.
    const fetched = await sa.get(`/api/companies/${companyId}/`);
    expect(fetched.status()).toBe(200);
    const original = (await fetched.json()) as { name: string };
    await sa.dispose();
    const originalName = original.name;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/companies/${companyId}/edit`);

    const nameInput = page.locator("input#company-name");
    await expect(nameInput).toBeVisible({ timeout: 10_000 });
    await nameInput.fill(`${originalName} ___DIRTY___`);

    const cancel = page.locator('[data-testid="company-edit-cancel"]');
    await expect(cancel).toBeVisible();
    await cancel.click();

    await page.waitForURL((url) =>
      url.pathname === `/admin/companies/${companyId}`,
    );
    await expect(
      page.locator('[data-testid="company-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Re-fetch via the API to prove the original name is intact.
    const sa2 = await apiAs(DEMO_USERS.super.email);
    const refetched = await sa2.get(`/api/companies/${companyId}/`);
    expect(refetched.status()).toBe(200);
    const refetchedBody = (await refetched.json()) as { name: string };
    expect(refetchedBody.name).toBe(originalName);
    await sa2.dispose();
  });

  test("an admin of a different company does not see the Edit button", async ({
    page,
  }) => {
    // COMPANY_ADMIN of Company B (Bright Facilities) viewing Company A
    // (Osius Demo). The route guard (`AdminRoute`) admits any
    // SUPER_ADMIN or COMPANY_ADMIN — but the in-page `canEdit` gate
    // requires the admin to be a member of THIS company. So the Edit
    // affordance must NOT render. Backend enforces the same on the
    // PATCH path independently; this asserts the UX mirror.
    const sa = await apiAs(DEMO_USERS.super.email);
    const companyAId = await resolveCompanyIdByName(sa, COMPANY_A_NAME);
    const companyBId = await resolveCompanyIdByName(sa, COMPANY_B_NAME);
    await sa.dispose();
    expect(companyAId).not.toBe(companyBId);

    await loginAs(page, DEMO_USERS.companyAdminB);
    await page.goto(`/admin/companies/${companyAId}`);

    // The detail page must mount (read access via the list endpoint).
    await expect(
      page.locator('[data-testid="company-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // The role-gated affordances must be absent: this user is not a
    // member of Company A, and is not a SUPER_ADMIN.
    await expect(
      page.locator('[data-testid="company-edit-link"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="deactivate-button"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="reactivate-button"]'),
    ).toHaveCount(0);
  });
});
