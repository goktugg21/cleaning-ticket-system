import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 5 — Provider-wide service catalog admin page.
 *
 * Coverage:
 *   1. Top-level sidebar shows the "Services" link for SUPER_ADMIN.
 *   2. `/admin/services` renders the real page; the Services tab is
 *      the default-active tab.
 *   3. Adding a category via the modal makes it appear on the
 *      Categories tab.
 *   4. Adding a service via the modal makes it appear on the
 *      Services tab.
 *   5. Editing a service from the detail panel updates the row.
 *   6. Deleting a category that still has services attached fails
 *      gracefully (backend returns 400 from ProtectedError); the
 *      category remains in the list afterwards.
 *
 * Auth: SUPER_ADMIN — gives access to both companies' catalog rows
 * and the broadest test surface. The backend gates list/CRUD with
 * SUPER_ADMIN or COMPANY_ADMIN of ANY company; a separate batch will
 * exercise the COMPANY_ADMIN path explicitly.
 *
 * Cleanup: every test that creates rows deletes them via the API
 * at the end so the suite is rerunnable without a reseed.
 */

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  const MAX_ATTEMPTS = 3;
  const THROTTLE_BACKOFF_MS = 35_000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const loginCtx = await request.newContext({
      baseURL,
      ignoreHTTPSErrors: true,
    });
    const tokenResponse = await loginCtx.post("/api/auth/token/", {
      data: { email, password },
    });
    const status = tokenResponse.status();
    if (status === 200) {
      const body = (await tokenResponse.json()) as { access: string };
      await loginCtx.dispose();
      return await request.newContext({
        baseURL,
        ignoreHTTPSErrors: true,
        extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
      });
    }
    await loginCtx.dispose();
    if (status === 429 && attempt < MAX_ATTEMPTS) {
      await new Promise((r) => setTimeout(r, THROTTLE_BACKOFF_MS));
      continue;
    }
    expect(
      status,
      `token request for ${email} should succeed (attempt ${attempt})`,
    ).toBe(200);
  }
  throw new Error(`apiAs(${email}) exhausted attempts`);
}

interface CategoryRow {
  id: number;
  name: string;
}

interface ServiceRow {
  id: number;
  name: string;
  category: number;
}

async function findCategoryByName(
  api: APIRequestContext,
  name: string,
): Promise<CategoryRow | null> {
  const response = await api.get("/api/services/categories/?page_size=200");
  if (response.status() !== 200) return null;
  const body = (await response.json()) as { results: CategoryRow[] };
  return body.results.find((c) => c.name === name) ?? null;
}

async function findServiceByName(
  api: APIRequestContext,
  name: string,
): Promise<ServiceRow | null> {
  const response = await api.get("/api/services/?page_size=200");
  if (response.status() !== 200) return null;
  const body = (await response.json()) as { results: ServiceRow[] };
  return body.results.find((s) => s.name === name) ?? null;
}

async function deleteCategoryById(
  api: APIRequestContext,
  id: number,
): Promise<void> {
  const response = await api.delete(`/api/services/categories/${id}/`);
  expect([204, 400, 404]).toContain(response.status());
}

async function deleteServiceById(
  api: APIRequestContext,
  id: number,
): Promise<void> {
  const response = await api.delete(`/api/services/${id}/`);
  expect([204, 404]).toContain(response.status());
}

test("Sprint 28 B5 — Top-level sidebar shows Services entry for SUPER_ADMIN", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  // Land on the top-level dashboard.
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await expect(page.locator("[data-testid='sidebar-services']")).toBeVisible({
    timeout: 10_000,
  });
});

test("Sprint 28 B5 — /admin/services renders, Services tab is the default", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  await page.goto("/admin/services");
  await page.waitForLoadState("networkidle");

  await expect(
    page.locator("[data-testid='services-admin-page']"),
  ).toBeVisible({ timeout: 10_000 });

  // Default tab is Services.
  const servicesTab = page.locator("[data-testid='services-tab-services']");
  await expect(servicesTab).toHaveAttribute("aria-selected", "true");
  await expect(
    page.locator("[data-testid='services-services-list']"),
  ).toBeVisible();
});

test("Sprint 28 B5 — Add category modal: save shows row on Categories tab", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const uniqueName = `Cat Test ${Date.now()}`;

  try {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/services");
    await page.waitForLoadState("networkidle");

    // Switch to Categories tab and open the Add modal.
    await page.locator("[data-testid='services-tab-categories']").click();
    await page
      .locator("[data-testid='services-add-category-button']")
      .click();

    const modal = page.locator("[data-testid='services-category-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal
      .locator("[data-testid='services-category-input-name']")
      .fill(uniqueName);
    await modal
      .locator("[data-testid='services-category-input-description']")
      .fill("Created via Playwright");

    await modal
      .locator("[data-testid='services-category-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    const newRow = page.locator("[data-testid='services-category-row']", {
      hasText: uniqueName,
    });
    await expect(newRow).toBeVisible({ timeout: 10_000 });
  } finally {
    const found = await findCategoryByName(sa, uniqueName);
    if (found) await deleteCategoryById(sa, found.id);
    await sa.dispose();
  }
});

test("Sprint 28 B5 — Add service modal: save shows row on Services tab", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);

  // Make sure at least one category exists; create one for the
  // test so the spec is self-contained.
  const categoryName = `Cat For Service ${Date.now()}`;
  const createCatResponse = await sa.post("/api/services/categories/", {
    data: { name: categoryName, description: "", is_active: true },
  });
  expect(createCatResponse.status()).toBe(201);
  const createdCat = (await createCatResponse.json()) as { id: number };

  const uniqueServiceName = `Svc Test ${Date.now()}`;

  try {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/services");
    await page.waitForLoadState("networkidle");

    await page.locator("[data-testid='services-add-service-button']").click();

    const modal = page.locator("[data-testid='services-service-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Pick the category we just created.
    await modal
      .locator("[data-testid='services-service-input-category']")
      .selectOption({ value: String(createdCat.id) });

    await modal
      .locator("[data-testid='services-service-input-name']")
      .fill(uniqueServiceName);
    await modal
      .locator("[data-testid='services-service-input-unit-type']")
      .selectOption({ value: "FIXED" });
    const priceInput = modal.locator(
      "[data-testid='services-service-input-default-unit-price']",
    );
    await priceInput.fill("");
    await priceInput.fill("100.00");

    await modal
      .locator("[data-testid='services-service-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // Row appears on the Services tab (default-active).
    const newRow = page.locator("[data-testid='services-service-row']", {
      hasText: uniqueServiceName,
    });
    await expect(newRow).toBeVisible({ timeout: 10_000 });
  } finally {
    const foundService = await findServiceByName(sa, uniqueServiceName);
    if (foundService) await deleteServiceById(sa, foundService.id);
    await deleteCategoryById(sa, createdCat.id);
    await sa.dispose();
  }
});

test("Sprint 28 B5 — Edit service: change name, list reflects new name", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);

  // Seed via API so the test does not depend on prior test ordering.
  const categoryName = `Cat Edit ${Date.now()}`;
  const createCatResponse = await sa.post("/api/services/categories/", {
    data: { name: categoryName, description: "", is_active: true },
  });
  expect(createCatResponse.status()).toBe(201);
  const createdCat = (await createCatResponse.json()) as { id: number };

  const initialName = `Svc Edit Init ${Date.now()}`;
  const createSvcResponse = await sa.post("/api/services/", {
    data: {
      category: createdCat.id,
      name: initialName,
      description: "",
      unit_type: "HOURS",
      default_unit_price: "50.00",
      default_vat_pct: "21.00",
      is_active: true,
    },
  });
  expect(createSvcResponse.status()).toBe(201);
  const createdSvc = (await createSvcResponse.json()) as { id: number };

  const newName = `Svc Edit Updated ${Date.now()}`;

  try {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/services");
    await page.waitForLoadState("networkidle");

    const row = page
      .locator("[data-testid='services-service-row']", {
        hasText: initialName,
      })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    const detail = page.locator("[data-testid='services-service-detail']");
    await expect(detail).toBeVisible({ timeout: 5_000 });

    await detail
      .locator("[data-testid='services-service-edit-button']")
      .click();

    const modal = page.locator("[data-testid='services-service-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const nameInput = modal.locator(
      "[data-testid='services-service-input-name']",
    );
    await nameInput.fill("");
    await nameInput.fill(newName);

    await modal
      .locator("[data-testid='services-service-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // List shows the new name.
    await expect(
      page
        .locator("[data-testid='services-service-row']", { hasText: newName })
        .first(),
    ).toBeVisible({ timeout: 10_000 });
  } finally {
    await deleteServiceById(sa, createdSvc.id);
    await deleteCategoryById(sa, createdCat.id);
    await sa.dispose();
  }
});

test("Sprint 28 B5 — Deleting a category with services attached fails gracefully", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);

  const categoryName = `Cat Protected ${Date.now()}`;
  const createCatResponse = await sa.post("/api/services/categories/", {
    data: { name: categoryName, description: "", is_active: true },
  });
  expect(createCatResponse.status()).toBe(201);
  const createdCat = (await createCatResponse.json()) as { id: number };

  // Attach a service to make the category protected.
  const serviceName = `Svc Protect ${Date.now()}`;
  const createSvcResponse = await sa.post("/api/services/", {
    data: {
      category: createdCat.id,
      name: serviceName,
      description: "",
      unit_type: "HOURS",
      default_unit_price: "50.00",
      default_vat_pct: "21.00",
      is_active: true,
    },
  });
  expect(createSvcResponse.status()).toBe(201);
  const createdSvc = (await createSvcResponse.json()) as { id: number };

  try {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/admin/services");
    await page.waitForLoadState("networkidle");

    await page.locator("[data-testid='services-tab-categories']").click();

    const row = page
      .locator("[data-testid='services-category-row']", {
        hasText: categoryName,
      })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    const detail = page.locator("[data-testid='services-category-detail']");
    await expect(detail).toBeVisible({ timeout: 5_000 });

    await detail
      .locator("[data-testid='services-category-delete-button']")
      .click();

    // The ConfirmDialog is a native <dialog>. Confirm via the button
    // whose text matches the "Delete" label.
    const confirmDialog = page.locator("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5_000 });
    await confirmDialog.locator(".btn-primary").click();

    // After the failed delete, the category should still be present.
    // The dialog closes regardless (the page surfaces the error via
    // an alert banner). Reload to take the cleanest read.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.locator("[data-testid='services-tab-categories']").click();
    await expect(
      page
        .locator("[data-testid='services-category-row']", {
          hasText: categoryName,
        })
        .first(),
    ).toBeVisible({ timeout: 10_000 });
  } finally {
    await deleteServiceById(sa, createdSvc.id);
    await deleteCategoryById(sa, createdCat.id);
    await sa.dispose();
  }
});
