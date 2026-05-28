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
 *   - On the Permissions page the per-access inline panel is replaced
 *     in Sprint 31 Phase 6 by an Excel-style matrix: one row per
 *     access with 16 `permissions-matrix-cell` cells (one per
 *     customer-permission key) showing effective state via
 *     `data-effective` + `data-policy-blocked` discriminators. The
 *     pill testid `customer-access-overrides-button` is preserved on
 *     the row's "Edit permissions" button; clicking it opens the
 *     PermissionEditorModal directly — no intermediate panel.
 *
 *   - The per-customer rollup chip (Permissions page user-card header,
 *     Customer Users tab row, AND User detail customer-access card)
 *     becomes a toggle button that opens an inline
 *     `<PermissionsRollupSummary>` panel listing one row per access
 *     with its effective sub-role + override count + an Edit link.
 *
 * Locked testid contract (verified against the in-place
 * implementation):
 *   - `permissions-matrix-row` + data-user-id + data-building-id    (matrix row)
 *   - `permissions-matrix-cell` + data-permission-key + data-effective + data-policy-blocked
 *   - `permissions-rollup-summary-<userId>-<customerId>`            (summary root)
 *   - `permissions-rollup-summary-collapse-<userId>-<customerId>`   (collapse button)
 *   - `permissions-rollup-summary-open-full-<userId>-<customerId>`  (deep-link)
 *   - `permissions-rollup-summary-row-<accessId>`                   (per-access row)
 *   - `permissions-rollup-summary-edit-<accessId>`                  (per-row edit)
 *
 * Preserved from earlier sprints (29.6 / 29.7 locks):
 *   - `permissions-rollup-chip-<userId>`               (chip root)
 *   - `user-detail-permissions-link-<customerId>`      (chip on user detail)
 *   - `customer-access-overrides-button`               (row Edit button)
 *   - `section-customer-overrides-editor`              (modal root, was drawer)
 *   - `customer-overrides-close`                       (modal close)
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
// Sprint 31 Phase 6 — the per-access pill that used to toggle the
// inline AccessPermissionsPanel is now the matrix row's "Edit
// permissions" button. The testid + data-* discriminators are
// preserved verbatim, and a click now opens the PermissionEditorModal
// directly (no intermediate panel step).
async function openModalForAccess(
  page: Page,
  userId: number,
  buildingId: number,
): Promise<void> {
  const button = page.locator(
    `[data-testid="customer-access-overrides-button"][data-user-id="${userId}"][data-building-id="${buildingId}"]`,
  );
  await expect(button).toBeVisible({ timeout: 10_000 });
  await button.scrollIntoViewIfNeeded();
  await button.click();
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

  test("Permissions matrix renders 16 cells per access row with effective state", async ({
    page,
  }) => {
    // Sprint 31 Phase 6 — replaces the per-access inline panel with a
    // matrix row. Each matrix row carries 16 `permissions-matrix-cell`
    // cells (one per customer-permission key); cells expose
    // `data-effective="granted|denied"` + `data-policy-blocked` so a
    // spec can assert state structurally without parsing class names.
    test.skip(
      overrideTarget === null,
      "no access row with permission_overrides + seeding fallback failed",
    );
    const t = overrideTarget!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    const row = page.locator(
      `[data-testid="permissions-matrix-row"][data-user-id="${t.userId}"][data-building-id="${t.buildingId}"]`,
    );
    await expect(row).toBeVisible({ timeout: 10_000 });

    // 16 customer-permission keys -> 16 cells per row, same contract
    // the panel used to provide.
    const cells = row.locator('[data-testid="permissions-matrix-cell"]');
    await expect(cells).toHaveCount(16);

    // At least one cell should be granted (the seeded
    // "customer.ticket.create" override above, or whatever non-empty
    // overrides the seed shipped). Assert via the structural
    // `data-effective` discriminator.
    const grantedCells = row.locator(
      '[data-testid="permissions-matrix-cell"][data-effective="granted"]',
    );
    expect(await grantedCells.count()).toBeGreaterThan(0);
  });

  test("Edit permissions button on the matrix row opens the modal", async ({
    page,
  }) => {
    // Sprint 31 Phase 6 — the Edit permissions button on each matrix
    // row (locked testid `customer-access-overrides-button` preserved
    // verbatim with `data-user-id` + `data-building-id`) opens the
    // PermissionEditorModal directly; no intermediate panel step.
    test.skip(
      overrideTarget === null,
      "no access row with permission_overrides + seeding fallback failed",
    );
    const t = overrideTarget!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/admin/customers/${t.customerId}/permissions`);

    await openModalForAccess(page, t.userId, t.buildingId);

    const modal = page.locator(
      '[data-testid="section-customer-overrides-editor"]',
    );
    await expect(modal).toBeVisible({ timeout: 10_000 });

    // Close via the locked close button — modal disappears.
    await page.locator('[data-testid="customer-overrides-close"]').click();
    await expect(modal).toHaveCount(0);
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
