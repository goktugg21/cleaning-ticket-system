import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 4 — Customer Contacts page.
 *
 * Coverage:
 *   1. `/admin/customers/<id>/contacts` renders `CustomerContactsPage`
 *      (the real page) and NOT the Batch 3 `CustomerSubPagePlaceholder`.
 *   2. The Add-contact modal exposes phone-book fields only — NO
 *      password / role enum / scope inputs (Contacts vs Users §1 of
 *      `docs/product/meeting-2026-05-15-system-requirements.md`).
 *   3. A new contact appears in the list after submission.
 *   4. Clicking a row opens the read-only detail panel (no inline
 *      form auto-render) with an explicit Edit button.
 *   5. Editing the role label updates both the list row and the
 *      detail panel.
 *
 * Auth: COMPANY_ADMIN (Ramazan @ Osius Demo). Backend gate is
 * `IsSuperAdminOrCompanyAdminForCompany`; using the narrower role
 * also locks in the COMPANY_ADMIN-visible path.
 *
 * Cleanup: every test that creates a contact deletes it via the
 * backend at the end so the suite is rerunnable without a reseed.
 *
 * Customer id resolution: lookup "B Amsterdam" via the customers
 * list endpoint, mirroring `sprint28b_customer_sidebar.spec.ts`.
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

interface ContactPayload {
  id: number;
  full_name: string;
}

async function deleteContactById(
  api: APIRequestContext,
  customerId: number,
  contactId: number,
): Promise<void> {
  const response = await api.delete(
    `/api/customers/${customerId}/contacts/${contactId}/`,
  );
  expect([204, 404]).toContain(response.status());
}

async function findContactByName(
  api: APIRequestContext,
  customerId: number,
  fullName: string,
): Promise<ContactPayload | null> {
  const response = await api.get(`/api/customers/${customerId}/contacts/`);
  if (response.status() !== 200) return null;
  const body = (await response.json()) as {
    results: ContactPayload[];
  };
  return body.results.find((c) => c.full_name === fullName) ?? null;
}

test("Sprint 28 B4 — /admin/customers/:id/contacts renders real page (not placeholder)", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}/contacts`);
  await page.waitForLoadState("networkidle");

  // Real page is mounted.
  await expect(
    page.locator("[data-testid='customer-contacts-page']"),
  ).toBeVisible({ timeout: 10_000 });

  // Placeholder is NOT.
  await expect(
    page.locator("[data-testid='customer-subpage-placeholder']"),
  ).toHaveCount(0);

  // Add button is reachable.
  await expect(
    page.locator("[data-testid='customer-contacts-add-button']"),
  ).toBeVisible();
});

test("Sprint 28 B4 — Add modal has contact fields and NO login/user fields", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);
  await sa.dispose();

  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto(`/admin/customers/${customerId}/contacts`);
  await page.waitForLoadState("networkidle");

  await page.locator("[data-testid='customer-contacts-add-button']").click();

  const modal = page.locator("[data-testid='customer-contact-modal']");
  await expect(modal).toBeVisible({ timeout: 5_000 });

  // Contact fields are present.
  await expect(
    modal.locator("[data-testid='customer-contact-input-full-name']"),
  ).toBeVisible();
  await expect(
    modal.locator("[data-testid='customer-contact-input-email']"),
  ).toBeVisible();
  await expect(
    modal.locator("[data-testid='customer-contact-input-phone']"),
  ).toBeVisible();
  await expect(
    modal.locator("[data-testid='customer-contact-input-role-label']"),
  ).toBeVisible();
  await expect(
    modal.locator("[data-testid='customer-contact-input-notes']"),
  ).toBeVisible();

  // Contacts are NOT login users — no password input, no role enum
  // dropdown, no field whose placeholder/name suggests a login or
  // role-enum control.
  await expect(modal.locator("input[type='password']")).toHaveCount(0);
  await expect(modal.locator("select[name='role']")).toHaveCount(0);
  await expect(
    modal.locator("input[placeholder*='password' i]"),
  ).toHaveCount(0);
  await expect(
    modal.locator("input[placeholder*='role enum' i]"),
  ).toHaveCount(0);

  // Close the modal so the page is back to a clean state for the
  // following tests.
  await modal
    .locator("[data-testid='customer-contact-modal-cancel']")
    .click();
  await expect(modal).toBeHidden({ timeout: 5_000 });
});

test("Sprint 28 B4 — Creating a contact adds it to the list", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);

  // Unique name so the spec is rerunnable.
  const uniqueName = `Pieter Test ${Date.now()}`;

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/contacts`);
    await page.waitForLoadState("networkidle");

    await page.locator("[data-testid='customer-contacts-add-button']").click();

    const modal = page.locator("[data-testid='customer-contact-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal
      .locator("[data-testid='customer-contact-input-full-name']")
      .fill(uniqueName);
    await modal
      .locator("[data-testid='customer-contact-input-email']")
      .fill("pieter.test@example.com");
    await modal
      .locator("[data-testid='customer-contact-input-phone']")
      .fill("+31 6 0000 0001");
    await modal
      .locator("[data-testid='customer-contact-input-role-label']")
      .fill("Facility manager");

    await modal
      .locator("[data-testid='customer-contact-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // Row with the unique name should appear in the list.
    const newRow = page.locator(
      "[data-testid='customer-contact-row']",
      { hasText: uniqueName },
    );
    await expect(newRow).toBeVisible({ timeout: 10_000 });
  } finally {
    const found = await findContactByName(sa, customerId, uniqueName);
    if (found) await deleteContactById(sa, customerId, found.id);
    await sa.dispose();
  }
});

test("Sprint 28 B4 — Row click opens read-only detail with explicit Edit button", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);

  // Create a contact via the API so the spec does not depend on the
  // ordering of preceding tests.
  const uniqueName = `Lieke Test ${Date.now()}`;
  const createResponse = await sa.post(
    `/api/customers/${customerId}/contacts/`,
    {
      data: {
        full_name: uniqueName,
        email: "lieke.test@example.com",
        phone: "+31 6 0000 0002",
        role_label: "Janitor lead",
      },
    },
  );
  expect(createResponse.status()).toBe(201);
  const created = (await createResponse.json()) as { id: number };

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/contacts`);
    await page.waitForLoadState("networkidle");

    const row = page
      .locator("[data-testid='customer-contact-row']", { hasText: uniqueName })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    // Read-only detail panel renders.
    const detail = page.locator("[data-testid='customer-contact-detail']");
    await expect(detail).toBeVisible({ timeout: 5_000 });

    // Values match what we created.
    await expect(
      detail.locator("[data-testid='customer-contact-detail-role']"),
    ).toContainText("Janitor lead");
    await expect(
      detail.locator("[data-testid='customer-contact-detail-email']"),
    ).toContainText("lieke.test@example.com");
    await expect(
      detail.locator("[data-testid='customer-contact-detail-phone']"),
    ).toContainText("+31 6 0000 0002");

    // Explicit Edit button is present, but the edit form does NOT
    // auto-render (modal is hidden until Edit is clicked).
    await expect(
      detail.locator("[data-testid='customer-contact-edit-button']"),
    ).toBeVisible();
    await expect(
      page.locator("[data-testid='customer-contact-modal']"),
    ).toHaveCount(0);
  } finally {
    await deleteContactById(sa, customerId, created.id);
    await sa.dispose();
  }
});

test("Sprint 28 B4 — Edit modal updates list row and detail panel", async ({
  page,
  baseURL,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const customerId = await resolveCustomerId(sa, OSIUS_CUSTOMER_NAME);

  const uniqueName = `Sven Test ${Date.now()}`;
  const createResponse = await sa.post(
    `/api/customers/${customerId}/contacts/`,
    {
      data: {
        full_name: uniqueName,
        email: "sven.test@example.com",
        phone: "+31 6 0000 0003",
        role_label: "Initial role",
      },
    },
  );
  expect(createResponse.status()).toBe(201);
  const created = (await createResponse.json()) as { id: number };

  const newRole = `Updated role ${Date.now()}`;

  try {
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/admin/customers/${customerId}/contacts`);
    await page.waitForLoadState("networkidle");

    const row = page
      .locator("[data-testid='customer-contact-row']", { hasText: uniqueName })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    const detail = page.locator("[data-testid='customer-contact-detail']");
    await expect(detail).toBeVisible({ timeout: 5_000 });

    await detail
      .locator("[data-testid='customer-contact-edit-button']")
      .click();

    const modal = page.locator("[data-testid='customer-contact-modal']");
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const roleInput = modal.locator(
      "[data-testid='customer-contact-input-role-label']",
    );
    await roleInput.fill("");
    await roleInput.fill(newRole);

    await modal
      .locator("[data-testid='customer-contact-modal-save']")
      .click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // The list row shows the new role label.
    const updatedRow = page
      .locator("[data-testid='customer-contact-row']", { hasText: uniqueName })
      .first();
    await expect(
      updatedRow.locator("[data-testid='customer-contact-row-role']"),
    ).toContainText(newRole);

    // The detail panel shows the new role label.
    await expect(
      detail.locator("[data-testid='customer-contact-detail-role']"),
    ).toContainText(newRole);
  } finally {
    await deleteContactById(sa, customerId, created.id);
    await sa.dispose();
  }
});
