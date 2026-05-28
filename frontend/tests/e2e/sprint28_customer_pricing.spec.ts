import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 5 — Per-customer pricing page.
 *
 * Coverage:
 *   1. Customer-scoped sidebar shows the "Pricing" entry on a
 *      customer deep link.
 *   2. `/admin/customers/<id>/pricing` renders the real page; the
 *      list is empty initially for a customer with no pricing rows.
 *   3. Adding a price (service + unit_price + valid_from) makes
 *      a row appear in the list.
 *   4. Editing a price changes its unit_price in the list.
 *   5. Setting `valid_to` before `valid_from` shows the inline
 *      error and does not submit.
 *
 * Auth: COMPANY_ADMIN of Osius Demo for the customer-scoped reads.
 * The backend gate matches SUPER_ADMIN or COMPANY_ADMIN of the
 * customer's provider company; using the narrower role keeps the
 * test honest about the COMPANY_ADMIN path.
 *
 * Customer id resolution: look up "B Amsterdam" via the customers
 * list endpoint — same pattern as `sprint28b_customer_sidebar.spec.ts`
 * and `sprint28_contacts.spec.ts`.
 *
 * Cleanup: tests delete all rows they create through the backend at
 * the end so the suite is rerunnable.
 */

const OSIUS_CUSTOMER_NAME = "B Amsterdam";

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

async function resolveCustomerId(
  api: APIRequestContext,
  customerName: string,
): Promise<number> {
  const response = await api.get("/api/customers/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match = body.results.find((c) => c.name === customerName);
  expect(match, `customer ${customerName} present`).toBeTruthy();
  return match!.id;
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

interface PriceRow {
  id: number;
  service: number;
  unit_price: string;
}

async function ensureSeedService(
  api: APIRequestContext,
): Promise<{ category: CategoryRow; service: ServiceRow }> {
  // Use a deterministic unique seed name so parallel test workers do not
  // collide. Each invocation creates its own category + service pair so
  // we can clean up without affecting other suites.
  const ts = Date.now();
  const categoryName = `Pricing Cat ${ts} ${Math.random()
    .toString(36)
    .slice(2, 7)}`;
  const catResponse = await api.post("/api/services/categories/", {
    data: { name: categoryName, description: "", is_active: true },
  });
  expect(catResponse.status()).toBe(201);
  const cat = (await catResponse.json()) as CategoryRow;

  const serviceName = `Pricing Svc ${ts} ${Math.random()
    .toString(36)
    .slice(2, 7)}`;
  const svcResponse = await api.post("/api/services/", {
    data: {
      category: cat.id,
      name: serviceName,
      description: "",
      unit_type: "FIXED",
      default_unit_price: "75.00",
      default_vat_pct: "21.00",
      is_active: true,
    },
  });
  expect(svcResponse.status()).toBe(201);
  const svc = (await svcResponse.json()) as ServiceRow;

  return { category: cat, service: svc };
}

async function deleteSeedService(
  api: APIRequestContext,
  category: CategoryRow,
  service: ServiceRow,
): Promise<void> {
  await api.delete(`/api/services/${service.id}/`);
  await api.delete(`/api/services/categories/${category.id}/`);
}

async function deletePriceById(
  api: APIRequestContext,
  customerId: number,
  priceId: number,
): Promise<void> {
  const response = await api.delete(
    `/api/customers/${customerId}/pricing/${priceId}/`,
  );
  expect([204, 404]).toContain(response.status());
}

async function listPricesForService(
  api: APIRequestContext,
  customerId: number,
  serviceId: number,
): Promise<PriceRow[]> {
  const response = await api.get(
    `/api/customers/${customerId}/pricing/?service=${serviceId}`,
  );
  if (response.status() !== 200) return [];
  const body = (await response.json()) as { results: PriceRow[] };
  return body.results;
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

test("Sprint 28 B5 — Customer-scoped sidebar shows Pricing entry", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}`);
  await page.waitForLoadState("networkidle");

  await expect(
    page.locator("[data-testid='sidebar-customer-pricing']"),
  ).toBeVisible({ timeout: 10_000 });
});

test("Sprint 28 B5 — /admin/customers/:id/pricing renders the page", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}/pricing`);
  await page.waitForLoadState("networkidle");

  await expect(
    page.locator("[data-testid='customer-pricing-page']"),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator("[data-testid='customer-pricing-add-button']"),
  ).toBeVisible();
});

test("Sprint 28 B5 — Add price: pick service, fill price, save, row appears", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa);

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/pricing`);
    await page.waitForLoadState("networkidle");

    await page.locator("[data-testid='customer-pricing-add-button']").click();

    const modal = page.locator("[data-testid='customer-pricing-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal
      .locator("[data-testid='customer-pricing-input-service']")
      .selectOption({ value: String(service.id) });

    const priceInput = modal.locator(
      "[data-testid='customer-pricing-input-unit-price']",
    );
    await priceInput.fill("");
    await priceInput.fill("42.00");

    // valid_from defaults to today; just confirm it is filled.
    const fromInput = modal.locator(
      "[data-testid='customer-pricing-input-valid-from']",
    );
    await expect(fromInput).toHaveValue(todayISO());

    await modal
      .locator("[data-testid='customer-pricing-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    const newRow = page
      .locator("[data-testid='customer-pricing-row']", {
        hasText: service.name,
      })
      .first();
    await expect(newRow).toBeVisible({ timeout: 10_000 });
    await expect(newRow).toContainText("42.00");
  } finally {
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("Sprint 28 B5 — Edit price: change unit_price, list reflects new value", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa);

  // Seed an initial price via the API.
  const createResponse = await sa.post(
    `/api/customers/${customerId}/pricing/`,
    {
      data: {
        service: service.id,
        unit_price: "30.00",
        vat_pct: "21.00",
        valid_from: todayISO(),
        valid_to: null,
        is_active: true,
      },
    },
  );
  expect(createResponse.status()).toBe(201);

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/pricing`);
    await page.waitForLoadState("networkidle");

    const row = page
      .locator("[data-testid='customer-pricing-row']", {
        hasText: service.name,
      })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    const detail = page.locator("[data-testid='customer-pricing-detail']");
    await expect(detail).toBeVisible({ timeout: 5_000 });

    await detail
      .locator("[data-testid='customer-pricing-edit-button']")
      .click();

    const modal = page.locator("[data-testid='customer-pricing-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const priceInput = modal.locator(
      "[data-testid='customer-pricing-input-unit-price']",
    );
    await priceInput.fill("");
    await priceInput.fill("99.50");

    await modal
      .locator("[data-testid='customer-pricing-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    const updatedRow = page
      .locator("[data-testid='customer-pricing-row']", {
        hasText: service.name,
      })
      .first();
    await expect(updatedRow).toContainText("99.50");
  } finally {
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("Sprint 28 B5 — valid_to before valid_from shows inline error", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa);

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/pricing`);
    await page.waitForLoadState("networkidle");

    await page.locator("[data-testid='customer-pricing-add-button']").click();

    const modal = page.locator("[data-testid='customer-pricing-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal
      .locator("[data-testid='customer-pricing-input-service']")
      .selectOption({ value: String(service.id) });

    // Set valid_from = today, valid_to = yesterday — invalid pair.
    const today = todayISO();
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);
    const yesterdayISO = `${yesterday.getFullYear()}-${String(
      yesterday.getMonth() + 1,
    ).padStart(2, "0")}-${String(yesterday.getDate()).padStart(2, "0")}`;

    await modal
      .locator("[data-testid='customer-pricing-input-valid-from']")
      .fill(today);
    await modal
      .locator("[data-testid='customer-pricing-input-valid-to']")
      .fill(yesterdayISO);

    await modal
      .locator("[data-testid='customer-pricing-modal-save']")
      .click();

    // The modal stays open and shows the inline error.
    await expect(
      modal.locator("[data-testid='customer-pricing-modal-error']"),
    ).toBeVisible({ timeout: 5_000 });
    await expect(modal).toBeVisible();

    // No price row was created.
    const existing = await listPricesForService(sa, customerId, service.id);
    expect(existing.length).toBe(0);
  } finally {
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});
