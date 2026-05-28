import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 6 — Extra Work cart UI.
 *
 * Coverage:
 *   1. Customer submits a cart with one priced line → INSTANT banner.
 *   2. Customer submits a cart with one unpriced line → PROPOSAL
 *      banner.
 *   3. Empty cart blocks submission (inline error, no API call).
 *   4. Duplicate service blocks submission (inline error).
 *   5. After a successful submission, the detail page renders the
 *      cart line item correctly (service / quantity / requested_date
 *      / customer_note).
 *
 * Auth: CUSTOMER_USER (Tom Verbeek) for the UI flows; SUPER_ADMIN
 * via the REST API for seeding/cleanup so the catalog rows the
 * customer needs actually exist.
 *
 * Customer / building resolution: look up "B Amsterdam" + "B1
 * Amsterdam" via the list endpoints — same dynamic-id pattern as
 * `sprint28_customer_pricing.spec.ts`.
 *
 * Cleanup: every seeded service / pricing row / ExtraWorkRequest is
 * deleted via the API at the end so the suite is rerunnable.
 */

const OSIUS_CUSTOMER_NAME = "B Amsterdam";
const OSIUS_BUILDING_NAME = "B1 Amsterdam";

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

async function resolveBuildingId(
  api: APIRequestContext,
  buildingName: string,
): Promise<number> {
  const response = await api.get("/api/buildings/?page_size=200");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match = body.results.find((b) => b.name === buildingName);
  expect(match, `building ${buildingName} present`).toBeTruthy();
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
}

interface ExtraWorkRow {
  id: number;
  title: string;
  routing_decision: "INSTANT" | "PROPOSAL";
  line_items: Array<{
    id: number;
    service: number | null;
    service_name: string;
    quantity: string;
    requested_date: string;
    customer_note: string;
  }>;
}

async function ensureSeedService(
  api: APIRequestContext,
  suffix: string,
): Promise<{ category: CategoryRow; service: ServiceRow }> {
  const ts = Date.now();
  const tag = `${suffix}-${ts}-${Math.random().toString(36).slice(2, 7)}`;
  const catResponse = await api.post("/api/services/categories/", {
    data: {
      name: `B6 Cat ${tag}`,
      description: "",
      is_active: true,
    },
  });
  expect(catResponse.status()).toBe(201);
  const cat = (await catResponse.json()) as CategoryRow;

  const svcResponse = await api.post("/api/services/", {
    data: {
      category: cat.id,
      name: `B6 Svc ${tag}`,
      description: "",
      unit_type: "HOURS",
      default_unit_price: "60.00",
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

async function deleteExtraWorkRequest(
  api: APIRequestContext,
  requestId: number,
): Promise<void> {
  // DELETE may not be implemented on the EW endpoint for every role;
  // tolerate 404 / 405 so test cleanup never fails the suite.
  const response = await api.delete(`/api/extra-work/${requestId}/`);
  expect([204, 404, 405]).toContain(response.status());
}

async function findExtraWorkByTitle(
  api: APIRequestContext,
  title: string,
): Promise<ExtraWorkRow | null> {
  const response = await api.get("/api/extra-work/?page_size=100");
  if (response.status() !== 200) return null;
  const body = (await response.json()) as {
    results: Array<{ id: number; title: string }>;
  };
  const match = body.results.find((r) => r.title === title);
  if (!match) return null;
  const detail = await api.get(`/api/extra-work/${match.id}/`);
  if (detail.status() !== 200) return null;
  return (await detail.json()) as ExtraWorkRow;
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function uniqueTitle(label: string): string {
  return `B6 ${label} ${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

test("Sprint 28 B6 — Customer cart submission with one priced line → INSTANT banner", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa, "instant");

  // Seed an active customer-specific price → routes the cart to INSTANT.
  const priceResponse = await sa.post(
    `/api/customers/${customerId}/pricing/`,
    {
      data: {
        service: service.id,
        unit_price: "55.00",
        vat_pct: "21.00",
        valid_from: todayISO(),
        valid_to: null,
        is_active: true,
      },
    },
  );
  expect(priceResponse.status()).toBe(201);

  const title = uniqueTitle("instant");

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/extra-work/new");
    await page.waitForLoadState("networkidle");
    await expect(
      page.locator("[data-testid='extra-work-create-page']"),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .locator("[data-testid='extra-work-create-title']")
      .fill(title);
    await page
      .locator("[data-testid='extra-work-create-description']")
      .fill("Cart submission — instant path");

    // The page seeds one empty cart line by default. Select the priced
    // service in line 0.
    await page
      .locator("[data-testid='extra-work-create-line-service-0']")
      .selectOption({ value: String(service.id) });

    const qty = page.locator(
      "[data-testid='extra-work-create-line-quantity-0']",
    );
    await qty.fill("");
    await qty.fill("3");

    const dateInput = page.locator(
      "[data-testid='extra-work-create-line-date-0']",
    );
    await dateInput.fill(todayISO());

    await page
      .locator("[data-testid='extra-work-create-line-note-0']")
      .fill("Top floor windows");

    await page.locator("[data-testid='extra-work-create-submit']").click();

    await expect(
      page.locator("[data-testid='extra-work-result-instant']"),
    ).toBeVisible({ timeout: 15_000 });
  } finally {
    const created = await findExtraWorkByTitle(sa, title);
    if (created) {
      await deleteExtraWorkRequest(sa, created.id);
    }
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("Sprint 28 B6 — Customer cart submission without agreed price → PROPOSAL banner", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa, "proposal");
  // No CustomerServicePrice seeded — cart routes to PROPOSAL.

  const title = uniqueTitle("proposal");

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/extra-work/new");
    await page.waitForLoadState("networkidle");
    await expect(
      page.locator("[data-testid='extra-work-create-page']"),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .locator("[data-testid='extra-work-create-title']")
      .fill(title);
    await page
      .locator("[data-testid='extra-work-create-description']")
      .fill("Cart submission — proposal path");

    await page
      .locator("[data-testid='extra-work-create-line-service-0']")
      .selectOption({ value: String(service.id) });

    const qty = page.locator(
      "[data-testid='extra-work-create-line-quantity-0']",
    );
    await qty.fill("");
    await qty.fill("1");

    const dateInput = page.locator(
      "[data-testid='extra-work-create-line-date-0']",
    );
    await dateInput.fill(todayISO());

    await page.locator("[data-testid='extra-work-create-submit']").click();

    await expect(
      page.locator("[data-testid='extra-work-result-proposal']"),
    ).toBeVisible({ timeout: 15_000 });
  } finally {
    const created = await findExtraWorkByTitle(sa, title);
    if (created) {
      await deleteExtraWorkRequest(sa, created.id);
    }
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("Sprint 28 B6 — Empty cart blocks submission with inline error", async ({
  page,
  baseURL,
}) => {
  // Resolve the demo customer/building IDs just to confirm seed,
  // but no service / pricing is needed because submission never
  // reaches the API.
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.customerAll);
  await page.goto("/extra-work/new");
  await page.waitForLoadState("networkidle");
  await expect(
    page.locator("[data-testid='extra-work-create-page']"),
  ).toBeVisible({ timeout: 10_000 });

  await page
    .locator("[data-testid='extra-work-create-title']")
    .fill("Empty cart test");
  await page
    .locator("[data-testid='extra-work-create-description']")
    .fill("Should be blocked by empty cart check");

  // Remove the default seeded cart line (index 0) so the cart is empty.
  await page
    .locator("[data-testid='extra-work-create-remove-line-0']")
    .click();
  await expect(
    page.locator("[data-testid='extra-work-create-cart-empty']"),
  ).toBeVisible();

  // Track POSTs to /api/extra-work/ — there should be NONE.
  const submitRequests: string[] = [];
  page.on("request", (req) => {
    if (
      req.method() === "POST" &&
      req.url().includes("/api/extra-work/")
    ) {
      submitRequests.push(req.url());
    }
  });

  await page.locator("[data-testid='extra-work-create-submit']").click();

  await expect(
    page.locator("[data-testid='extra-work-create-error']"),
  ).toBeVisible({ timeout: 5_000 });
  // We never navigated to the result panel.
  await expect(
    page.locator("[data-testid='extra-work-create-result']"),
  ).toHaveCount(0);
  // And no submission hit the wire.
  expect(submitRequests.length).toBe(0);
});

test("Sprint 28 B6 — Duplicate service in cart blocks submission", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa, "duplicate");

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/extra-work/new");
    await page.waitForLoadState("networkidle");
    await expect(
      page.locator("[data-testid='extra-work-create-page']"),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .locator("[data-testid='extra-work-create-title']")
      .fill("Duplicate-service test");
    await page
      .locator("[data-testid='extra-work-create-description']")
      .fill("Two lines that pick the same service should be rejected.");

    // Line 0: pick the service.
    await page
      .locator("[data-testid='extra-work-create-line-service-0']")
      .selectOption({ value: String(service.id) });
    const date0 = page.locator(
      "[data-testid='extra-work-create-line-date-0']",
    );
    await date0.fill(todayISO());

    // Add a second cart line.
    await page.locator("[data-testid='extra-work-create-add-line']").click();
    await expect(
      page.locator("[data-testid='extra-work-create-cart-line']"),
    ).toHaveCount(2, { timeout: 5_000 });

    // Line 1: pick the SAME service.
    await page
      .locator("[data-testid='extra-work-create-line-service-1']")
      .selectOption({ value: String(service.id) });
    const date1 = page.locator(
      "[data-testid='extra-work-create-line-date-1']",
    );
    await date1.fill(todayISO());

    // No POST should reach the wire.
    const submitRequests: string[] = [];
    page.on("request", (req) => {
      if (
        req.method() === "POST" &&
        req.url().includes("/api/extra-work/")
      ) {
        submitRequests.push(req.url());
      }
    });

    await page.locator("[data-testid='extra-work-create-submit']").click();

    await expect(
      page.locator("[data-testid='extra-work-create-error']"),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.locator("[data-testid='extra-work-create-result']"),
    ).toHaveCount(0);
    expect(submitRequests.length).toBe(0);
  } finally {
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("Sprint 28 B6 — Detail page renders cart line item after submission", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const { category, service } = await ensureSeedService(sa, "detail");

  // Seed an active customer-specific price so the cart routes to INSTANT.
  const priceResponse = await sa.post(
    `/api/customers/${customerId}/pricing/`,
    {
      data: {
        service: service.id,
        unit_price: "65.00",
        vat_pct: "21.00",
        valid_from: todayISO(),
        valid_to: null,
        is_active: true,
      },
    },
  );
  expect(priceResponse.status()).toBe(201);

  const title = uniqueTitle("detail");
  const note = "Detail-render check";
  const requestedDate = todayISO();
  const quantity = "4";
  let createdRequestId: number | null = null;

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await page.goto("/extra-work/new");
    await page.waitForLoadState("networkidle");
    await expect(
      page.locator("[data-testid='extra-work-create-page']"),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .locator("[data-testid='extra-work-create-title']")
      .fill(title);
    await page
      .locator("[data-testid='extra-work-create-description']")
      .fill("Cart submission verifying detail render");

    await page
      .locator("[data-testid='extra-work-create-line-service-0']")
      .selectOption({ value: String(service.id) });
    const qty = page.locator(
      "[data-testid='extra-work-create-line-quantity-0']",
    );
    await qty.fill("");
    await qty.fill(quantity);
    await page
      .locator("[data-testid='extra-work-create-line-date-0']")
      .fill(requestedDate);
    await page
      .locator("[data-testid='extra-work-create-line-note-0']")
      .fill(note);

    await page.locator("[data-testid='extra-work-create-submit']").click();
    await expect(
      page.locator("[data-testid='extra-work-result-instant']"),
    ).toBeVisible({ timeout: 15_000 });

    // Navigate to the detail page via the result-panel link.
    await page
      .locator("[data-testid='extra-work-result-view-link']")
      .click();
    await expect(
      page.locator("[data-testid='extra-work-detail-page']"),
    ).toBeVisible({ timeout: 10_000 });

    const lineItemRow = page
      .locator("[data-testid='extra-work-detail-line-item-row']")
      .first();
    await expect(lineItemRow).toBeVisible({ timeout: 10_000 });
    await expect(lineItemRow).toContainText(service.name);
    await expect(lineItemRow).toContainText(requestedDate);
    await expect(lineItemRow).toContainText(note);

    // Capture the request id so cleanup can DELETE it.
    const created = await findExtraWorkByTitle(sa, title);
    if (created) createdRequestId = created.id;
    expect(created, "request should exist after submit").toBeTruthy();
    expect(created!.routing_decision).toBe("INSTANT");
    expect(created!.line_items.length).toBe(1);
    expect(created!.line_items[0].service).toBe(service.id);
    expect(Number(created!.line_items[0].quantity)).toBe(Number(quantity));
    expect(created!.line_items[0].requested_date).toBe(requestedDate);
    expect(created!.line_items[0].customer_note).toBe(note);
  } finally {
    if (createdRequestId !== null) {
      await deleteExtraWorkRequest(sa, createdRequestId);
    } else {
      const fallback = await findExtraWorkByTitle(sa, title);
      if (fallback) await deleteExtraWorkRequest(sa, fallback.id);
    }
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});
