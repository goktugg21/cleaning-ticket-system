import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 18 — `/admin/audit-logs` SPA page access.
 *
 * Mirrors `audit/views.py::IsSuperAdmin`. The SPA `SuperAdminRoute`
 * guard redirects every other role to `/?admin_required=ok`; we
 * assert the URL does not stay on `/admin/audit-logs` for those roles
 * and the page renders for SUPER_ADMIN.
 *
 * The seed_demo_data run for the demo stack creates several audit
 * rows (CompanyUserMembership inserts, BuildingManagerAssignment
 * inserts, CustomerUserBuildingAccess inserts, etc.), so the
 * SUPER_ADMIN view should display rows. We tolerate the empty-state
 * card too — a freshly-truncated DB would produce zero rows; either
 * shape is a valid pass.
 */

test("SUPER_ADMIN can open /admin/audit-logs", async ({ page }) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/audit-logs");
  await page.waitForLoadState("networkidle");
  expect(new URL(page.url()).pathname).toBe("/admin/audit-logs");
  await expect(page.locator('[data-testid="audit-logs-page"]')).toBeVisible({
    timeout: 10_000,
  });
  // Either a table row or the empty-state card must be present once
  // the network idles.
  const rows = page.locator('[data-testid="audit-row"]');
  const empty = page.locator('[data-testid="audit-empty"]');
  await expect(rows.first().or(empty)).toBeVisible({ timeout: 10_000 });
});

test("SUPER_ADMIN sidebar shows the audit log link", async ({ page }) => {
  await loginAs(page, DEMO_USERS.super);
  await expect(
    page.locator('.sidebar-nav a[href="/admin/audit-logs"]'),
  ).toBeVisible({ timeout: 10_000 });
});

for (const roleKey of [
  "companyAdmin",
  "managerAll",
  "customerAll",
] as const) {
  test(`${roleKey} cannot reach /admin/audit-logs`, async ({ page }) => {
    await loginAs(page, DEMO_USERS[roleKey]);
    await page.goto("/admin/audit-logs");
    await page.waitForLoadState("networkidle");
    // SuperAdminRoute redirects to /?admin_required=ok. The page
    // never mounts; we assert via the URL change AND the absence of
    // the page test id so an accidental future leak (e.g. someone
    // forgets the SuperAdminRoute wrapper) gets caught here.
    expect(new URL(page.url()).pathname).not.toBe("/admin/audit-logs");
    await expect(
      page.locator('[data-testid="audit-logs-page"]'),
    ).toHaveCount(0);
  });

  test(`${roleKey} sidebar hides the audit log link`, async ({ page }) => {
    await loginAs(page, DEMO_USERS[roleKey]);
    await expect(
      page.locator('.sidebar-nav a[href="/admin/audit-logs"]'),
    ).toHaveCount(0);
  });
}
