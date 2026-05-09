import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 16 — reports page access matches IsReportsConsumer.
 *
 * Reports are allowed for SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER.
 * CUSTOMER_USER must be denied. The frontend ReportsRoute redirects
 * unauthorised roles back to /; we assert that here.
 */

test("Company Admin can open /reports", async ({ page }) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/reports");
  await page.waitForLoadState("networkidle");
  expect(page.url()).toContain("/reports");
  // Reports page renders chart cards. We do not assert on every
  // chart label (i18n / future re-skinning would break the test);
  // we just confirm at least one .card element rendered.
  await expect(page.locator(".card").first()).toBeVisible({
    timeout: 10_000,
  });
});

test("Building Manager (Murat) can open /reports", async ({ page }) => {
  await loginAs(page, DEMO_USERS.managerB1);
  await page.goto("/reports");
  await page.waitForLoadState("networkidle");
  expect(page.url()).toContain("/reports");
});

test("Customer user (Amanda) is redirected away from /reports", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await page.goto("/reports");
  await page.waitForLoadState("networkidle");
  // ReportsRoute sends customer-users to "/?admin_required=ok". We
  // tolerate any non-/reports landing.
  expect(page.url()).not.toContain("/reports");
});
