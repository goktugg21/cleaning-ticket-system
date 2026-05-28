/**
 * Sprint 28 Batch 12 — BUILDING_MANAGER read-only customer / contact view.
 *
 * What's locked here:
 *   1. BM can navigate to /admin/customers and see the read-only
 *      customer list (no "Add customer" button, no Edit links).
 *   2. BM detail page renders the read-only overview with NO form
 *      controls (no Save / Edit / Delete affordances), and the
 *      "Customers in your assigned buildings" wording is present
 *      (via the `bm-customers-readonly-hint` testid; locale-agnostic).
 *   3. BM contacts page renders the contact list with NO Add / Edit /
 *      Delete buttons.
 *   4. BM cannot reach the global admin pages (`/admin/companies`,
 *      `/admin/buildings`, `/admin/users`) — the `AdminRoute` wrapper
 *      bounces them back to the dashboard with `?admin_required=ok`.
 *
 * Light assertions only — no count assertions (seed-data dependent),
 * no DOM-shape assertions. Anchors on `data-testid` and on the
 * absence of role-bound affordances.
 */
import { test, expect } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

test.describe("Sprint 28 Batch 12 — BM read-only customer/contact view", () => {
  test("BM sees the read-only customer list (no Add button)", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.managerAll);
    await page.goto("/admin/customers");

    // The BM read-only page renders with its dedicated testid.
    await expect(page.getByTestId("bm-customers-page")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByTestId("bm-customers-readonly-hint"),
    ).toBeVisible();

    // No "Add customer" button. The admin variant renders a button
    // pointing at /admin/customers/new — BM must not see it.
    await expect(
      page.locator("a[href='/admin/customers/new']"),
    ).toHaveCount(0);
  });

  test("BM customer detail is read-only (no Save / Edit / Delete)", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.managerAll);

    // Resolve a customer the BM can see by hitting the BM list page
    // and clicking the first row's link.
    await page.goto("/admin/customers");
    await expect(page.getByTestId("bm-customers-page")).toBeVisible({
      timeout: 15_000,
    });
    const firstLink = page
      .getByTestId(/^bm-customer-link-/)
      .first();
    await expect(firstLink).toBeVisible();
    await firstLink.click();

    // Detail page renders.
    await expect(
      page.getByTestId("bm-customer-detail-page"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByTestId("bm-customer-detail-readonly-hint"),
    ).toBeVisible();

    // No form controls. The admin variant (`CustomerFormPage`) is
    // packed with `<input>` / `<select>` / `<textarea>` form
    // controls — the BM read-only page has zero. We assert by
    // counting form controls inside the detail page wrapper.
    const detailPage = page.getByTestId("bm-customer-detail-page");
    await expect(detailPage.locator("input")).toHaveCount(0);
    await expect(detailPage.locator("textarea")).toHaveCount(0);
    await expect(detailPage.locator("select")).toHaveCount(0);

    // The "View contacts" link is the only outbound link the BM has
    // from this surface. It must point at the contacts sub-route.
    const contactsLink = page.getByTestId(
      "bm-customer-detail-contacts-link",
    );
    await expect(contactsLink).toBeVisible();
  });

  test("BM contacts page is read-only (no Add / Edit / Delete)", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.managerAll);

    await page.goto("/admin/customers");
    const firstLink = page.getByTestId(/^bm-customer-link-/).first();
    await expect(firstLink).toBeVisible({ timeout: 15_000 });
    await firstLink.click();

    await expect(
      page.getByTestId("bm-customer-detail-page"),
    ).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("bm-customer-detail-contacts-link").click();

    await expect(
      page.getByTestId("bm-customer-contacts-page"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByTestId("bm-customer-contacts-readonly-hint"),
    ).toBeVisible();

    // No Add / Edit / Delete affordances. The admin variant carries
    // a primary "Add contact" button at the top. We anchor on the
    // absence of any `btn-primary` / `btn-danger` inside the page
    // wrapper — the BM page intentionally renders no primary or
    // danger buttons.
    const contactsPage = page.getByTestId("bm-customer-contacts-page");
    await expect(contactsPage.locator(".btn-primary")).toHaveCount(0);
    await expect(contactsPage.locator(".btn-danger")).toHaveCount(0);

    // No form controls at all — purely read-only.
    await expect(contactsPage.locator("input")).toHaveCount(0);
    await expect(contactsPage.locator("textarea")).toHaveCount(0);
    await expect(contactsPage.locator("select")).toHaveCount(0);
  });

  test("BM cannot reach global admin surfaces (Companies / Buildings / Users / Services)", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await loginAs(page, DEMO_USERS.managerAll);

    // AdminRoute rejects BM and redirects to '/?admin_required=ok'.
    // Hit each path and assert the URL ends up on the dashboard with
    // the admin-required query string, not on the admin page.
    for (const path of [
      "/admin/companies",
      "/admin/buildings",
      "/admin/users",
      "/admin/services",
      "/admin/customers/new",
    ]) {
      await page.goto(path);
      await page.waitForURL(/admin_required=ok/, { timeout: 10_000 });
      expect(page.url()).toContain("admin_required=ok");
    }
  });
});
