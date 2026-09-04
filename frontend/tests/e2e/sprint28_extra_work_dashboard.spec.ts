import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 9 — Extra Work dashboard cards.
 * Sprint 28 Batch 13 (rework) — unified dashboard composition.
 * RF-16 (#106) — the dashboard became an overview.
 * FE-6 (Addendum D) — REWRITTEN for the redesigned home pages:
 *
 *   - Provider roles (SA / CA / BM) land on the dashboard: FOUR KPI
 *     tiles (`dashboard-ops-kpi-row`: open work, urgent, awaiting,
 *     this month), ONE attention list (`dashboard-attention` with an
 *     `attention-needed` list of `attention-<key>` rows) and the
 *     billing panel. No work lists, no work-view toggle.
 *   - The full ticket list lives exclusively on /tickets; the Extra
 *     Work list on /extra-work as before.
 *   - A CUSTOMER_USER's home is the Start page (`customer-start-page`),
 *     not the provider dashboard.
 *   - A STAFF user's home is the agenda (`/agenda`, `agenda-page`).
 *
 * No mutations — read-only assertions. `seed_demo_data` fixture.
 */

test.describe("FE-6 — the home page per role; lists live on their pages", () => {
  test("SUPER_ADMIN dashboard shows four tiles + the attention list, no lists", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("dashboard-ops-kpi-row")).toBeVisible({
      timeout: 10_000,
    });
    for (const tile of ["hero-open-work", "hero-urgent", "hero-awaiting", "hero-month"]) {
      await expect(page.getByTestId(tile)).toBeVisible();
    }
    await expect(page.getByTestId("dashboard-attention")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("attention-needed")).toBeVisible();
    // The attention list is ONE list of rows; the three separate
    // attention cards of RF-16 are gone.
    expect(await page.locator('[data-testid^="attention-"]').count()).toBeGreaterThan(0);
    await expect(page.getByTestId("dashboard-billing-panel")).toBeVisible();

    // The old list surfaces and the work-view toggle are gone from "/".
    await expect(page.getByTestId("dashboard-tickets-section")).toHaveCount(0);
    await expect(page.getByTestId("ticket-card-list")).toHaveCount(0);
    await expect(page.getByTestId("extra-work-list-page")).toHaveCount(0);
  });

  test("the full ticket list renders on /tickets with the preset applied", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.waitForLoadState("networkidle");

    // Follow an attention row's deep link into the manager-review
    // queue — the list page must apply the status preset: the tab that
    // status lives on opens and the precise status filter is set.
    await page.goto("/tickets?status=WAITING_MANAGER_REVIEW");
    await expect(page.getByTestId("dashboard-tickets-section")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("tickets-tab-busy")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("tickets-filter-status")).toHaveValue(
      "WAITING_MANAGER_REVIEW",
    );
  });

  test("CUSTOMER_USER lands on the Start page, not the provider dashboard", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("customer-start-page")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("start-new-melding")).toBeVisible();
    await expect(page.getByTestId("dashboard-ops-kpi-row")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-attention")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-tickets-section")).toHaveCount(0);
  });

  test("STAFF lands on the agenda (no dashboard surfaces)", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.waitForURL((url) => url.pathname === "/agenda", {
      timeout: 10_000,
    });
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("agenda-page")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("dashboard-ops-kpi-row")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-attention")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-tickets-section")).toHaveCount(0);
  });
});
