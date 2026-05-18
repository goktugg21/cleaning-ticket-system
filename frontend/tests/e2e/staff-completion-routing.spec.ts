import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 28 Batch 11 — Staff completion routing.
 *
 * Closes the frontend half of Batch 11:
 *   - TicketDetailPage now renders a "Complete work" button for an
 *     assigned STAFF user on an IN_PROGRESS ticket. The button opens
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
interface TicketListItem {
  id: number;
  status: string;
  building_name?: string;
}
interface TicketDetailBody {
  id: number;
  status: string;
  is_assigned_staff: boolean;
  building: number;
  assigned_staff: Array<{ id?: number; anonymous?: boolean }>;
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
 * Find (or freshly prepare) an Osius IN_PROGRESS ticket that Ahmet
 * (staffOsius) is directly assigned to. Strategy:
 *   1. List Osius tickets, look for an IN_PROGRESS ticket whose
 *      assigned_staff already contains Ahmet.
 *   2. If none — pick the first IN_PROGRESS ticket, POST a direct
 *      staff-assignment for Ahmet via the admin endpoint, then
 *      return that ticket id.
 *
 * The spec does NOT clean up the assignment; subsequent runs will
 * find the existing assigned row at step 1 and reuse it.
 */
async function findOrPrepareInProgressTicketForAhmet(
  sa: APIRequestContext,
): Promise<number> {
  const listResponse = await sa.get("/api/tickets/?page_size=100");
  expect(listResponse.status()).toBe(200);
  const list = (await listResponse.json()) as { results: TicketListItem[] };
  const osiusTickets = list.results.filter((t) =>
    /Amsterdam/i.test(t.building_name ?? ""),
  );
  expect(
    osiusTickets.length,
    "expected at least one Osius ticket in the seed",
  ).toBeGreaterThan(0);

  const inProgress = osiusTickets.filter((t) => t.status === "IN_PROGRESS");
  const ahmetId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);

  for (const t of inProgress) {
    const detail = await sa.get(`/api/tickets/${t.id}/`);
    if (detail.status() !== 200) continue;
    const body = (await detail.json()) as TicketDetailBody;
    const isAhmetAssigned = (body.assigned_staff ?? []).some(
      (entry) => "id" in entry && entry.id === ahmetId,
    );
    if (isAhmetAssigned) return t.id;
  }

  // None pre-assigned — grab the first IN_PROGRESS and add Ahmet.
  expect(
    inProgress.length,
    "expected at least one IN_PROGRESS Osius ticket in the seed",
  ).toBeGreaterThan(0);
  const target = inProgress[0];
  const assign = await sa.post(
    `/api/tickets/${target.id}/staff-assignments/`,
    { data: { user_id: ahmetId } },
  );
  expect([200, 201]).toContain(assign.status());
  return target.id;
}

test.describe("Sprint 28 Batch 11 — STAFF completion routing", () => {
  test("STAFF sees the Complete work button and the modal flow lands the ticket in a review state", async ({
    baseURL,
    page,
  }) => {
    test.setTimeout(180_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await findOrPrepareInProgressTicketForAhmet(sa);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);

    // The "Complete work" entry point must be present.
    const completeBtn = page.getByTestId("ticket-staff-complete-button");
    await expect(completeBtn).toBeVisible({ timeout: 15_000 });

    // Sprint 28 Batch 11 UX hotfix — the Workflow card must show the
    // dedicated "Complete your assigned work" subtitle AND must NOT
    // expose any of the generic next-status UI for STAFF. The card
    // subtitle is rendered via `card_workflow_subtitle_staff_complete`
    // which the testid below anchors stably across locales.
    await expect(
      page.getByTestId("ticket-staff-complete-card-subtitle"),
    ).toBeVisible();

    // No generic Status-note input. The workflow card uses
    // id="status-note" for that input; getByRole + name is fragile
    // across locales, so we anchor on the stable DOM id instead.
    await expect(page.locator("#status-note")).toHaveCount(0);

    // No generic "Move to X" buttons. They are rendered via
    // `workflow_move_to` in both locales; their EN/NL labels both
    // contain the string "Move" / "Verplaats" respectively, but the
    // structural assertion is "the workflow card contains exactly
    // one status-btn — the Complete work CTA". We verify by counting
    // `.status-btn` elements inside the workflow card.
    const workflowCard = page
      .locator(`xpath=//*[@data-testid="ticket-staff-complete-button"]/ancestor::div[contains(@class, "card")][1]`);
    await expect(workflowCard).toBeVisible();
    await expect(workflowCard.locator(".status-btn")).toHaveCount(1);

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
    await page.goto(`/admin/users/${ahmetId}`);
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByTestId("staff-details-section"),
    ).toBeVisible({ timeout: 15_000 });

    const checkboxTestid = `staff-completion-routes-to-customer-${targetRow.building_id}`;
    const checkbox = page.getByTestId(checkboxTestid);
    await expect(checkbox).toBeVisible({ timeout: 10_000 });

    // The initial UI state must mirror the API state.
    if (initial) {
      await expect(checkbox).toBeChecked();
    } else {
      await expect(checkbox).not.toBeChecked();
    }

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
      checkbox.click(),
    ]);

    // Reload the page to confirm the flag persisted server-side.
    await page.reload();
    await page.waitForLoadState("networkidle");
    const reloadedCheckbox = page.getByTestId(checkboxTestid);
    await expect(reloadedCheckbox).toBeVisible({ timeout: 10_000 });
    if (initial) {
      await expect(reloadedCheckbox).not.toBeChecked();
    } else {
      await expect(reloadedCheckbox).toBeChecked();
    }

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
