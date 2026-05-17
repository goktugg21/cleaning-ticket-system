import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 10 — Staff per-building visibility selector.
 *
 * Closes the frontend half of Batch 10: each row in the
 * BuildingStaffVisibility editor on UserFormPage (only shown when
 * the target user has role=STAFF) now carries a per-building
 * `visibility_level` selector with three options:
 *
 *   - ASSIGNED_ONLY            (recognised at the building as an
 *                               assign target but does NOT see other
 *                               tickets — Batch 10 B1)
 *   - BUILDING_READ            (legacy default; sees every ticket in
 *                               the building)
 *   - BUILDING_READ_AND_ASSIGN (building-read plus may call
 *                               POST /tickets/<id>/assign/ — B3)
 *
 * The selector PATCHes the existing
 * /api/users/<id>/staff-visibility/<building_id>/ endpoint with
 * `visibility_level`; the backend serializer (Batch 10) accepts it
 * as an additional writable field alongside the Sprint 24A
 * `can_request_assignment` checkbox.
 *
 * No mutations are asserted here — the spec is a read-only sanity
 * check that the selector renders for every BSV row Ahmet (Osius
 * staff) has, and that all three enum options are present. A
 * mutation/persistence assertion is parked because Playwright would
 * need to chase the demo state across the form-save round-trip and
 * the smallest-safe Batch 10 spec is just "does the control exist
 * and offer the right vocabulary".
 */

test.describe("Sprint 28 Batch 10 — Staff per-building visibility selector", () => {
  test("SUPER_ADMIN sees the visibility-level dropdown on a STAFF user's building rows", async ({
    page,
    request,
  }) => {
    await loginAs(page, DEMO_USERS.super);

    // Resolve Ahmet (staffOsius) by email via the admin users list so
    // the spec does not hard-code a numeric ID that may shift when
    // seed_demo_data is reordered.
    const accessToken = await page.evaluate(() =>
      localStorage.getItem("accessToken"),
    );
    expect(accessToken, "super admin must have access token").toBeTruthy();

    const usersResponse = await request.get(
      `http://localhost:8000/api/users/?search=${encodeURIComponent(
        DEMO_USERS.staffOsius.email,
      )}&page_size=10`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    expect(usersResponse.ok()).toBeTruthy();
    const usersBody = await usersResponse.json();
    const match = (usersBody.results as Array<{ id: number; email: string }>)
      .find((u) => u.email === DEMO_USERS.staffOsius.email);
    expect(match, "Ahmet (staffOsius) must exist in seeded data").toBeDefined();

    await page.goto(`/admin/users/${match!.id}`);
    await page.waitForLoadState("networkidle");

    // The staff-details section is only rendered for STAFF users.
    await expect(
      page.getByTestId("staff-details-section"),
    ).toBeVisible({ timeout: 10_000 });

    // At least one BSV row exists for Ahmet — seed grants visibility on
    // every Osius building. The selector data-testid is parameterised by
    // building id so a regex matches every row's desktop variant.
    const desktopSelector = page
      .locator('[data-testid^="staff-visibility-level-select-"]')
      .filter({ hasNot: page.locator('[data-testid*="-mobile-"]') })
      .first();
    await expect(desktopSelector).toBeVisible({ timeout: 10_000 });
  });

  test("dropdown lists all three visibility levels", async ({
    page,
    request,
  }) => {
    await loginAs(page, DEMO_USERS.super);

    const accessToken = await page.evaluate(() =>
      localStorage.getItem("accessToken"),
    );
    const usersResponse = await request.get(
      `http://localhost:8000/api/users/?search=${encodeURIComponent(
        DEMO_USERS.staffOsius.email,
      )}&page_size=10`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const usersBody = await usersResponse.json();
    const match = (usersBody.results as Array<{ id: number; email: string }>)
      .find((u) => u.email === DEMO_USERS.staffOsius.email);
    expect(match).toBeDefined();

    await page.goto(`/admin/users/${match!.id}`);
    await page.waitForLoadState("networkidle");

    const selector = page
      .locator('[data-testid^="staff-visibility-level-select-"]')
      .filter({ hasNot: page.locator('[data-testid*="-mobile-"]') })
      .first();
    await expect(selector).toBeVisible({ timeout: 10_000 });

    // The three options match the backend `VisibilityLevel` enum
    // values verbatim (the i18n labels render in NL or EN depending
    // on the actor's language; the *values* are stable).
    const values = await selector
      .locator("option")
      .evaluateAll((opts) => opts.map((o) => (o as HTMLOptionElement).value));
    expect(values).toEqual([
      "ASSIGNED_ONLY",
      "BUILDING_READ",
      "BUILDING_READ_AND_ASSIGN",
    ]);
  });
});
