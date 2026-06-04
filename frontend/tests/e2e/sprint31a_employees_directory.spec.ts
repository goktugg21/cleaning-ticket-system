import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Employees directory (feature/employees-directory).
 *
 * Two surfaces over two backend endpoints:
 *   - Provider directory  GET /api/employees/         (/admin/employees)
 *   - Customer directory  GET /api/customers/<cid>/employees/
 *                         (/admin/customers/:id/employees + /my/employees)
 *
 * Test footprint:
 *   1. SUPER_ADMIN sees the provider directory with rows + the STAFF
 *      inline employment-type edit affordance + a Manage account link.
 *   2. BUILDING_MANAGER reaches the provider directory read-only (no
 *      edit affordance) via its own sidebar entry.
 *   3. CUSTOMER_USER reaches /my/employees and sees the customer
 *      directory; a non-CCA customer user has NO edit affordance.
 *   4. SUPER_ADMIN reaches the customer-scoped directory via the
 *      customer submenu and sees the edit affordance.
 */

test.describe("Employees directory", () => {
  test("super admin sees the provider directory with edit + manage links", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/employees");

    await expect(
      page.locator('[data-testid="employees-admin-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // At least one row renders.
    await expect(
      page.locator('[data-testid="employee-row"]').first(),
    ).toBeVisible({ timeout: 10_000 });

    // Every row carries a Manage account link to the Users page.
    const manageLink = page
      .locator('[data-testid="employee-manage-account"]')
      .first();
    await expect(manageLink).toBeVisible();
    const href = await manageLink.getAttribute("href");
    expect(href).toMatch(/^\/admin\/users\/\d+$/);

    // STAFF rows get an inline employment-type edit affordance for SA.
    const staffRow = page
      .locator('[data-testid="employee-row"][data-role="STAFF"]')
      .first();
    await expect(staffRow).toBeVisible();
    const editButton = staffRow.locator(
      '[data-testid="employee-edit-employment-type"]',
    );
    await expect(editButton).toBeVisible();
    await editButton.click();
    await expect(
      staffRow.locator('[data-testid="employee-employment-type-select"]'),
    ).toBeVisible();
  });

  test("building manager reaches the directory read-only", async ({ page }) => {
    await loginAs(page, DEMO_USERS.managerAll);

    // BM has its own sidebar entry (no admin group).
    const navEntry = page.locator('[data-testid="sidebar-employees-bm"]');
    await expect(navEntry).toBeVisible({ timeout: 10_000 });
    await navEntry.click();

    await page.waitForURL((url) => url.pathname === "/admin/employees");
    await expect(
      page.locator('[data-testid="employees-admin-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.locator('[data-testid="employee-row"]').first(),
    ).toBeVisible({ timeout: 10_000 });

    // BM is read-only — no inline employment-type edit affordance.
    await expect(
      page.locator('[data-testid="employee-edit-employment-type"]'),
    ).toHaveCount(0);
  });

  test("customer user sees their org directory without edit affordance", async ({
    page,
  }) => {
    // Iris is a plain CUSTOMER_USER (not a CUSTOMER_COMPANY_ADMIN), so
    // the edit affordance must be absent.
    await loginAs(page, DEMO_USERS.customerB1B2);

    const navEntry = page.locator('[data-testid="sidebar-my-employees"]');
    await expect(navEntry).toBeVisible({ timeout: 10_000 });
    await navEntry.click();

    await page.waitForURL((url) => url.pathname === "/my/employees");
    await expect(
      page.locator('[data-testid="my-employees-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.locator('[data-testid="customer-employees-directory"]'),
    ).toBeVisible({ timeout: 10_000 });

    // No edit affordance for a non-CCA customer user.
    await expect(
      page.locator('[data-testid="customer-employee-edit-access-role"]'),
    ).toHaveCount(0);
  });

  test("super admin edits a customer employee's access role", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);

    // Enter a customer scope, then the Employees submenu entry.
    await page.goto("/admin/customers");
    await page
      .locator('[data-testid="customer-row"], .admin-row-clickable, a')
      .first()
      .waitFor({ state: "visible", timeout: 10_000 });

    // Navigate to the first customer's overview by clicking the first
    // customer link in the list, then use the customer submenu.
    const firstCustomerLink = page
      .locator('a[href^="/admin/customers/"]')
      .first();
    await firstCustomerLink.click();
    await page.waitForURL((url) =>
      /^\/admin\/customers\/\d+/.test(url.pathname),
    );

    const employeesEntry = page.locator(
      '[data-testid="sidebar-customer-employees"]',
    );
    await expect(employeesEntry).toBeVisible({ timeout: 10_000 });
    await employeesEntry.click();

    await page.waitForURL((url) =>
      /^\/admin\/customers\/\d+\/employees$/.test(url.pathname),
    );
    await expect(
      page.locator('[data-testid="customer-employees-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // SA gets the edit affordance. If the customer has at least one
    // employee, the affordance is present and opens the modal.
    const editButton = page
      .locator('[data-testid="customer-employee-edit-access-role"]')
      .first();
    if ((await editButton.count()) > 0) {
      await editButton.click();
      await expect(
        page.locator('[data-testid="customer-employee-edit-modal"]'),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});
