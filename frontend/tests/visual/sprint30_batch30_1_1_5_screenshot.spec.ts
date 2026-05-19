import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "../e2e/fixtures/demoUsers";
import { loginAs } from "../e2e/fixtures/login";

/**
 * Sprint 30 Batch 30.1.1.5 — visual evidence for the progressive
 * workflow disclosure.
 *
 *   tid=83 (WAITING_CUSTOMER_APPROVAL): Approved + Rejected primary,
 *     OPEN / IN_PROGRESS / WAITING_MANAGER_REVIEW / CLOSED /
 *     REOPENED_BY_ADMIN secondary behind the "More actions" toggle.
 *     Toggle is opened in the screenshot to expose the disclosure.
 *
 *   tid=75 (CLOSED): no primaries — secondary list (OPEN /
 *     IN_PROGRESS / WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL /
 *     REJECTED / APPROVED / REOPENED_BY_ADMIN) renders inline-open
 *     without a toggle.
 *
 * Output is checked into `frontend/tests/visual/`, NOT under
 * `tests/e2e/`, so it does not run in the regular spec bundle.
 */

test("tid=83 WAITING_CUSTOMER_APPROVAL — primary Approve/Reject + secondary disclosure", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/tickets/83");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);
  // Expand the secondary disclosure so the screenshot captures
  // both partitions in one frame.
  const toggle = page.locator('[data-testid="workflow-more-actions-toggle"]');
  await expect(toggle).toBeVisible({ timeout: 10_000 });
  await toggle.click();
  await expect(
    page.locator('[data-testid="workflow-secondary-list"]'),
  ).toBeVisible({ timeout: 5_000 });
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_1_5_wca_progressive.png",
    fullPage: true,
  });
});

test("tid=75 CLOSED — no primaries, secondary list inline-open without toggle", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/tickets/75");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);
  // On CLOSED there are no primaries; the secondary list auto-opens
  // and the toggle button must be absent.
  await expect(
    page.locator('[data-testid="workflow-secondary-list"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('[data-testid="workflow-more-actions-toggle"]'),
  ).toHaveCount(0);
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_1_5_closed_inline_open.png",
    fullPage: true,
  });
});
