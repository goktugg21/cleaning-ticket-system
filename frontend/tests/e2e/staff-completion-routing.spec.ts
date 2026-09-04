import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 11 — Staff completion routing.
 *
 * Closes the frontend half of Batch 11:
 *   - TicketDetailPage now renders a "Complete work" button for an
 *     assigned STAFF user on an IN_PROGRESS ticket (FE-3: it IS the
 *     page's one primary action, in the phase banner; no generic
 *     "move to" buttons are offered next to it). The button opens
 *     a modal that resolves the destination via
 *     `GET /api/tickets/<id>/staff-completion-route/` and submits the
 *     corresponding status transition.
 *   - UserFormPage's per-BSV-row editor now exposes a
 *     `staff_completion_routes_to_customer` checkbox so SUPER_ADMIN
 *     can flip the route per (user, building).
 *
 * The spec is light: it exercises the testid surfaces only and does
 * not assert backend side-effects beyond the UI badge / persisted
 * checkbox value. Heavier coverage (route mismatch error, evidence-
 * required error) sits in the backend Sprint 28 Batch 11 test suite.
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

interface UserSearchRow {
  id: number;
  email: string;
}
async function resolveUserId(
  api: APIRequestContext,
  email: string,
): Promise<number> {
  const response = await api.get(
    `/api/users/?search=${encodeURIComponent(email)}&page_size=50`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: UserSearchRow[] };
  const match = body.results.find((u) => u.email === email);
  expect(match, `user ${email} present`).toBeTruthy();
  return match!.id;
}

/**
 * P-12 H — seed a FRESH IN_PROGRESS ticket for Ahmet instead of
 * borrowing one from the database. The old find-or-prepare picked the
 * first IN_PROGRESS seed row, and on dev that is a ticket spawned from
 * an extra work with `file_upload_required=True`: the server (rightly)
 * refused the note-only completion with "requires a file". A plain
 * ticket (no extra-work origin) is completable with a note alone
 * (`tickets/completion_requirements.py`), so the spec creates its own:
 *   1. pick an Amsterdam building and a customer linked to it,
 *   2. POST /api/tickets/ (a plain melding — no evidence flags),
 *   3. assign Ahmet, and move it OPEN -> IN_PROGRESS with the
 *      `scheduled_start_at` answer the transition-requirements gate
 *      asks for (WHO is the assignment, WHEN is the answer field).
 * Each run seeds its own ticket; nothing in the seed data is mutated.
 */
async function seedInProgressTicketForAhmet(
  sa: APIRequestContext,
): Promise<number> {
  const ahmetId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);

  const buildingsResponse = await sa.get(
    "/api/buildings/?search=Amsterdam&page_size=50",
  );
  expect(buildingsResponse.status()).toBe(200);
  const buildings = (await buildingsResponse.json()) as {
    results: Array<{ id: number; name: string }>;
  };
  expect(
    buildings.results.length,
    "expected an Amsterdam building in the seed",
  ).toBeGreaterThan(0);

  // A customer linked to the building (the M:N membership; the legacy
  // single-building anchor still mirrors it on old rows).
  const customersResponse = await sa.get("/api/customers/?page_size=100");
  expect(customersResponse.status()).toBe(200);
  const customers = (await customersResponse.json()) as {
    results: Array<{
      id: number;
      building?: number | null;
      linked_building_ids?: number[];
    }>;
  };
  let buildingId: number | null = null;
  let customerId: number | null = null;
  for (const b of buildings.results) {
    const match = customers.results.find(
      (c) => (c.linked_building_ids ?? []).includes(b.id) || c.building === b.id,
    );
    if (match) {
      buildingId = b.id;
      customerId = match.id;
      break;
    }
  }
  expect(customerId, "a customer linked to an Amsterdam building").toBeTruthy();

  const create = await sa.post("/api/tickets/", {
    data: {
      title: "P-12 e2e completion seed",
      description:
        "Seeded by staff-completion-routing.spec.ts — a plain ticket with no evidence requirements.",
      building: buildingId,
      customer: customerId,
      priority: "NORMAL",
    },
  });
  expect(create.status(), await create.text()).toBe(201);
  const ticket = (await create.json()) as { id: number };

  const assign = await sa.post(`/api/tickets/${ticket.id}/staff-assignments/`, {
    data: { user_id: ahmetId },
  });
  expect([200, 201]).toContain(assign.status());

  // OPEN -> IN_PROGRESS is a legal move; the gate wants WHO (assigned
  // above) and WHEN (answered inline).
  const start = await sa.post(`/api/tickets/${ticket.id}/status/`, {
    data: {
      to_status: "IN_PROGRESS",
      note: "P-12 e2e seed: started for the completion-routing walk",
      scheduled_start_at: new Date().toISOString(),
    },
  });
  expect(start.status(), await start.text()).toBe(200);
  return ticket.id;
}

test.describe("Sprint 28 Batch 11 — STAFF completion routing", () => {
  test("STAFF sees the Complete work button and the modal flow lands the ticket in a review state", async ({
    baseURL,
    page,
  }) => {
    test.setTimeout(180_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await seedInProgressTicketForAhmet(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);

    // The "Complete work" entry point must be present.
    const completeBtn = page.getByTestId("ticket-staff-complete-button");
    await expect(completeBtn).toBeVisible({ timeout: 15_000 });

    // FE-3 — "Complete work" is THE primary action: it sits in the
    // phase banner at the head of the page, and the page must NOT
    // offer the generic next-status buttons (`workflow-move-*`) to
    // STAFF alongside it. The generic buttons are what a manager gets;
    // for the assigned STAFF the completion modal is the only door.
    await expect(
      page.locator('[data-testid="ticket-facts"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid^="workflow-move-"]'),
    ).toHaveCount(0);

    // Open the modal.
    await completeBtn.click();
    const modal = page.getByTestId("ticket-staff-complete-modal");
    await expect(modal).toBeVisible({ timeout: 10_000 });

    // Fill the required note.
    const note = page.getByTestId("ticket-staff-complete-note");
    await expect(note).toBeVisible();
    await note.fill("Sprint 28 Batch 11 e2e completion note");

    // The route resolves async — wait for the submit to enable.
    const submit = page.getByTestId("ticket-staff-complete-submit");
    await expect(submit).toBeEnabled({ timeout: 10_000 });

    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes(`/api/tickets/${ticketId}/status/`) &&
          r.request().method() === "POST",
        { timeout: 15_000 },
      ),
      submit.click(),
    ]);

    // The modal closes and the ticket status badge updates to either
    // WAITING_MANAGER_REVIEW (default route) or WAITING_CUSTOMER_APPROVAL
    // (configured-bypass route). Either is a valid Batch 11 outcome —
    // the seed's BSV flag dictates which.
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // Re-fetch via the API to confirm the status is in one of the
    // accepted post-completion states. We avoid asserting the badge
    // text in either language by going to the data source directly.
    const checkApi = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const after = await checkApi.get(`/api/tickets/${ticketId}/`);
    expect(after.status()).toBe(200);
    const afterBody = (await after.json()) as { status: string };
    await checkApi.dispose();
    expect([
      "WAITING_MANAGER_REVIEW",
      "WAITING_CUSTOMER_APPROVAL",
    ]).toContain(afterBody.status);
  });

  test("SUPER_ADMIN can toggle the staff-completion-routes-to-customer flag and it persists", async ({
    baseURL,
    page,
  }) => {
    test.setTimeout(180_000);

    // Resolve Ahmet's user id once via the admin API.
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ahmetId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);

    // Discover one of Ahmet's BSV rows so the testid is anchored on a
    // real building_id (avoids the spec hard-coding a seed-dependent
    // numeric id).
    const bsvResponse = await sa.get(
      `/api/users/${ahmetId}/staff-visibility/`,
    );
    expect(bsvResponse.status()).toBe(200);
    const bsvBody = (await bsvResponse.json()) as {
      results: Array<{
        building_id: number;
        staff_completion_routes_to_customer: boolean;
      }>;
    };
    expect(bsvBody.results.length).toBeGreaterThan(0);
    const targetRow = bsvBody.results[0];
    const initial = targetRow.staff_completion_routes_to_customer;
    await sa.dispose();

    await loginAs(page, DEMO_USERS.super);
    // Sprint 29 Batch 29.6 — `/admin/users/:id` is the read-only
    // detail page; the StaffDetailsSection lives on the form at /edit.
    await page.goto(`/admin/users/${ahmetId}/edit`);
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByTestId("staff-details-section"),
    ).toBeVisible({ timeout: 15_000 });

    // The switch's testid sits on a visually hidden checkbox input; the
    // `.toggle-switch` label around it is the click target.
    const checkboxTestid = `staff-completion-routes-to-customer-${targetRow.building_id}`;
    const checkbox = page.getByTestId(checkboxTestid);
    await expect(checkbox).toBeAttached({ timeout: 10_000 });

    // The initial UI state must mirror the API state.
    expect(await checkbox.isChecked()).toBe(initial);

    // Toggle to the inverse value.
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r
            .url()
            .includes(
              `/api/users/${ahmetId}/staff-visibility/${targetRow.building_id}/`,
            ) && r.request().method() === "PATCH",
        { timeout: 15_000 },
      ),
      checkbox.locator("xpath=..").click(),
    ]);

    // Reload the page to confirm the flag persisted server-side.
    await page.reload();
    await page.waitForLoadState("networkidle");
    const reloadedCheckbox = page.getByTestId(checkboxTestid);
    await expect(reloadedCheckbox).toBeAttached({ timeout: 10_000 });
    expect(await reloadedCheckbox.isChecked()).toBe(!initial);

    // Restore initial state so subsequent runs start from a known
    // baseline.
    const restore = await apiAs(baseURL!, DEMO_USERS.super.email);
    const patch = await restore.patch(
      `/api/users/${ahmetId}/staff-visibility/${targetRow.building_id}/`,
      { data: { staff_completion_routes_to_customer: initial } },
    );
    expect([200, 204]).toContain(patch.status());
    await restore.dispose();
  });
});
