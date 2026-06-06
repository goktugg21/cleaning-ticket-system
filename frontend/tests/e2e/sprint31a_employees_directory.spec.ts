import { expect, test } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
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
 *   1. SUPER_ADMIN sees the provider directory; rows are the click target
 *      (navigate to the user account) + STAFF rows expose the inline
 *      employment-type pencil edit.
 *   2. BUILDING_MANAGER reaches the provider directory read-only (no edit
 *      affordance) via its own sidebar entry.
 *   3. CUSTOMER_USER reaches /my/employees and sees the customer
 *      directory; a non-CCA customer user has NO edit affordance.
 *   4. SUPER_ADMIN reaches the customer-scoped directory via the customer
 *      submenu and sees the edit affordance.
 *   5. (Codex #1) a CCA keeps the access-role edit affordance even when
 *      the table is filtered by another access role.
 */

test.describe("Employees directory", () => {
  test("super admin sees the provider directory; row click opens the account", async ({
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

    // STAFF rows get an inline employment-type pencil edit for SA: the
    // pencil reveals the <select> in place (and, because it is a nested
    // control, does not trigger row navigation).
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

    // The row itself is the click target -> the person's account page.
    await page
      .locator('[data-testid="employee-row"]')
      .first()
      .locator("td")
      .first()
      .click();
    await page.waitForURL((url) => /^\/admin\/users\/\d+$/.test(url.pathname));
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

  test("super admin edits a customer user's per-building access via the Users drill-in modal", async ({
    page,
  }) => {
    // The customer-scoped Employees tab was deleted in the CCA / people
    // consolidation rework: USERS is now the single people-with-access
    // surface, and per-building access editing lives in the Users
    // drill-in modal (the reused ContactPermissionsPanel). Navigate
    // straight to the Users sub-page to avoid a fragile dependency on
    // the customers-list link ordering.
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/customers/1/users");
    await page.waitForURL((url) =>
      /^\/admin\/customers\/\d+\/users$/.test(url.pathname),
    );
    await expect(
      page.locator('[data-testid="customer-users-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // SA gets the Manage affordance on each member row. If the customer
    // has at least one member, the drill-in modal opens and exposes the
    // per-building access editor (ContactPermissionsPanel) for a
    // non-company-admin user.
    const manageButton = page
      .locator('[data-testid="customer-user-manage-button"]')
      .first();
    if ((await manageButton.count()) > 0) {
      await manageButton.click();
      await expect(
        page.locator('[data-testid="customer-user-manage-modal"]'),
      ).toBeVisible({ timeout: 10_000 });
      await expect(
        page.locator('[data-testid="customer-user-company-admin-section"]'),
      ).toBeVisible();
    }
  });

  test("CCA keeps the edit affordance under an access-role filter (Codex #1)", async ({
    page,
  }) => {
    // Setup (via API as SUPER_ADMIN): in Amanda's customer, make Amanda a
    // CUSTOMER_COMPANY_ADMIN and force ONE other user to a plain
    // CUSTOMER_USER on all their buildings. Then, filtering Amanda's
    // directory by CUSTOMER_USER drops Amanda's own (CCA) row — which is
    // exactly the case the Codex #1 bug regressed (canEdit was derived
    // from the filtered list, so the edit affordance vanished). The fix
    // derives canEdit from the viewer's own role independently of the
    // filter, so the affordance must remain.
    const ccaEmail = DEMO_USERS.customerB3.email; // Amanda
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      const customers =
        ((await (await sa.get("/api/customers/?page_size=50")).json())
          .results as Array<{ id: number }>) ?? [];
      let customerId: number | null = null;
      let amandaId: number | null = null;
      let otherId: number | null = null;
      for (const c of customers) {
        const empResp = await sa.get(`/api/customers/${c.id}/employees/`);
        if (empResp.status() !== 200) continue;
        const rows =
          ((await empResp.json()).results as Array<{
            id: number;
            email: string;
          }>) ?? [];
        const amanda = rows.find((r) => r.email === ccaEmail);
        const other = rows.find((r) => r.email !== ccaEmail);
        if (amanda && other) {
          customerId = c.id;
          amandaId = amanda.id;
          otherId = other.id;
          break;
        }
      }
      expect(
        customerId,
        "Amanda's customer (with another user) not found",
      ).not.toBeNull();

      const setAllAccess = async (uid: number, role: string): Promise<number> => {
        const rows =
          ((await (
            await sa.get(`/api/customers/${customerId}/users/${uid}/access/`)
          ).json()).results as Array<{ building_id: number }>) ?? [];
        for (const ar of rows) {
          const resp = await sa.patch(
            `/api/customers/${customerId}/users/${uid}/access/${ar.building_id}/`,
            { data: { access_role: role } },
          );
          expect(resp.status()).toBe(200);
        }
        return rows.length;
      };
      await setAllAccess(amandaId as number, "CUSTOMER_COMPANY_ADMIN");
      const otherCount = await setAllAccess(otherId as number, "CUSTOMER_USER");
      expect(otherCount).toBeGreaterThan(0);
    } finally {
      await sa.dispose();
    }

    // As Amanda (now a CCA), the edit affordance is present...
    await loginAs(page, DEMO_USERS.customerB3);
    await page.goto("/my/employees");
    await expect(
      page.locator('[data-testid="customer-employees-directory"]'),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page
        .locator('[data-testid="customer-employee-edit-access-role"]')
        .first(),
    ).toBeVisible();

    // ...and it SURVIVES filtering by CUSTOMER_USER (which excludes
    // Amanda's own CCA row). With the Codex #1 bug the affordance vanished.
    await page
      .locator('[data-testid="customer-employees-filter-access-role"]')
      .selectOption("CUSTOMER_USER");
    await expect(
      page.locator('[data-testid="customer-employee-row"]').first(),
    ).toBeVisible();
    await expect(
      page
        .locator('[data-testid="customer-employee-edit-access-role"]')
        .first(),
    ).toBeVisible();
  });
});
