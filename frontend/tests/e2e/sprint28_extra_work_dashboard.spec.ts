import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 9 — Extra Work dashboard cards.
 *
 * Closes the frontend half of Batch 9: the dashboard now renders
 * two top-level sections (Tickets + Extra Work) with role-aware
 * shapes:
 *
 *  - Provider-side actors (SUPER_ADMIN, COMPANY_ADMIN) see both
 *    sections populated with scoped aggregates from
 *    /api/extra-work/stats/ + /api/extra-work/stats/by-building/.
 *
 *  - CUSTOMER_USER actors see the Extra Work section with the
 *    "Awaiting customer" KPI carrying the dedicated test id so it
 *    can be visually emphasised (the bucket their action resolves).
 *
 *  - STAFF actors receive a zeroed-out payload from the backend
 *    (scope_extra_work_for returns .none()), and the dashboard
 *    renders an explicit empty-state instead of a row of zero KPI
 *    cards.
 *
 * No mutations — read-only assertions on the dashboard surface. The
 * fixture data seeded by `seed_demo_data` is enough.
 */

test.describe("Sprint 28 Batch 9 — Extra Work dashboard", () => {
  test("SUPER_ADMIN sees both Tickets and Extra Work sections", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("CUSTOMER_USER sees Extra Work awaiting-customer KPI", async ({
    page,
  }) => {
    // Tom Verbeek (CUSTOMER_USER, all three Osius buildings) has
    // visibility on the seeded Extra Work requests, so the Extra
    // Work section will render the KPI grid rather than the empty
    // state. The "awaiting customer" KPI carries the dedicated
    // testid that the dashboard uses to flag the bucket
    // CUSTOMER_USER actors action against.
    await loginAs(page, DEMO_USERS.customerAll);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByTestId("dashboard-extra-work-kpi-awaiting-customer"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("STAFF sees Extra Work empty-state", async ({ page }) => {
    // Backend `scope_extra_work_for(staff_user)` returns `.none()`
    // — STAFF cannot see any Extra Work request, so the dashboard
    // collapses the Extra Work section into its empty-state instead
    // of rendering a row of zero KPI cards.
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByTestId("dashboard-extra-work-section-empty"),
    ).toBeVisible({ timeout: 10_000 });
  });
});
