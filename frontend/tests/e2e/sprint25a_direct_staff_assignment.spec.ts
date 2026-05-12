import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 25A — pilot-readiness audit: admin/manager direct staff
 * assignment.
 *
 * Coverage:
 *   API gate
 *     - COMPANY_ADMIN can add and remove a STAFF assignment via the
 *       new endpoint without any staff-initiated request.
 *     - Add is idempotent (re-POST returns 200, no duplicate row).
 *     - Cross-company COMPANY_ADMIN cannot add (404 via queryset).
 *     - CUSTOMER_USER cannot add (403).
 *     - STAFF cannot add (403).
 *     - assignable-staff endpoint excludes ineligible candidates and
 *       cross-company staff.
 *   UI
 *     - COMPANY_ADMIN sees the Sprint 25A admin block on a ticket
 *       detail page, adds a staff member, and the ticket reload
 *       shows them in `assigned_staff`. Cleanup restores state.
 *
 * State isolation: each test acts on a freshly seeded ticket
 * cycle (add then remove). The cross-company / cross-role tests
 * never mutate state. The UI test removes its own row.
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

interface AssignableStaffBody {
  id: number;
  email: string;
  full_name: string;
  role: string;
}
interface TicketListItem {
  id: number;
  title: string;
  building_name?: string;
}
interface TicketDetailBody {
  id: number;
  assigned_staff: Array<{
    id?: number;
    anonymous?: boolean;
    email?: string;
    full_name?: string;
  }>;
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
 * Pick an Osius ticket where Ahmet (Osius STAFF) is NOT yet directly
 * assigned. Direct-assignment is non-destructive (no pending
 * request created), but `TicketStaffAssignment` is unique per
 * (ticket, user), so a re-run would 200-idempotent on the same row.
 * The cleanup branch in the happy-path test removes the row again
 * so the same ticket can be reused on the next run.
 */
async function pickFreshOsiusTicketId(
  sa: APIRequestContext,
  staffEmail: string,
): Promise<number> {
  const tickets = await listOsiusTickets(sa);
  expect(tickets.length).toBeGreaterThan(0);
  const staffId = await resolveUserId(sa, staffEmail);
  for (const t of tickets) {
    const detail = await sa.get(`/api/tickets/${t.id}/`);
    if (detail.status() !== 200) continue;
    const detailBody = (await detail.json()) as TicketDetailBody;
    const alreadyAssigned = (detailBody.assigned_staff ?? []).some(
      (entry) => "id" in entry && entry.id === staffId,
    );
    if (!alreadyAssigned) return t.id;
  }
  throw new Error(
    "Sprint 25A: no Osius ticket left without an Ahmet assignment — " +
      "run `seed_demo_data --reset-tickets`.",
  );
}

// =====================================================================
// API gate
// =====================================================================

test.describe("Sprint 25A → direct staff assignment API gate", () => {
  test("COMPANY_ADMIN can add and remove a STAFF assignment without any request", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    try {
      const add = await admin.post(
        `/api/tickets/${ticketId}/staff-assignments/`,
        { data: { user_id: staffId } },
      );
      expect([200, 201]).toContain(add.status());
      const addBody = await add.json();
      expect(addBody.user_id).toBe(staffId);

      // Re-POST → idempotent 200, no duplicate row.
      const dup = await admin.post(
        `/api/tickets/${ticketId}/staff-assignments/`,
        { data: { user_id: staffId } },
      );
      expect(dup.status()).toBe(200);

      // Detail reflects the assignment.
      const detail = await admin.get(`/api/tickets/${ticketId}/`);
      expect(detail.status()).toBe(200);
      const detailBody = (await detail.json()) as TicketDetailBody;
      const assignedIds = detailBody.assigned_staff
        .filter((e) => "id" in e)
        .map((e) => (e as { id: number }).id);
      expect(assignedIds).toContain(staffId);

      // Cleanup — remove the assignment.
      const remove = await admin.delete(
        `/api/tickets/${ticketId}/staff-assignments/${staffId}/`,
      );
      expect(remove.status()).toBe(204);
    } finally {
      await admin.dispose();
    }
  });

  test("assignable-staff excludes cross-company and ineligible candidates", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();

    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const response = await admin.get(
      `/api/tickets/${ticketId}/assignable-staff/`,
    );
    expect(response.status()).toBe(200);
    const body = (await response.json()) as AssignableStaffBody[];
    await admin.dispose();
    // Ahmet (Osius staff) must appear.
    expect(body.some((s) => s.email === DEMO_USERS.staffOsius.email)).toBe(true);
    // Noah (Bright staff) must NOT appear.
    expect(body.some((s) => s.email === DEMO_USERS.staffBright.email)).toBe(
      false,
    );
    // Customer / admin / manager personas must NOT appear.
    expect(body.some((s) => s.email === DEMO_USERS.customerAll.email)).toBe(
      false,
    );
    expect(body.some((s) => s.email === DEMO_USERS.companyAdmin.email)).toBe(
      false,
    );
  });

  test("cross-company COMPANY_ADMIN cannot add to another company's ticket", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const brightAdmin = await apiAs(baseURL!, DEMO_USERS.companyAdminB.email);
    const response = await brightAdmin.post(
      `/api/tickets/${ticketId}/staff-assignments/`,
      { data: { user_id: staffId } },
    );
    await brightAdmin.dispose();
    expect(response.status()).toBe(404);
  });

  test("CUSTOMER_USER cannot use the direct-assignment endpoint", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const tom = await apiAs(baseURL!, DEMO_USERS.customerAll.email);
    const response = await tom.post(
      `/api/tickets/${ticketId}/staff-assignments/`,
      { data: { user_id: staffId } },
    );
    await tom.dispose();
    // 403 (role gate) when CUSTOMER_USER can see the ticket via
    // their own scope; 404 (queryset hide) when they can't see it
    // (e.g. plain view_own + ticket created by another customer).
    // Both are valid CUSTOMER_USER rejections. Same shape as the
    // Sprint 24C self-cancel customer test.
    expect([403, 404]).toContain(response.status());
  });

  test("STAFF cannot use the direct-assignment endpoint", async ({
    baseURL,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    const ahmet = await apiAs(baseURL!, DEMO_USERS.staffOsius.email);
    const response = await ahmet.post(
      `/api/tickets/${ticketId}/staff-assignments/`,
      { data: { user_id: staffId } },
    );
    await ahmet.dispose();
    expect(response.status()).toBe(403);
  });
});

// =====================================================================
// UI — admin sees and uses the Sprint 25A block on ticket detail
// =====================================================================

test.describe("Sprint 25A → ticket detail admin block", () => {
  test("COMPANY_ADMIN can add a STAFF via the new block and the ticket reloads with them assigned", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    const staffId = await resolveUserId(sa, DEMO_USERS.staffOsius.email);
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/tickets/${ticketId}`);
    const block = page.locator('[data-testid="assigned-staff-admin-block"]');
    await expect(block).toBeVisible({ timeout: 15_000 });

    // Wait for the assignable-staff dropdown to populate.
    const select = page.locator('[data-testid="assigned-staff-admin-select"]');
    await expect(select).toBeVisible();
    await select.selectOption(String(staffId));

    const addPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/tickets/${ticketId}/staff-assignments/`) &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );
    await page
      .locator('[data-testid="assigned-staff-admin-add-button"]')
      .click();
    const addResponse = await addPromise;
    expect([200, 201]).toContain(addResponse.status());

    // Banner shows + the staff member appears in the assigned-staff list.
    await expect(
      page.locator('[data-testid="assigned-staff-admin-banner"]'),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page
        .locator('[data-testid="assigned-staff-item"]')
        .filter({ hasText: DEMO_USERS.staffOsius.fullName }),
    ).toBeVisible({ timeout: 10_000 });

    // Cleanup: remove the assignment via API so the demo state is bounded.
    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const remove = await admin.delete(
      `/api/tickets/${ticketId}/staff-assignments/${staffId}/`,
    );
    expect(remove.status()).toBe(204);
    await admin.dispose();
  });

  test("No raw `assigned_staff_admin_*` i18n keys leak on ticket detail", async ({
    baseURL,
    page,
  }) => {
    const sa = await apiAs(baseURL!, DEMO_USERS.super.email);
    const ticketId = await pickFreshOsiusTicketId(
      sa,
      DEMO_USERS.staffOsius.email,
    );
    await sa.dispose();

    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto(`/tickets/${ticketId}`);
    await expect(
      page.locator('[data-testid="assigned-staff-admin-block"]'),
    ).toBeVisible({ timeout: 15_000 });
    const bodyText = (await page.locator("body").textContent()) ?? "";
    const RAW_KEYS = [
      "assigned_staff_admin_title",
      "assigned_staff_admin_desc",
      "assigned_staff_admin_select_placeholder",
      "assigned_staff_admin_no_eligible",
      "assigned_staff_admin_add_button",
      "assigned_staff_admin_remove_button",
      "assigned_staff_admin_remove_dialog_title",
      "assigned_staff_admin_remove_dialog_body",
      "assigned_staff_admin_banner_added",
      "assigned_staff_admin_banner_removed",
    ];
    for (const key of RAW_KEYS) {
      expect(
        bodyText.includes(key),
        `Raw i18n key "${key}" leaked into rendered text — check src/i18n/{en,nl}/ticket_detail.json`,
      ).toBe(false);
    }
  });
});
