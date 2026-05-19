import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.8.5 — permissions visibility surfaces.
 *
 * The previous "Custom (N)" / "Default" affordances were navigation
 * jump-offs — clicking either dropped the operator into the editor or
 * a different page with no glance-level view of WHO can do WHAT. Batch
 * 29.8.5 turns both into in-place toggles:
 *
 *   - On the Permissions page the per-building "N custom permissions"
 *     pill toggles an inline `<AccessPermissionsPanel>` that lists all
 *     16 effective customer-permission rows with grant/deny indicators
 *     and a reason annotation. An explicit "Edit overrides" button
 *     inside the panel opens the legacy OverrideDrawer when the
 *     operator actually wants to mutate.
 *
 *   - The per-customer rollup chip (Permissions page user-card header,
 *     Customer Users tab row, AND User detail customer-access card)
 *     becomes a toggle button that opens an inline
 *     `<PermissionsRollupSummary>` panel listing one row per access
 *     with its effective sub-role + override count + an Edit link.
 *
 * Locked testid contract (verified against the in-place
 * implementation):
 *   - `access-permissions-panel-<accessId>`         (panel root)
 *   - `access-permissions-edit-<accessId>`          (Edit button)
 *   - `access-permission-row-<accessId>-<key>`      (16 grant/deny rows)
 *   - `permissions-rollup-summary-<userId>-<customerId>`            (summary root)
 *   - `permissions-rollup-summary-collapse-<userId>-<customerId>`   (collapse button)
 *   - `permissions-rollup-summary-open-full-<userId>-<customerId>`  (deep-link)
 *   - `permissions-rollup-summary-row-<accessId>`                   (per-access row)
 *   - `permissions-rollup-summary-edit-<accessId>`                  (per-row edit)
 *
 * Preserved from earlier sprints (29.6 / 29.7 locks):
 *   - `permissions-rollup-chip-<userId>`               (chip root)
 *   - `user-detail-permissions-link-<customerId>`      (chip on user detail)
 *   - `customer-access-overrides-button`               (the per-building pill)
 *   - `section-customer-overrides-editor`              (drawer root)
 *   - `customer-overrides-close`                       (drawer close)
 */

type AccessRow = {
  id: number;
  building_id: number;
  permission_overrides?: Record<string, boolean>;
};

interface OverrideTarget {
  customerId: number;
  userId: number;
  accessId: number;
  buildingId: number;
}

async function scanForOverrideTarget(
  api: APIRequestContext,
): Promise<OverrideTarget | null> {
  const customersResp = await api.get("/api/customers/?page_size=10");
  if (customersResp.status() !== 200) return null;
  const customersBody = (await customersResp.json()) as {
    results: Array<{ id: number }>;
  };

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
      const accessBody = (await accessResp.json()) as { results: AccessRow[] };
      for (const row of accessBody.results) {
        if (Object.keys(row.permission_overrides ?? {}).length > 0) {
          return {
            customerId: c.id,
            userId: m.user_id,
            accessId: row.id,
            buildingId: row.building_id,
          };
        }
      }
    }
  }
  return null;
}

interface AnyAccessTarget {
  customerId: number;
  userId: number;
  accessId: number;
  buildingId: number;
}

async function scanForAnyAccess(
  api: APIRequestContext,
): Promise<AnyAccessTarget | null> {
  const customersResp = await api.get("/api/customers/?page_size=10");
  if (customersResp.status() !== 200) return null;
  const customersBody = (await customersResp.json()) as {
    results: Array<{ id: number }>;
  };

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
      const accessBody = (await accessResp.json()) as { results: AccessRow[] };
      const first = accessBody.results[0];
      if (first) {
        return {
          customerId: c.id,
          userId: m.user_id,
          accessId: first.id,
          buildingId: first.building_id,
        };
      }
    }
  }
  return null;
}

async function patchOverrides(
  api: APIRequestContext,
  customerId: number,
  userId: number,
  buildingId: number,
  overrides: Record<string, boolean>,
): Promise<void> {
  const resp = await api.patch(
    `/api/customers/${customerId}/users/${userId}/access/${buildingId}/`,
    { data: { permission_overrides: overrides } },
  );
  expect(resp.status()).toBe(200);
}

/**
 * Open the per-building pill that backs the AccessPermissionsPanel
 * for the (userId, buildingId) pair. The pill carries the preserved
 * `customer-access-overrides-button` testid plus both
 * `data-user-id` and `data-building-id` discriminators (multiple
 * users on the Permissions page can share the same building id).
 */
async function openPanelForAccess(
  page: Page,
  userId: number,
  buildingId: number,
): Promise<void> {
  const pill = page.locator(
    `[data-testid="customer-access-overrides-button"][data-user-id="${userId}"][data-building-id="${buildingId}"]`,
  );
  await expect(pill).toBeVisible({ timeout: 10_000 });
  await pill.scrollIntoViewIfNeeded();
  await pill.click();
}

test.describe("Sprint 29 Batch 29.8.5 — permissions visibility surfaces", () => {
  let overrideTarget: OverrideTarget | null = null;
  let anyAccess: AnyAccessTarget | null = null;
  let mutatedRevert: {
    customerId: number;
    userId: number;
    buildingId: number;
    original: Record<string, boolean>;
  } | null = null;

  test.beforeAll(async () => {
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      overrideTarget = await scanForOverrideTarget(sa);
      anyAccess = await scanForAnyAccess(sa);

      // If the demo seed lacks any access with non-empty overrides we
      // seed one in beforeAll and revert it in afterAll. The 29.7
      // spec uses the same trick so the contract test is exercised on
      // a clean seed too.
      if (!overrideTarget && anyAccess) {
        const accessResp = await sa.get(
          `/api/customers/${anyAccess.customerId}/users/${anyAccess.userId}/access/`,
        );
        if (accessResp.status() === 200) {
          const body = (await accessResp.json()) as { results: AccessRow[] };
          const row = body.results.find((r) => r.id === anyAccess!.accessId);
          if (row) {
            const original = { ...(row.permission_overrides ?? {}) };
            const patched = { ...original, "customer.ticket.create": true };
            await patchOverrides(
              sa,
              anyAccess.customerId,
              anyAccess.userId,
              anyAccess.buildingId,
              patched,
            );
            mutatedRevert = {
              customerId: anyAccess.customerId,
              userId: anyAccess.userId,
              buildingId: anyAccess.buildingId,
              original,
            };
            overrideTarget = {
              customerId: anyAccess.customerId,
              userId: anyAccess.userId,
              accessId: anyAccess.accessId,
              buildingId: anyAccess.buildingId,
            };
          }
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

  test("Per-building inline panel opens on the Permissions page with all 16 rows", async ({
    page,
  }) => {
    test.skip(
      overrideTarget === null,
      "no access row with permission_overrides + seeding fallback failed",
    );
    const t = overrideTarget!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    await openPanelForAccess(page, t.userId, t.buildingId);

    const panel = page.locator(
      `[data-testid="access-permissions-panel-${t.accessId}"]`,
    );
    await expect(panel).toBeVisible({ timeout: 10_000 });

    // 16 customer-permission keys must each render a row inside the
    // panel — same count contract as the OverrideDrawer table.
    const rows = panel.locator(
      `[data-testid^="access-permission-row-${t.accessId}-"]`,
    );
    await expect(rows).toHaveCount(16);

    // At least one row should be granted (the seeded "customer.ticket.create"
    // override above, or whatever non-empty overrides the seed
    // shipped). We assert via the `data-granted="true"` discriminator
    // rather than a class-name match to keep the contract structural.
    const grantedRows = panel.locator(
      `[data-testid^="access-permission-row-${t.accessId}-"][data-granted="true"]`,
    );
    expect(await grantedRows.count()).toBeGreaterThan(0);

    // Collapse via the inline panel's own Collapse button — panel
    // disappears.
    await panel.getByRole("button", { name: /collapse|inklappen/i }).click();
    await expect(panel).toHaveCount(0);
  });

  test("Edit overrides button on the inline panel opens the override drawer", async ({
    page,
  }) => {
    test.skip(
      overrideTarget === null,
      "no access row with permission_overrides + seeding fallback failed",
    );
    const t = overrideTarget!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    await openPanelForAccess(page, t.userId, t.buildingId);

    const panel = page.locator(
      `[data-testid="access-permissions-panel-${t.accessId}"]`,
    );
    await expect(panel).toBeVisible({ timeout: 10_000 });

    // The inline panel's "Edit overrides" button opens the legacy
    // OverrideDrawer for the same access row. Clicking it implicitly
    // collapses the panel (per UserAccessCard.onEditClick).
    await page
      .locator(`[data-testid="access-permissions-edit-${t.accessId}"]`)
      .click();

    const drawer = page.locator(
      '[data-testid="section-customer-overrides-editor"]',
    );
    await expect(drawer).toBeVisible({ timeout: 10_000 });

    // Close via the locked close button — drawer disappears.
    await page.locator('[data-testid="customer-overrides-close"]').click();
    await expect(drawer).toHaveCount(0);
  });

  test("User detail rollup chip toggles the inline summary panel", async ({
    page,
  }) => {
    const t = overrideTarget ?? anyAccess;
    test.skip(
      t === null,
      "no targets discoverable (no customer access rows in seed)",
    );

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/users/${t!.userId}`);

    await expect(
      page.locator('[data-testid="user-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Preserved 29.6 contract: the chip on the User detail customer-
    // access card exposes `user-detail-permissions-link-<customerId>`
    // via the chip's testId override.
    const chip = page.locator(
      `[data-testid="user-detail-permissions-link-${t!.customerId}"]`,
    );
    await expect(chip).toBeVisible({ timeout: 10_000 });

    await chip.click();

    const summary = page.locator(
      `[data-testid="permissions-rollup-summary-${t!.userId}-${t!.customerId}"]`,
    );
    await expect(summary).toBeVisible({ timeout: 10_000 });

    // At least one per-access row must render — the user has at
    // least one access row (`anyAccess` enforces this).
    const summaryRows = summary.locator(
      '[data-testid^="permissions-rollup-summary-row-"]',
    );
    expect(await summaryRows.count()).toBeGreaterThan(0);

    // Collapse via the summary's own Collapse button — summary
    // disappears.
    await page
      .locator(
        `[data-testid="permissions-rollup-summary-collapse-${t!.userId}-${t!.customerId}"]`,
      )
      .click();
    await expect(summary).toHaveCount(0);
  });
});
