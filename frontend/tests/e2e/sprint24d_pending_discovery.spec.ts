import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 24D — pending-request discovery hardening.
 *
 * Sprint 24C used `listStaffAssignmentRequests()` (no filters) to
 * find the staff user's PENDING request for the current ticket. With
 * the default backend pagination (25/page) and Sprint 23A's
 * append-only request history, a staff user whose PENDING row sat
 * past the first page silently failed to see the Cancel CTA.
 *
 * Sprint 24D switches the discovery call to a targeted
 * `?ticket=<id>&status=PENDING` filter — supported by the new
 * `filterset_fields` on `StaffAssignmentRequestViewSet`. This spec
 * proves the contract end-to-end:
 *
 *   1. Bulk-create ≥25 CANCELLED rows for Ahmet on a dedicated
 *      ticket (so the next PENDING row is guaranteed NOT to land on
 *      page 1 of an unfiltered list).
 *   2. Create one fresh PENDING row.
 *   3. Open the ticket detail page as Ahmet. The pending block must
 *      render and the Cancel button must be visible — proving the
 *      filtered call finds it regardless of page position.
 *   4. Cancel via the dialog. Cleanup leaves the row CANCELLED.
 *
 * We do NOT re-test the Sprint 24C cancel happy path here — that
 * spec already covers it. This file targets the pagination edge.
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

interface StaffRequestBody {
  id: number;
  staff: number;
  ticket: number;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";
}
interface TicketListItem {
  id: number;
  title: string;
  building_name?: string;
}

async function listOsiusTickets(
  api: APIRequestContext,
): Promise<TicketListItem[]> {
  const response = await api.get("/api/tickets/?page_size=50");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: TicketListItem[] };
  return body.results.filter((t) =>
    /Amsterdam/i.test(t.building_name ?? ""),
  );
}

async function resolveUserId(
  api: APIRequestContext,
  email: string,
): Promise<number> {
  const response = await api.get(
    `/api/users/?search=${encodeURIComponent(email)}&page_size=50`,
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    results: Array<{ id: number; email: string }>;
  };
  const match = body.results.find((u) => u.email === email);
  expect(match, `user ${email} present`).toBeTruthy();
  return match!.id;
}

async function pickFreshOsiusTicketId(
  sa: APIRequestContext,
  staffEmail: string,
): Promise<number> {
  const tickets = await listOsiusTickets(sa);
  expect(tickets.length).toBeGreaterThan(0);
  const staffId = await resolveUserId(sa, staffEmail);
  const reqResponse = await sa.get(
    `/api/staff-assignment-requests/?staff=${staffId}&status=PENDING&page_size=200`,
  );
  expect(reqResponse.status()).toBe(200);
  const reqBody = (await reqResponse.json()) as { results: StaffRequestBody[] };
  const ticketIdsWithPending = new Set(
    reqBody.results.map((r) => r.ticket),
  );
  for (const t of tickets) {
    if (ticketIdsWithPending.has(t.id)) continue;
    const detail = await sa.get(`/api/tickets/${t.id}/`);
    if (detail.status() !== 200) continue;
    const detailBody = (await detail.json()) as {
      assigned_staff?: Array<{ id?: number; anonymous?: boolean }>;
    };
    const alreadyAssigned = (detailBody.assigned_staff ?? []).some(
      (entry) => "id" in entry && entry.id === staffId,
    );
    if (!alreadyAssigned) return t.id;
  }
  throw new Error(
    "Sprint 24D: no Osius ticket left without an existing Ahmet " +
      "assignment or pending request — run `seed_demo_data --reset-tickets`.",
  );
}

// =====================================================================
// Backend filter — sanity check
// =====================================================================

test.describe("Sprint 24D → ?ticket=&status= filter sanity", () => {
  test("Filtered call returns at most the matching PENDING row for the staff", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();

    // Create one PENDING row as Ahmet.
    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const create = await ahmet.post("/api/staff-assignment-requests/", {
      data: { ticket: ticketId },
    });
    expect(create.status()).toBe(201);
    const created = (await create.json()) as StaffRequestBody;

    // Filtered call — exactly one row, the one we created.
    const filtered = await ahmet.get(
      `/api/staff-assignment-requests/?ticket=${ticketId}&status=PENDING`,
    );
    expect(filtered.status()).toBe(200);
    const filteredBody = (await filtered.json()) as {
      results: StaffRequestBody[];
    };
    expect(filteredBody.results.length).toBe(1);
    expect(filteredBody.results[0].id).toBe(created.id);
    expect(filteredBody.results[0].status).toBe("PENDING");

    // Cleanup.
    const cleanup = await ahmet.post(
      `/api/staff-assignment-requests/${created.id}/cancel/`,
    );
    expect(cleanup.status()).toBe(200);
    await ahmet.dispose();
  });
});

// =====================================================================
// UI — pending discovery survives >25 historical rows
// =====================================================================

test.describe("Sprint 24D → ticket detail discovery survives a long history", () => {
  test("Cancel CTA renders even when Ahmet has 30+ historical CANCELLED rows", async ({
    baseURL,
    page,
  }) => {
    test.setTimeout(180_000);

    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();

    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    try {
      // Build a deep history: 30 cycles of create → cancel on the
      // SAME ticket. Each cycle leaves one CANCELLED row, which the
      // duplicate guard tolerates (only PENDING blocks a new POST).
      // 30 > the backend page size of 25 so an unfiltered fetch
      // would never see the next PENDING row in the first page.
      const HISTORY_DEPTH = 30;
      for (let i = 0; i < HISTORY_DEPTH; i++) {
        const cycleCreate = await ahmet.post(
          "/api/staff-assignment-requests/",
          { data: { ticket: ticketId } },
        );
        expect(
          cycleCreate.status(),
          `history seed cycle ${i} create`,
        ).toBe(201);
        const cycle = (await cycleCreate.json()) as StaffRequestBody;
        const cycleCancel = await ahmet.post(
          `/api/staff-assignment-requests/${cycle.id}/cancel/`,
        );
        expect(
          cycleCancel.status(),
          `history seed cycle ${i} cancel`,
        ).toBe(200);
      }

      // Now create the CURRENT pending request.
      const currentCreate = await ahmet.post(
        "/api/staff-assignment-requests/",
        { data: { ticket: ticketId } },
      );
      expect(currentCreate.status()).toBe(201);
      const current = (await currentCreate.json()) as StaffRequestBody;

      // Sanity: an unfiltered list would NOT have this PENDING row
      // on page 1 (the deep CANCELLED history sits ahead of it in
      // `-requested_at` order). The filtered call MUST still find it.
      const filtered = await ahmet.get(
        `/api/staff-assignment-requests/?ticket=${ticketId}&status=PENDING`,
      );
      expect(filtered.status()).toBe(200);
      const filteredBody = (await filtered.json()) as {
        results: StaffRequestBody[];
      };
      expect(filteredBody.results.map((r) => r.id)).toContain(current.id);

      // UI check — Ahmet opens the ticket; the Cancel CTA renders.
      await loginAs(page, DEMO_USERS.staffOsius);
      await page.goto(`/tickets/${ticketId}`);
      await expect(
        page.locator('[data-testid="request-assignment-pending"]'),
      ).toBeVisible({ timeout: 15_000 });
      await expect(
        page.locator('[data-testid="cancel-request-assignment-button"]'),
      ).toBeVisible();
      await expect(
        page.locator('[data-testid="request-assignment-button"]'),
      ).toHaveCount(0);

      // Cleanup: cancel the current row so the demo state is bounded.
      const cleanup = await ahmet.post(
        `/api/staff-assignment-requests/${current.id}/cancel/`,
      );
      expect(cleanup.status()).toBe(200);
    } finally {
      await ahmet.dispose();
    }
  });
});
