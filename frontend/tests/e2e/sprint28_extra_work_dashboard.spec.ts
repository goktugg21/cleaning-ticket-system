import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 9 — Extra Work dashboard cards.
 * Sprint 28 Batch 13 (rework) — dashboard composition was rewritten
 * into a single `.operations-dashboard` shell with one top KPI strip
 * + a work-strip toggle + a work-layout. The Batch 9 testids that
 * matter for backend / scope coverage still resolve:
 *
 *  - `dashboard-tickets-section` and `dashboard-extra-work-section`
 *    are preserved on visible elements in the unified `view=all`
 *    layout (the extra-work side card carries the section testid).
 *
 *  - The CUSTOMER_USER "awaiting customer" bucket is now folded
 *    into the unified `dashboard-ops-kpi-awaiting` KPI alongside
 *    awaiting-pricing extra-work and waiting-customer-approval
 *    tickets. The unified bucket is the right surface to assert on
 *    because that is the action queue the CUSTOMER_USER role
 *    resolves.
 *
 *  - The STAFF empty-state for extra work is only rendered when the
 *    operator drills into the extra-work-only view; the unified
 *    top-of-page layout no longer dedicates a full empty section to
 *    a single zero-data half. The STAFF case therefore navigates to
 *    `?view=extra-work` and asserts the dedicated empty-state.
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

  test("CUSTOMER_USER sees the unified Awaiting approval KPI", async ({
    page,
  }) => {
    // Tom Verbeek (CUSTOMER_USER, all three Osius buildings) has
    // visibility on the seeded Extra Work requests. In the Batch 13
    // unified dashboard, the per-half "awaiting customer" KPI was
    // folded into a single top-strip KPI ("Awaiting approval") that
    // sums tickets.waitingApproval + extraWork.awaiting_customer +
    // extraWork.awaiting_pricing. This is the action queue a
    // CUSTOMER_USER actor resolves against.
    await loginAs(page, DEMO_USERS.customerAll);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByTestId("dashboard-ops-kpi-awaiting"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("STAFF sees Extra Work empty-state in the dedicated view", async ({
    page,
  }) => {
    // Backend `scope_extra_work_for(staff_user)` returns `.none()`
    // — STAFF cannot see any Extra Work request. In the Batch 13
    // unified dashboard, the empty-state for extra work is rendered
    // inside the dedicated `?view=extra-work` work layout (the
    // top-of-page no longer dedicates a full empty section to a
    // single zero-data half). Drill into the dedicated view to
    // verify the empty-state.
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("dashboard-tickets-section"),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByTestId("dashboard-work-view-extra-work").click();

    await expect(
      page.getByTestId("dashboard-extra-work-section-empty"),
    ).toBeVisible({ timeout: 10_000 });
  });
});
