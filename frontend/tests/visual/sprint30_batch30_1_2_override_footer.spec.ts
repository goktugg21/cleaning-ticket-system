import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "../e2e/fixtures/demoUsers";
import { loginAs } from "../e2e/fixtures/login";

/**
 * Sprint 30 Batch 30.1.2 Phase E — visual evidence for the override-card
 * footer alignment fix.
 *
 *   tid=83 (WAITING_CUSTOMER_APPROVAL). As SUPER_ADMIN, clicking a primary
 *   workflow button (Approve / Reject) opens the customer-decision
 *   override modal. The Cancel link must sit inside the card frame on the
 *   left edge, with Confirm on the right edge. Before this fix the layout
 *   used `justify-content: flex-end` which let Cancel float in the gutter
 *   left of Confirm.
 *
 * Output is checked into `frontend/tests/visual/`, NOT under `tests/e2e/`,
 * so it does not run in the regular spec bundle.
 */

test("tid=83 WCA override modal — Cancel + Confirm anchored inside card footer", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/tickets/83");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);

  // Click the first primary workflow button (APPROVED) to open the
  // override modal. The button has no testid; selecting by class on the
  // visible primary partition is enough for this visual harness.
  const primaryButtons = page.locator(".status-actions .status-btn").first();
  await expect(primaryButtons).toBeVisible({ timeout: 10_000 });
  await primaryButtons.click();

  // Override modal renders with the 27F testids preserved.
  await expect(
    page.locator('[data-testid="ticket-override-modal"]'),
  ).toBeVisible({ timeout: 5_000 });
  await expect(
    page.locator('[data-testid="ticket-override-cancel"]'),
  ).toBeVisible();
  await expect(
    page.locator('[data-testid="ticket-override-submit"]'),
  ).toBeVisible();

  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_2_override_footer.png",
    fullPage: true,
  });
});
