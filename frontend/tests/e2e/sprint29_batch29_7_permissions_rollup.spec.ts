import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.7 — permissions transparency rollup chip.
 *
 * Adds a glance-level rollup chip on the Permissions page user-access
 * cards, on the Customer Users tab rows, and on the User detail
 * Customer access rows. The chip text is "Default" when the (user,
 * customer) pair has no overrides on any of its access rows; otherwise
 * "Custom (N)" where N is the SUM of override keys across every access
 * row for that pair (same key on different buildings counts twice).
 *
 * The chip carries the 29.6 locked testid
 * `user-detail-permissions-link-<customerId>` on the User detail page
 * via its `testId` prop so the 29.6 spec still passes (no contract
 * regression).
 */

type AccessRow = {
  id: number;
  building_id: number;
  permission_overrides?: Record<string, boolean>;
};

interface RollupTarget {
  customerId: number;
  userId: number;
  count: number;
}

interface RollupDefaultTarget {
  customerId: number;
  userId: number;
}

interface ScanResult {
  custom: RollupTarget | null;
  default: RollupDefaultTarget | null;
}

function sumOverrides(rows: AccessRow[]): number {
  return rows.reduce(
    (s, a) => s + Object.keys(a.permission_overrides ?? {}).length,
    0,
  );
}

async function scanForTargets(api: APIRequestContext): Promise<ScanResult> {
  const customersResp = await api.get("/api/customers/?page_size=10");
  expect(customersResp.status()).toBe(200);
  const customersBody = (await customersResp.json()) as {
    results: Array<{ id: number }>;
  };

  let custom: RollupTarget | null = null;
  let defaultTarget: RollupDefaultTarget | null = null;

  for (const c of customersBody.results) {
    const membersResp = await api.get(
      `/api/customers/${c.id}/users/?page_size=50`,
    );
    if (membersResp.status() !== 200) continue;
    const membersBody = (await membersResp.json()) as {
      results: Array<{ user_id: number }>;
    };
    for (const m of membersBody.results) {
      const accessResp = await api.get(
        `/api/customers/${c.id}/users/${m.user_id}/access/`,
      );
      if (accessResp.status() !== 200) continue;
      const accessBody = (await accessResp.json()) as {
        results: AccessRow[];
      };
      const count = sumOverrides(accessBody.results);
      if (count > 0 && !custom) {
        custom = { customerId: c.id, userId: m.user_id, count };
      }
      if (count === 0 && !defaultTarget) {
        // Prefer a default target with at least one access row so the
        // chip render path that handles non-empty accesses-but-zero-
        // overrides is covered too.
        if (accessBody.results.length > 0) {
          defaultTarget = { customerId: c.id, userId: m.user_id };
        }
      }
      if (custom && defaultTarget) return { custom, default: defaultTarget };
    }
  }
  return { custom, default: defaultTarget };
}

async function findAnyAccessForUser(
  api: APIRequestContext,
  customerId: number,
  userId: number,
): Promise<AccessRow | null> {
  const resp = await api.get(
    `/api/customers/${customerId}/users/${userId}/access/`,
  );
  if (resp.status() !== 200) return null;
  const body = (await resp.json()) as { results: AccessRow[] };
  return body.results[0] ?? null;
}

test.describe("Sprint 29 Batch 29.7 — permissions rollup chip", () => {
  // Per-spec shared state. Resolved by the first test that needs it;
  // mutation (when no seed user has overrides) is cleaned up in
  // afterAll.
  let custom: RollupTarget | null = null;
  let defaultTarget: RollupDefaultTarget | null = null;
  let mutatedRevert: {
    customerId: number;
    userId: number;
    buildingId: number;
    original: Record<string, boolean>;
  } | null = null;

  test.beforeAll(async () => {
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      const scan = await scanForTargets(sa);
      custom = scan.custom;
      defaultTarget = scan.default;

      // If no seed user has overrides, mutate one access row on
      // `defaultTarget` so the "Custom (N)" path is testable. We add
      // a single override key; cleanup restores the original
      // permission_overrides map.
      if (!custom && defaultTarget) {
        const row = await findAnyAccessForUser(
          sa,
          defaultTarget.customerId,
          defaultTarget.userId,
        );
        if (row) {
          const original = { ...(row.permission_overrides ?? {}) };
          const patched = { ...original, "customer.ticket.create": true };
          const patchResp = await sa.patch(
            `/api/customers/${defaultTarget.customerId}/users/${defaultTarget.userId}/access/${row.building_id}/`,
            { data: { permission_overrides: patched } },
          );
          expect(
            patchResp.status(),
            "seeding an override on a default user must succeed",
          ).toBe(200);
          mutatedRevert = {
            customerId: defaultTarget.customerId,
            userId: defaultTarget.userId,
            buildingId: row.building_id,
            original,
          };
          custom = {
            customerId: defaultTarget.customerId,
            userId: defaultTarget.userId,
            count: Object.keys(patched).length,
          };
          // The mutated user is now "Custom"; clear the default
          // pointer and try to find another default user.
          defaultTarget = null;
          const rescan = await scanForTargets(sa);
          if (!defaultTarget) defaultTarget = rescan.default;
        }
      }
    } finally {
      await sa.dispose();
    }
  });

  test.afterAll(async () => {
    if (!mutatedRevert) return;
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      await sa.patch(
        `/api/customers/${mutatedRevert.customerId}/users/${mutatedRevert.userId}/access/${mutatedRevert.buildingId}/`,
        { data: { permission_overrides: mutatedRevert.original } },
      );
    } finally {
      await sa.dispose();
    }
  });

  test("Default chip renders on the Permissions page for a no-override user", async ({
    page,
  }) => {
    test.skip(
      defaultTarget === null,
      "no seed user with zero overrides + at least one access row",
    );
    const t = defaultTarget!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    const chip = page.locator(
      `[data-testid="permissions-rollup-chip-${t.userId}"]`,
    );
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toHaveClass(/permissions-rollup-chip-default/);
    await expect(chip).toHaveText(/^(Default|Standaard)$/);
  });

  test("Custom (N) chip renders on the Permissions page and N matches the API", async ({
    page,
  }) => {
    test.skip(
      custom === null,
      "no seed user with overrides and seeding failed",
    );
    const t = custom!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    const chip = page.locator(
      `[data-testid="permissions-rollup-chip-${t.userId}"]`,
    );
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toHaveClass(/permissions-rollup-chip-custom/);
    const text = (await chip.textContent())?.trim() ?? "";
    const match = text.match(/^(?:Custom|Aangepast) \((\d+)\)$/);
    expect(match, `chip text "${text}" matches the rollup format`).not.toBeNull();
    expect(Number(match![1])).toBe(t.count);
  });

  test("clicking the chip toggles the inline summary; Open full editor deep-links", async ({
    page,
  }) => {
    // Sprint 29 Batch 29.8.5 — the chip became a toggle button that
    // opens an inline <PermissionsRollupSummary> rather than
    // navigating away. The deep-link path is now under the summary's
    // explicit "Open full editor" link.
    test.skip(
      custom === null,
      "no seed user with overrides and seeding failed",
    );
    const t = custom!;

    await loginAs(page, DEMO_USERS.super);
    // Click the chip from the Customer Users tab to prove the toggle
    // works from a different surface (not just the Permissions
    // page itself).
    await page.goto(`/admin/customers/${t.customerId}/users`);

    const chip = page
      .locator(`[data-testid="permissions-rollup-chip-${t.userId}"]`)
      .first();
    await expect(chip).toBeVisible({ timeout: 10_000 });

    await chip.click();

    const openFull = page.locator(
      `[data-testid="permissions-rollup-summary-open-full-${t.userId}-${t.customerId}"]`,
    );
    await expect(openFull).toBeVisible({ timeout: 10_000 });

    await openFull.click();

    await page.waitForURL(
      (url) =>
        url.pathname === `/admin/customers/${t.customerId}/permissions` &&
        url.search.includes(`focus_user=${t.userId}`),
      { timeout: 10_000 },
    );

    const card = page.locator(`#user-access-card-${t.userId}`);
    await expect(card).toBeVisible({ timeout: 10_000 });
    await expect(card).toBeInViewport();
  });

  test("Customer Users tab renders the rollup chip on at least one row", async ({
    page,
  }) => {
    const t = custom ?? defaultTarget;
    test.skip(t === null, "no targets available");

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t!.customerId}/users`);

    const chip = page.locator(
      `[data-testid="permissions-rollup-chip-${t!.userId}"]`,
    );
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toHaveClass(/permissions-rollup-chip/);
  });

  test("User detail page chip carries the 29.6 locked testid and toggles the inline summary", async ({
    page,
  }) => {
    // Sprint 29 Batch 29.8.5 — the chip became a toggle button. The
    // 29.6 testid contract holds (via the `testId` prop), but href
    // is no longer set; the deep-link moved to the summary's
    // "Open full editor" link.
    const t = custom ?? defaultTarget;
    test.skip(t === null, "no targets available");

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/users/${t!.userId}`);

    await expect(
      page.locator('[data-testid="user-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // 29.6 contract: the per-customer chip on the Customer access
    // card MUST still expose
    // `user-detail-permissions-link-<customerId>`. 29.7 retains the
    // testid via the chip's `testId` prop; 29.8.5 keeps it.
    const chip = page.locator(
      `[data-testid="user-detail-permissions-link-${t!.customerId}"]`,
    );
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toHaveClass(/permissions-rollup-chip/);

    // 29.8.5 — clicking the chip opens the inline summary panel
    // instead of navigating away.
    await chip.click();
    const summary = page.locator(
      `[data-testid="permissions-rollup-summary-${t!.userId}-${t!.customerId}"]`,
    );
    await expect(summary).toBeVisible({ timeout: 10_000 });

    // The summary's "Open full editor" link is the new deep-link
    // affordance and points at the same Permissions page URL.
    const openFull = page.locator(
      `[data-testid="permissions-rollup-summary-open-full-${t!.userId}-${t!.customerId}"]`,
    );
    const href = await openFull.getAttribute("href");
    expect(href).toBe(
      `/admin/customers/${t!.customerId}/permissions?focus_user=${t!.userId}`,
    );
  });
});
