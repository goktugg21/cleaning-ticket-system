import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 24B — staff assignment review UX.
 *
 * The Sprint 23B page shipped a one-click approve/reject that sent
 * an empty reviewer_note. Sprint 24B replaces that with a proper
 * review modal: it shows the request context, lets the reviewer type
 * an optional note, posts approve/reject with the note, and surfaces
 * the persisted note on reviewed rows (both desktop table and mobile
 * card). Backend already supported reviewer_note since Sprint 23A —
 * these tests pin the UI path end-to-end and re-pin the cross-role /
 * cross-company isolation rules at the API layer.
 *
 * State-isolation strategy:
 *   - Each UI test creates a temporary PENDING request as Ahmet
 *     (Osius STAFF) against a TICKET that Ahmet is not yet assigned
 *     to. We pick a fresh ticket by listing Osius tickets via super-
 *     admin and filtering out any that already have a
 *     TicketStaffAssignment for Ahmet. After the test the request is
 *     left in its reviewed state — approving creates an assignment,
 *     rejecting leaves the ticket assignable again. The seed has
 *     enough Osius tickets (B1/B2/B3 Amsterdam variants) to absorb a
 *     handful of test runs before `seed_demo_data --reset-tickets`
 *     is needed.
 *   - The "cancel modal" test never mutates state because it never
 *     submits.
 */

async function apiAs(
  baseURL: string,
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  // Sprint 23C — 429 backoff. Same shape every other Sprint 23+ spec
  // uses; the full Playwright run easily crosses the 20/min auth_token
  // throttle now that several specs use apiAs.
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

interface TicketListItem {
  id: number;
  title: string;
  building_name?: string;
  assigned_staff?: Array<{ id?: number }>;
}
interface StaffRequestBody {
  id: number;
  staff: number;
  ticket: number;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";
  reviewer_note: string;
  reviewer_email: string | null;
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

/**
 * Pick an Osius ticket that has no existing PENDING request from
 * Ahmet AND no existing TicketStaffAssignment for Ahmet. Returns the
 * ticket id, throwing if the seed is exhausted (a re-seed is needed).
 */
async function pickFreshOsiusTicketId(
  sa: APIRequestContext,
  staffEmail: string,
): Promise<number> {
  const tickets = await listOsiusTickets(sa);
  expect(tickets.length).toBeGreaterThan(0);

  // Discover Ahmet's user id for the assigned_staff comparison.
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

  // Pull every existing request for Ahmet so we can skip tickets that
  // already have one.
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

  // For each candidate ticket, fetch detail to inspect assigned_staff.
  for (const t of tickets) {
    if (ticketIdsWithPending.has(t.id)) continue;
    const detail = await sa.get(`/api/tickets/${t.id}/`);
    if (detail.status() !== 200) continue;
    const detailBody = (await detail.json()) as {
      assigned_staff?: Array<{ id?: number; anonymous?: boolean }>;
    };
    const alreadyAssigned =
      (detailBody.assigned_staff ?? []).some(
        (entry) => "id" in entry && entry.id === staffId,
      );
    if (!alreadyAssigned) return t.id;
  }
  throw new Error(
    "Sprint 24B: no Osius ticket left without an existing Ahmet " +
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
// API gate — reviewer_note round-trip + role/cross-company isolation
// =====================================================================

test.describe("Sprint 24B → reviewer_note API gate", () => {
  test("SUPER_ADMIN can approve with reviewer_note (note persists on response)", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const pending = await createPendingRequestAs(
      DEMO_USERS.staffOsius.email,
      baseURL!,
      ticketId,
    );

    const note = `Sprint 24B api approve ${Date.now()}`;
    const response = await sa.post(
      `/api/staff-assignment-requests/${pending.id}/approve/`,
      { data: { reviewer_note: note } },
    );
    expect(response.status()).toBe(200);
    const body = (await response.json()) as StaffRequestBody;
    await sa.dispose();
    expect(body.status).toBe("APPROVED");
    expect(body.reviewer_note).toBe(note);
    expect(body.reviewer_email).toBe(DEMO_USERS.super.email);
  });

  test("STAFF cannot approve their own request (class-level gate)", async ({
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

    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const response = await ahmet.post(
      `/api/staff-assignment-requests/${pending.id}/approve/`,
      { data: { reviewer_note: "self-approval" } },
    );
    await ahmet.dispose();
    expect(response.status()).toBe(403);

    // Cleanup: a SUPER_ADMIN rejects the still-PENDING request so the
    // demo state stays bounded (no orphan permanently-pending row).
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const restore = await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24B cleanup — self-approval blocked" } },
    );
    expect(restore.status()).toBe(200);
    await sa2.dispose();
  });

  test("CUSTOMER_USER cannot review (queryset hides the resource)", async ({
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

    const tom = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await tom.post(
      `/api/staff-assignment-requests/${pending.id}/approve/`,
      { data: { reviewer_note: "from a customer" } },
    );
    await tom.dispose();
    expect(response.status()).toBe(404);

    // Cleanup.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24B cleanup — customer review blocked" } },
    );
    await sa2.dispose();
  });

  test("Cross-company COMPANY_ADMIN cannot review (queryset hides the row)", async ({
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

    const brightAdmin = await apiAs(baseURL!, DEMO_USERS.companyAdminB.email);
    const response = await brightAdmin.post(
      `/api/staff-assignment-requests/${pending.id}/approve/`,
      { data: { reviewer_note: "cross-company attempt" } },
    );
    await brightAdmin.dispose();
    expect(response.status()).toBe(404);

    // Cleanup.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24B cleanup — cross-company blocked" } },
    );
    await sa2.dispose();
  });
});

// =====================================================================
// UI — review modal
// =====================================================================

test.describe("Sprint 24B → review modal UX", () => {
  test("COMPANY_ADMIN approves a pending request with a reviewer note via the modal", async ({
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

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    await expect(
      page.locator('[data-testid="staff-requests-page"]'),
    ).toBeVisible({ timeout: 15_000 });

    const approveButton = page.locator(`[data-testid="approve-${pending.id}"]`);
    await expect(approveButton).toBeVisible({ timeout: 15_000 });
    await approveButton.click();

    const dialog = page.locator('[data-testid="staff-requests-review-dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const note = `Sprint 24B approved via UI ${Date.now()}`;
    const noteInput = page.locator(
      '[data-testid="staff-review-reviewer-note"]',
    );
    await expect(noteInput).toBeVisible();
    await noteInput.fill(note);

    const reviewPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/staff-assignment-requests/${pending.id}/approve/`) &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );
    // The confirm button is the second button in the ConfirmDialog
    // footer (cancel + confirm). Match by accessible name.
    await page
      .getByRole("button", { name: /^Approve$/i })
      .last()
      .click();
    const reviewResponse = await reviewPromise;
    expect(reviewResponse.status()).toBe(200);

    // Success banner shows. The dialog closes.
    await expect(
      page.locator('[data-testid="staff-requests-success-banner"]'),
    ).toBeVisible({ timeout: 5_000 });
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    // Switch the filter to "all" so the reviewed row is visible, and
    // confirm the note is rendered against the row.
    await page
      .locator('[data-testid="staff-requests-filter"]')
      .selectOption("all");
    const noteCell = page
      .locator('[data-testid="staff-request-reviewer-note"]')
      .filter({ hasText: note })
      .first();
    await expect(noteCell).toBeVisible({ timeout: 10_000 });
  });

  test("COMPANY_ADMIN rejects a pending request with a reviewer note via the modal", async ({
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

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    const rejectButton = page.locator(`[data-testid="reject-${pending.id}"]`);
    await expect(rejectButton).toBeVisible({ timeout: 15_000 });
    await rejectButton.click();

    const noteInput = page.locator(
      '[data-testid="staff-review-reviewer-note"]',
    );
    await expect(noteInput).toBeVisible({ timeout: 5_000 });
    const note = `Sprint 24B rejected via UI ${Date.now()}`;
    await noteInput.fill(note);

    const reviewPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/staff-assignment-requests/${pending.id}/reject/`) &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );
    await page
      .getByRole("button", { name: /^Reject$/i })
      .last()
      .click();
    const reviewResponse = await reviewPromise;
    expect(reviewResponse.status()).toBe(200);
    const body = (await reviewResponse.json()) as StaffRequestBody;
    expect(body.status).toBe("REJECTED");
    expect(body.reviewer_note).toBe(note);

    await expect(
      page.locator('[data-testid="staff-requests-success-banner"]'),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Cancelling the modal leaves the request PENDING (no API call)", async ({
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

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    const approveButton = page.locator(`[data-testid="approve-${pending.id}"]`);
    await expect(approveButton).toBeVisible({ timeout: 15_000 });
    await approveButton.click();

    const dialog = page.locator('[data-testid="staff-requests-review-dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Listen for any POST against the approve endpoint — there should
    // be NONE while the user cancels.
    let postSeen = false;
    page.on("request", (req) => {
      if (
        req.method() === "POST" &&
        req.url().includes(`/api/staff-assignment-requests/${pending.id}/`)
      ) {
        postSeen = true;
      }
    });
    await page
      .getByRole("button", { name: /Cancel|Annuleren/i })
      .last()
      .click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
    expect(postSeen).toBe(false);

    // Verify via API that the request is still PENDING and has no note.
    const sa2 = await apiAs(baseURL!, DEMO_USERS.super.email);
    const stillPending = await sa2.get(
      `/api/staff-assignment-requests/?status=PENDING&page_size=200`,
    );
    expect(stillPending.status()).toBe(200);
    const list = (await stillPending.json()) as {
      results: StaffRequestBody[];
    };
    const match = list.results.find((r) => r.id === pending.id);
    expect(match, "request stays PENDING after cancel").toBeTruthy();
    expect(match!.reviewer_note).toBe("");

    // Cleanup: reject the pending request so it doesn't accumulate
    // (the success / approve test path is also reachable from this
    // ticket, but only one PENDING request per (staff, ticket) is
    // allowed by the backend).
    const cleanup = await sa2.post(
      `/api/staff-assignment-requests/${pending.id}/reject/`,
      { data: { reviewer_note: "Sprint 24B cleanup — cancel test" } },
    );
    expect(cleanup.status()).toBe(200);
    await sa2.dispose();
  });
});

// =====================================================================
// Mobile invariant — no horizontal body overflow at phone widths
// =====================================================================

for (const vp of [
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 480, height: 853 },
]) {
  test(`/admin/staff-assignment-requests at ${vp.width}x${vp.height}: no horizontal page overflow`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    await expect(
      page.locator('[data-testid="staff-requests-page"]'),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator('[data-testid="staff-requests-card-list"]'),
    ).toBeAttached({ timeout: 10_000 });
    const scrollWidth = await page.evaluate(
      () => document.documentElement.scrollWidth,
    );
    expect(scrollWidth).toBeLessThanOrEqual(vp.width + 1);
  });
}

// =====================================================================
// No raw i18n keys leak on /admin/staff-assignment-requests
// =====================================================================

test("No raw `staff_requests.*` i18n keys leak on /admin/staff-assignment-requests", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/admin/staff-assignment-requests");
  await expect(
    page.locator('[data-testid="staff-requests-page"]'),
  ).toBeVisible({ timeout: 15_000 });

  const bodyText = (await page.locator("body").textContent()) ?? "";
  const RAW_KEYS = [
    "staff_requests.title",
    "staff_requests.intro",
    "staff_requests.col_when",
    "staff_requests.col_staff",
    "staff_requests.col_ticket",
    "staff_requests.col_status",
    "staff_requests.col_reviewer_note",
    "staff_requests.filter_pending",
    "staff_requests.filter_all",
    "staff_requests.approve",
    "staff_requests.reject",
    "staff_requests.review_dialog_approve_title",
    "staff_requests.review_dialog_reject_title",
    "staff_requests.reviewer_note_label",
    "staff_requests.reviewer_note_empty",
    "staff_requests.banner_approved",
    "staff_requests.banner_rejected",
  ];
  for (const key of RAW_KEYS) {
    expect(
      bodyText.includes(key),
      `Raw i18n key "${key}" leaked into rendered text — check src/i18n/{en,nl}/common.json`,
    ).toBe(false);
  }
});
