import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 6 — Extra Work cart UI.
 * FE-2 / FE-4 (Addendum D §D.5) — REWRITTEN onto the customer Meerwerk
 * flow. A CUSTOMER_USER opening `/extra-work/new` lands on
 * `MeerwerkFlowPage`: four steps — where (building) / what (tick the
 * agreed-price services, add "other" free-text lines) / when (wish
 * date) / confirm — and the confirm step STATES the outcome from the
 * server's own preview (`meerwerk-outcome`, `data-kind="instant"` when
 * every line has an agreed price, `"quote"` otherwise). The Sprint 28
 * cart (title / description / per-line service select, quantity,
 * date, note, add/remove line, submit, result banners) is gone; the
 * flow derives the request title from the picked lines.
 *
 * Coverage (same intent as Batch 6):
 *   1. Customer submits one priced line → INSTANT outcome + created
 *      screen saying so.
 *   2. Customer submits a line without an agreed price ("other" line)
 *      → QUOTE outcome.
 *   3. Empty cart blocks progress (the Next button stays disabled on
 *      the "what" step; no API call).
 *   4. A priced service can only be in the cart ONCE (it is a checkbox,
 *      not a repeatable line) — the duplicate-service guard is
 *      structural now.
 *   5. After a successful submission, the created screen links to the
 *      customer detail (`meerwerk-detail-page`) and the API row carries
 *      the line item (service / quantity / requested_date).
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


/**
 * Sprint 142 — a catalog row is per provider COMPANY, and `company` is
 * REQUIRED on create as soon as more than one company exists (the dev
 * database now holds four). Seed everything under "Osius Demo".
 */
async function resolveOsiusCompanyId(api: APIRequestContext): Promise<number> {
  const response = await api.get("/api/companies/?page_size=50");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  const match = body.results.find((c) => c.name === "Osius Demo");
  expect(match, 'company "Osius Demo" present').toBeTruthy();
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
    requested_date: string | null;
    customer_note: string;
  }>;
}

async function ensureSeedService(
  api: APIRequestContext,
  suffix: string,
): Promise<{ category: CategoryRow; service: ServiceRow }> {
  const ts = Date.now();
  const companyId = await resolveOsiusCompanyId(api);
  const tag = `${suffix}-${ts}-${Math.random().toString(36).slice(2, 7)}`;
  const catResponse = await api.post("/api/services/categories/", {
    data: {
      company: companyId,
      name: `B6 Cat ${tag}`,
      description: "",
      is_active: true,
    },
  });
  expect(catResponse.status()).toBe(201);
  const cat = (await catResponse.json()) as CategoryRow;

  const svcResponse = await api.post("/api/services/", {
    data: {
      company: companyId,
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

async function seedCustomerPrice(
  api: APIRequestContext,
  customerId: number,
  serviceId: number,
  unitPrice: string,
): Promise<void> {
  const priceResponse = await api.post(
    `/api/customers/${customerId}/pricing/`,
    {
      data: {
        service: serviceId,
        unit_price: unitPrice,
        vat_pct: "21.00",
        valid_from: todayISO(),
        valid_to: null,
        is_active: true,
      },
    },
  );
  expect(priceResponse.status()).toBe(201);
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

/**
 * The flow derives the request title from the picked lines (one line
 * → its label, the service name). Find the request by the service it
 * was created for, newest first.
 */
async function findExtraWorkForService(
  api: APIRequestContext,
  serviceId: number,
): Promise<ExtraWorkRow | null> {
  const response = await api.get("/api/extra-work/?page_size=100");
  if (response.status() !== 200) return null;
  const body = (await response.json()) as {
    results: Array<{ id: number; title: string }>;
  };
  for (const row of body.results) {
    const detail = await api.get(`/api/extra-work/${row.id}/`);
    if (detail.status() !== 200) continue;
    const full = (await detail.json()) as ExtraWorkRow;
    if ((full.line_items ?? []).some((line) => line.service === serviceId)) {
      return full;
    }
  }
  return null;
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

/** Step 1 (where): Tom has B1 + B2 + B3, so the building is a select. */
async function openFlowAtWhat(
  page: import("@playwright/test").Page,
  buildingId: number,
): Promise<void> {
  await page.goto("/extra-work/new");
  await page.waitForLoadState("networkidle");
  await expect(page.locator("[data-testid='meerwerk-flow-page']")).toBeVisible({
    timeout: 10_000,
  });
  const fixed = page.locator("[data-testid='meerwerk-building-fixed']");
  if ((await fixed.count()) === 0) {
    await page
      .locator("[data-testid='meerwerk-building']")
      .selectOption({ value: String(buildingId) });
  }
  await page.locator("[data-testid='meerwerk-next']").click();
  // The "what" step: the agreed-price picker (or its empty line) and
  // the "other" lines editor.
  await expect(
    page.locator(
      "[data-testid='meerwerk-picker'], [data-testid='meerwerk-picker-empty']",
    ).first(),
  ).toBeVisible({ timeout: 10_000 });
}

/** Steps 3 + 4: wish date, then the confirm step with its outcome. */
async function advanceToConfirm(
  page: import("@playwright/test").Page,
  wishDate: string,
): Promise<void> {
  await page.locator("[data-testid='meerwerk-next']").click();
  const date = page.locator("[data-testid='meerwerk-date']");
  await expect(date).toBeVisible({ timeout: 5_000 });
  await date.fill(wishDate);
  await page.locator("[data-testid='meerwerk-next']").click();
  await expect(page.locator("[data-testid='meerwerk-confirm']")).toBeVisible({
    timeout: 5_000,
  });
  await expect(page.locator("[data-testid='meerwerk-outcome']")).toBeVisible({
    timeout: 15_000,
  });
}

test("FE-2 — Customer submits one priced line → INSTANT outcome", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const buildingId = await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  const { category, service } = await ensureSeedService(sa, "instant");

  // Seed an active customer-specific price → the line is agreed →
  // INSTANT.
  await seedCustomerPrice(sa, customerId, service.id, "55.00");

  let createdRequestId: number | null = null;
  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await openFlowAtWhat(page, buildingId);

    // Tick the priced service; a quantity box appears next to it.
    const serviceCheckbox = page.locator(
      `[data-testid='meerwerk-service-${service.id}']`,
    );
    await expect(serviceCheckbox).toBeVisible({ timeout: 10_000 });
    await serviceCheckbox.check();
    const qty = page
      .locator("[data-testid='meerwerk-services'] input[type='number']")
      .first();
    await expect(qty).toBeVisible();
    await qty.fill("3");

    await advanceToConfirm(page, todayISO());
    await expect(page.locator("[data-testid='meerwerk-outcome']")).toHaveAttribute(
      "data-kind",
      "instant",
    );
    await expect(
      page.locator("[data-testid='meerwerk-confirm-line']"),
    ).toHaveCount(1);

    await page.locator("[data-testid='meerwerk-submit']").click();
    await expect(page.locator("[data-testid='meerwerk-created']")).toBeVisible({
      timeout: 15_000,
    });

    const created = await findExtraWorkForService(sa, service.id);
    expect(created, "request should exist after submit").toBeTruthy();
    createdRequestId = created!.id;
    expect(created!.routing_decision).toBe("INSTANT");
    expect(Number(created!.line_items[0].quantity)).toBe(3);
  } finally {
    if (createdRequestId !== null) {
      await deleteExtraWorkRequest(sa, createdRequestId);
    }
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("FE-2 — Customer submits a line without an agreed price → QUOTE outcome", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const buildingId = await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  // No service / price seeded: the customer types an "other" line,
  // which the server cannot price → a quote first.
  const title = uniqueTitle("quote");

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await openFlowAtWhat(page, buildingId);

    const other = page.locator("[data-testid='meerwerk-other']");
    await expect(other).toBeVisible({ timeout: 10_000 });
    await other.fill(title);

    await advanceToConfirm(page, todayISO());
    await expect(page.locator("[data-testid='meerwerk-outcome']")).toHaveAttribute(
      "data-kind",
      /quote|auto_start/,
    );

    await page.locator("[data-testid='meerwerk-submit']").click();
    await expect(page.locator("[data-testid='meerwerk-created']")).toBeVisible({
      timeout: 15_000,
    });
    const created = await findExtraWorkByTitle(sa, title);
    expect(created, "request should exist after submit").toBeTruthy();
    expect(created!.routing_decision).toBe("PROPOSAL");
  } finally {
    const created = await findExtraWorkByTitle(sa, title);
    if (created) {
      await deleteExtraWorkRequest(sa, created.id);
    }
    await sa.dispose();
  }
});

test("FE-2 — Empty cart blocks progress with no API call", async ({
  page,
  baseURL,
}) => {
  // Resolve the demo customer/building IDs just to confirm seed,
  // but no service / pricing is needed because submission never
  // reaches the API.
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const buildingId = await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.customerAll);
  await openFlowAtWhat(page, buildingId);

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

  // Nothing ticked, nothing typed: the step is not valid, Next is
  // disabled and the confirm step (with its submit) is unreachable.
  const next = page.locator("[data-testid='meerwerk-next']");
  await expect(next).toBeDisabled();
  await next.click({ force: true });
  await expect(page.locator("[data-testid='meerwerk-date']")).toHaveCount(0);
  await expect(page.locator("[data-testid='meerwerk-submit']")).toHaveCount(0);
  await expect(page.locator("[data-testid='meerwerk-created']")).toHaveCount(0);
  // And no submission hit the wire.
  expect(submitRequests.length).toBe(0);
});

test("FE-2 — A priced service is one checkbox: it cannot be added twice", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const buildingId = await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  const { category, service } = await ensureSeedService(sa, "duplicate");
  await seedCustomerPrice(sa, customerId, service.id, "40.00");

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await openFlowAtWhat(page, buildingId);

    // Exactly one control for the service; ticking it twice toggles
    // it back OUT of the cart rather than adding a second line.
    const serviceCheckbox = page.locator(
      `[data-testid='meerwerk-service-${service.id}']`,
    );
    await expect(serviceCheckbox).toHaveCount(1);
    await serviceCheckbox.check();
    await expect(serviceCheckbox).toBeChecked();
    await serviceCheckbox.uncheck();
    await expect(serviceCheckbox).not.toBeChecked();
    await expect(page.locator("[data-testid='meerwerk-next']")).toBeDisabled();

    // In the cart once → the confirm list carries exactly one line.
    await serviceCheckbox.check();
    await advanceToConfirm(page, todayISO());
    await expect(
      page.locator("[data-testid='meerwerk-confirm-line']"),
    ).toHaveCount(1);
  } finally {
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});

test("FE-2 — Created screen opens the customer detail; the API row carries the line", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  const buildingId = await resolveBuildingId(sa, OSIUS_BUILDING_NAME);
  const { category, service } = await ensureSeedService(sa, "detail");

  // Seed an active customer-specific price so the line is agreed.
  await seedCustomerPrice(sa, customerId, service.id, "65.00");

  const requestedDate = todayISO();
  const quantity = "4";
  let createdRequestId: number | null = null;

  try {
    await loginAs(page, DEMO_USERS.customerAll);
    await openFlowAtWhat(page, buildingId);

    const serviceCheckbox = page.locator(
      `[data-testid='meerwerk-service-${service.id}']`,
    );
    await expect(serviceCheckbox).toBeVisible({ timeout: 10_000 });
    await serviceCheckbox.check();
    const qty = page
      .locator("[data-testid='meerwerk-services'] input[type='number']")
      .first();
    await qty.fill(quantity);

    await advanceToConfirm(page, requestedDate);
    await page.locator("[data-testid='meerwerk-submit']").click();
    await expect(page.locator("[data-testid='meerwerk-created']")).toBeVisible({
      timeout: 15_000,
    });

    // Navigate to the customer detail via the created screen's link.
    await page.locator("[data-testid='meerwerk-created-open']").click();
    await expect(
      page.locator("[data-testid='meerwerk-detail-page']"),
    ).toBeVisible({ timeout: 10_000 });
    await page.waitForURL(/\/extra-work\/\d+$/, { timeout: 10_000 });
    // The detail is titled after the picked line (the service name)
    // and tells the request's story in the timeline.
    await expect(page.locator("[data-testid='meerwerk-detail-page']")).toContainText(
      service.name,
    );
    await expect(page.locator("[data-testid='meerwerk-timeline']")).toBeVisible();

    // The request row carries the cart line: service / quantity /
    // requested date (the flow's wish date).
    const created = await findExtraWorkForService(sa, service.id);
    expect(created, "request should exist after submit").toBeTruthy();
    createdRequestId = created!.id;
    expect(String(created!.id)).toBe(new URL(page.url()).pathname.split("/").pop());
    expect(created!.routing_decision).toBe("INSTANT");
    expect(created!.line_items.length).toBe(1);
    expect(created!.line_items[0].service).toBe(service.id);
    expect(Number(created!.line_items[0].quantity)).toBe(Number(quantity));
    expect(created!.line_items[0].requested_date).toBe(requestedDate);
  } finally {
    if (createdRequestId !== null) {
      await deleteExtraWorkRequest(sa, createdRequestId);
    } else {
      const fallback = await findExtraWorkForService(sa, service.id);
      if (fallback) await deleteExtraWorkRequest(sa, fallback.id);
    }
    for (const p of await listPricesForService(sa, customerId, service.id)) {
      await deletePriceById(sa, customerId, p.id);
    }
    await deleteSeedService(sa, category, service);
    await sa.dispose();
  }
});
