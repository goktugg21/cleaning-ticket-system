import { test } from "@playwright/test";

import { DEMO_USERS } from "../e2e/fixtures/demoUsers";
import { loginAs } from "../e2e/fixtures/login";

/**
 * Sprint 30 Batch 30.1.1 — visual evidence for the multi-tenant fix.
 *
 * Ticket 77 is at building R2 Rotterdam, providing company "Bright
 * Facilities" (id 2). The Assignment card's field-staff subsection must
 * read "Assigned Bright Facilities staff" / "Toegewezen Bright
 * Facilities-medewerkers" — never the old hardcoded "OSIUS" copy.
 *
 * Output is checked into `frontend/tests/visual/`, NOT under
 * `tests/e2e/`, so it does not run in the regular spec bundle.
 */

test("Ticket 77 (Bright Facilities) renders the consolidated assignment card with the tenant company name", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/tickets/77");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2_000);
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_1_multi_tenant_heading.png",
    fullPage: true,
  });
});
