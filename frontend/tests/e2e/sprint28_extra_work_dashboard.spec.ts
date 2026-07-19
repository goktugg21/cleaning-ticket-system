import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 9 — Extra Work dashboard cards.
 * Sprint 28 Batch 13 (rework) — unified dashboard composition.
 * RF-16 (#106) — REWRITTEN: the dashboard no longer renders the big
 * work lists or the work-view toggle. It is an overview: KPI strip +
 * attention cards ("To confirm" / "Unassigned" / "Recent activity").
 * The full ticket list lives exclusively on /tickets
 * (dashboard-tickets-section moved there); the Extra Work list lives
 * on /extra-work as before.
 *
 * No mutations — read-only assertions. `seed_demo_data` fixture.
 */

test.describe("RF-16 — dashboard is an overview, lists live on their pages", () => {
  test("SUPER_ADMIN dashboard shows KPI strip + attention cards, no lists", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("dashboard-ops-kpi-row")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("dashboard-attention")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("attention-review")).toBeVisible();
    await expect(page.getByTestId("attention-unassigned")).toBeVisible();
    await expect(page.getByTestId("attention-activity")).toBeVisible();

    // The old list surfaces and the work-view toggle are gone from "/".
    await expect(page.getByTestId("dashboard-tickets-section")).toHaveCount(0);
    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("dashboard-work-view-toggle"),
    ).toHaveCount(0);
  });

  test("the full ticket list renders on /tickets with the preset applied", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.waitForLoadState("networkidle");

    // Follow the attention card's deep link into the manager-review
    // queue — the list page must apply the status preset.
    await page.goto("/tickets?status=WAITING_MANAGER_REVIEW");
    await expect(page.getByTestId("dashboard-tickets-section")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.locator("select.filter-control").first(),
    ).toHaveValue("WAITING_MANAGER_REVIEW");
  });

  test("CUSTOMER_USER sees the unified Awaiting approval KPI + attention cards", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("dashboard-ops-kpi-awaiting")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("dashboard-attention")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("STAFF dashboard is the same overview shape (no list surfaces)", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("dashboard-ops-kpi-row")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("dashboard-attention")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("dashboard-tickets-section")).toHaveCount(0);
    await expect(
      page.getByTestId("dashboard-extra-work-section"),
    ).toHaveCount(0);
  });
});
