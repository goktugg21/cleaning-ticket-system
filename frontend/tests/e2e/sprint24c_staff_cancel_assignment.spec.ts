import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 24C — STAFF self-cancellation of a PENDING assignment request.
 *
 * Coverage:
 *   1. API gate:
 *      - STAFF can cancel own PENDING request.
 *      - STAFF cannot cancel another staff's request (404).
 *      - CUSTOMER_USER cannot cancel (403/404 — either is fine).
 *      - COMPANY_ADMIN cannot use the self-cancel endpoint (403).
 *      - Cancelled request cannot later be approved by COMPANY_ADMIN.
 *      - STAFF can submit a new request after cancelling.
 *   2. UI:
 *      - STAFF opens the ticket detail page, sees the pending state,
 *        opens the cancel dialog, confirms, and the page flips back
 *        to the "Request assignment" CTA.
 *      - Cancel dialog can be dismissed without an API call.
 *   3. Mobile invariant on the touched ticket detail page at
 *      390 / 430 / 480 px.
 *   4. No raw i18n keys leak in the cancel UI.
 *
 * State isolation strategy:
 *   - Each test creates a temporary PENDING request as Ahmet (Osius
 *     STAFF) against a fresh Osius ticket (no existing assignment,
 *     no existing PENDING request from Ahmet). Cancelling leaves the
 *     row as CANCELLED — non-destructive, doesn't create an
 *     assignment, doesn't block other tests.
 *   - The "STAFF can cancel" UI test ends with the row CANCELLED.
 *   - Tests that intentionally leave a PENDING row cancel it as
 *     SUPER_ADMIN reject afterwards so no orphan PENDING rows
 *     accumulate (the API-gate tests do this).
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
  reviewer_note: string;
  reviewer_email: string | null;
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

async function pickFreshOsiusTicketId(
  sa: APIRequestContext,
  staffEmail: string,
): Promise<number> {
  const tickets = await listOsiusTickets(sa);
  expect(tickets.length).toBeGreaterThan(0);

  const userListResponse = await sa.get(
    `/api/users/?search=${encodeURIComponent(staffEmail)}&page_size=50`,
  );
  expect(userListResponse.status()).toBe(200);
  const userList = (await userListResponse.json()) as {
    results: Array<{ id: number; email: string }>;
  };
  const staffUser = userList.results.find((u) => u.email === staffEmail);
  expect(staffUser, `staff ${staffEmail} present`).toBeTruthy();
  const staffId = staffUser!.id;

  const reqResponse = await sa.get(
    `/api/staff-assignment-requests/?staff=${staffId}&page_size=200`,
  );
  expect(reqResponse.status()).toBe(200);
  const reqBody = (await reqResponse.json()) as { results: StaffRequestBody[] };
  const ticketIdsWithPending = new Set(
    reqBody.results
      .filter((r) => r.status === "PENDING")
      .map((r) => r.ticket),
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
    "Sprint 24C: no Osius ticket left without an existing Ahmet " +
      "assignment or pending request — run `seed_demo_data --reset-tickets`.",
  );
}

async function createPendingRequestAs(
  staffEmail: string,
  baseURL: string,
  ticketId: number,
): Promise<StaffRequestBody> {
  const ahmet = await apiAs(baseURL, staffEmail);
  try {
    const response = await ahmet.post("/api/staff-assignment-requests/", {
      data: { ticket: ticketId },
    });
    expect(response.status(), `POST request creation for ticket ${ticketId}`).toBe(
      201,
    );
    return (await response.json()) as StaffRequestBody;
  } finally {
    await ahmet.dispose();
  }
}

// =====================================================================
// API gate
// =====================================================================

test.describe("Sprint 24C → cancel API gate", () => {
  test("STAFF can cancel their own PENDING request", async ({ baseURL }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const response = await ahmet.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    expect(response.status()).toBe(200);
    const body = (await response.json()) as StaffRequestBody;
    await ahmet.dispose();
    expect(body.status).toBe("CANCELLED");
    expect(body.reviewer_email).toBeNull();
  });

  test("STAFF cannot cancel another staff's request (404)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const ahmetPending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    // Noah (Bright STAFF) tries to cancel Ahmet's request.
    const noah = await apiAs(baseURL!, DEMO_USERS.staffBright.email);
    const response = await noah.post(
      `/api/staff-assignment-requests/${ahmetPending.id}/cancel/`,
    );
    await noah.dispose();
    expect(response.status()).toBe(404);

    // Cleanup: SUPER_ADMIN rejects so the row doesn't sit PENDING.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const cleanup = await sa2.post(
      `/api/staff-assignment-requests/${ahmetPending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24C cleanup — cross-staff cancel" } },
    );
    expect(cleanup.status()).toBe(200);
    await sa2.dispose();
  });

  test("CUSTOMER_USER cannot use the cancel endpoint", async ({ baseURL }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    const tom = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await tom.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    await tom.dispose();
    expect([403, 404]).toContain(response.status());

    // Cleanup.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24C cleanup — customer cancel" } },
    );
    await sa2.dispose();
  });

  test("COMPANY_ADMIN cannot use the self-cancel endpoint (admins reject instead)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const response = await admin.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    await admin.dispose();
    expect(response.status()).toBe(403);

    // Cleanup via SUPER_ADMIN reject.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const cleanup = await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24C cleanup — admin cancel blocked" } },
    );
    expect(cleanup.status()).toBe(200);
    await sa2.dispose();
  });

  test("Cancelled request cannot later be approved (Sprint 24B reviewer-note path is closed)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    // Ahmet cancels.
    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const cancel = await ahmet.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    expect(cancel.status()).toBe(200);
    await ahmet.dispose();

    // COMPANY_ADMIN tries to approve. _review checks status==PENDING → 400.
    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const approve = await admin.post(
      `/api/staff-assignment-requests/${pending.id}/approve/`,
      { data: { reviewer_note: "post-cancel approve" } },
    );
    await admin.dispose();
    expect(approve.status()).toBe(400);
  });

  test("STAFF can request again after cancelling the previous request", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();

    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    try {
      // First request.
      const first = await ahmet.post("/api/staff-assignment-requests/", {
        data: { ticket: ticketId },
      });
      expect(first.status()).toBe(201);
      const firstBody = (await first.json()) as StaffRequestBody;

      // Cancel.
      const cancel = await ahmet.post(
        `/api/staff-assignment-requests/${firstBody.id}/cancel/`,
      );
      expect(cancel.status()).toBe(200);

      // Second request — the duplicate guard fires only on PENDING.
      const second = await ahmet.post("/api/staff-assignment-requests/", {
        data: { ticket: ticketId },
      });
      expect(second.status()).toBe(201);
      const secondBody = (await second.json()) as StaffRequestBody;
      expect(secondBody.id).not.toBe(firstBody.id);
      expect(secondBody.status).toBe("PENDING");

      // Cleanup: cancel the second request so the demo state is bounded.
      const cleanup = await ahmet.post(
        `/api/staff-assignment-requests/${secondBody.id}/cancel/`,
      );
      expect(cleanup.status()).toBe(200);
    } finally {
      await ahmet.dispose();
    }
  });
});

// =====================================================================
// UI — TicketDetailPage cancel flow
// =====================================================================

test.describe("Sprint 24C → ticket detail cancel UX", () => {
  test("STAFF sees the pending state, cancels via dialog, and returns to the request CTA", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);
    // Pending block should render automatically thanks to the
    // discover-pending-request effect.
    await expect(
      page.locator('[data-testid="request-assignment-pending"]'),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator('[data-testid="request-assignment-button"]'),
    ).toHaveCount(0);

    const cancelButton = page.locator(
      '[data-testid="cancel-request-assignment-button"]',
    );
    await expect(cancelButton).toBeVisible();
    await cancelButton.click();

    const cancelPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/staff-assignment-requests/${pending.id}/cancel/`) &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );
    // ConfirmDialog renders confirm as the last button labelled with
    // confirmLabel. Demo seed sets Ahmet's language to "nl", so the
    // button can render in either locale — match both.
    await page
      .getByRole("button", { name: /^(Cancel request|Aanvraag annuleren)$/i })
      .last()
      .click();
    const cancelResponse = await cancelPromise;
    expect(cancelResponse.status()).toBe(200);

    // Page flips back to the request CTA + shows the success banner.
    await expect(
      page.locator('[data-testid="request-assignment-button"]'),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.locator('[data-testid="request-assignment-pending"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="request-assignment-banner"]'),
    ).toBeVisible();
  });

  test("Cancel dialog can be dismissed without firing the API call", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);
    await expect(
      page.locator('[data-testid="request-assignment-pending"]'),
    ).toBeVisible({ timeout: 15_000 });
    await page
      .locator('[data-testid="cancel-request-assignment-button"]')
      .click();

    let postSeen = false;
    page.on("request", (req) => {
      if (
        req.method() === "POST" &&
        req.url().includes(`/api/staff-assignment-requests/${pending.id}/cancel/`)
      ) {
        postSeen = true;
      }
    });
    // ConfirmDialog cancel button — first button in the footer.
    await page
      .getByRole("button", { name: /^(Cancel|Annuleren)$/i })
      .first()
      .click();
    // The dialog closes — the pending state stays.
    await expect(
      page.locator('[data-testid="request-assignment-pending"]'),
    ).toBeVisible({ timeout: 5_000 });
    expect(postSeen).toBe(false);

    // Verify API still has the row PENDING.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const list = await sa2.get(
      `/api/staff-assignment-requests/?page_size=200`,
    );
    expect(list.status()).toBe(200);
    const body = (await list.json()) as { results: StaffRequestBody[] };
    const match = body.results.find((r) => r.id === pending.id);
    expect(match!.status).toBe("PENDING");

    // Cleanup: cancel the row via API so the demo state is bounded.
    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const cleanup = await ahmet.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    expect(cleanup.status()).toBe(200);
    await ahmet.dispose();
    await sa2.dispose();
  });
});

// =====================================================================
// Mobile invariant — no horizontal body overflow on ticket detail
// =====================================================================

for (const vp of [
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 480, height: 853 },
]) {
  test(`Ticket detail cancel UI at ${vp.width}x${vp.height}: no horizontal page overflow`, async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.staffOsius);
    await page.goto(`/tickets/${ticketId}`);
    await expect(
      page.locator('[data-testid="request-assignment-pending"]'),
    ).toBeVisible({ timeout: 15_000 });
    const scrollWidth = await page.evaluate(
      () => document.documentElement.scrollWidth,
    );
    expect(scrollWidth).toBeLessThanOrEqual(vp.width + 1);

    // Cleanup: cancel the row via API so the demo state is bounded.
    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const cleanup = await ahmet.post(
      `/api/staff-assignment-requests/${pending.id}/cancel/`,
    );
    expect(cleanup.status()).toBe(200);
    await ahmet.dispose();
  });
}

// =====================================================================
// No raw i18n keys leak in the cancel UI
// =====================================================================

test("No raw `request_assignment_*` cancel i18n keys leak on ticket detail", async ({
  baseURL,
  page,
}) => {
  const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
  const ticketId = await pickFreshOsiusTicketId(
    sa,
    DEMO_USERS.staffOsius.email,
  );
  await sa.dispose();
  const pending = await createPendingRequestAs(
    DEMO_USERS.staffOsius.email,
    baseURL!,
    ticketId,
  );

  await loginAs(page, DEMO_USERS.staffOsius);
  await page.goto(`/tickets/${ticketId}`);
  await expect(
    page.locator('[data-testid="request-assignment-pending"]'),
  ).toBeVisible({ timeout: 15_000 });
  const bodyText = (await page.locator("body").textContent()) ?? "";
  const RAW_KEYS = [
    "request_assignment_pending_title",
    "request_assignment_pending_body",
    "request_assignment_cancel",
    "request_assignment_cancelling",
    "request_assignment_cancelled_success",
    "request_assignment_cancel_dialog_title",
    "request_assignment_cancel_dialog_body",
  ];
  for (const key of RAW_KEYS) {
    expect(
      bodyText.includes(key),
      `Raw i18n key "${key}" leaked into rendered text — check src/i18n/{en,nl}/ticket_detail.json`,
    ).toBe(false);
  }

  // Cleanup.
  const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
  await ahmet.post(
    `/api/staff-assignment-requests/${pending.id}/cancel/`,
  );
  await ahmet.dispose();
});
