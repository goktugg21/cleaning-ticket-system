import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";
import { openTicketTab } from "./fixtures/tickets";

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
 *     - COMPANY_ADMIN sees the staff-assignment section on the ticket's
 *       People tab (FE-3: the Sprint 25A "admin block" + its select
 *       became the Assign dialog of the staff-assignment table), adds
 *       a staff member, and the ticket reload shows them in the
 *       assignment table. Cleanup restores state.
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
      expect(add.status()).toBe(201);
      const addBody = await add.json();
      expect(addBody.user_id).toBe(staffId);
      const slotId = addBody.id as number;

      // Multi-slot per staff — a re-POST is NO LONGER idempotent: it
      // creates a SECOND slot row (201) for the same staff.
      const dup = await admin.post(
        `/api/tickets/${ticketId}/staff-assignments/`,
        { data: { user_id: staffId } },
      );
      expect(dup.status()).toBe(201);
      const dupBody = await dup.json();
      expect(dupBody.id).not.toBe(slotId);

      // Detail reflects the assignment.
      const detail = await admin.get(`/api/tickets/${ticketId}/`);
      expect(detail.status()).toBe(200);
      const detailBody = (await detail.json()) as TicketDetailBody;
      const assignedIds = detailBody.assigned_staff
        .filter((e) => "id" in e)
        .map((e) => (e as { id: number }).id);
      expect(assignedIds).toContain(staffId);

      // Cleanup — remove BOTH slots, now keyed by the slot id.
      for (const id of [slotId, dupBody.id as number]) {
        const remove = await admin.delete(
          `/api/tickets/${ticketId}/staff-assignments/${id}/`,
        );
        expect(remove.status()).toBe(204);
      }
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

test.describe("Sprint 25A → ticket detail staff-assignment section", () => {
  test("COMPANY_ADMIN can add a STAFF via the Assign dialog and the table reloads with them assigned", async ({
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
    await openTicketTab(page, "people");
    const section = page.locator('[data-testid="staff-assignment-section"]');
    await expect(section).toBeVisible({ timeout: 15_000 });

    // Open the Assign dialog (the "assign first" and "assign more"
    // buttons share one testid) and tick Ahmet by his user id.
    await section.locator('[data-testid="staff-assignment-assign"]').first().click();
    const dialog = page.locator('[data-testid="staff-assignment-list-modal"]');
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    const person = dialog.locator(
      `[data-testid="staff-assignment-list-person"][data-user-id="${staffId}"]`,
    );
    await expect(person).toBeVisible({ timeout: 10_000 });
    await person.check();

    const addPromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/tickets/${ticketId}/staff-assignments/`) &&
        r.request().method() === "POST",
      { timeout: 15_000 },
    );
    await dialog.locator('[data-testid="staff-assignment-list-confirm"]').click();
    const addResponse = await addPromise;
    expect([200, 201]).toContain(addResponse.status());

    // The dialog closes and the staff member appears as a row of the
    // assignment table.
    await expect(dialog).toBeHidden({ timeout: 10_000 });
    await expect(
      page
        .locator('[data-testid="staff-assignment-row"]')
        .filter({ hasText: DEMO_USERS.staffOsius.fullName }),
    ).toBeVisible({ timeout: 10_000 });

    // Cleanup: remove the assignment(s) via API so the demo state is
    // bounded. Multi-slot per staff — delete is keyed by the slot id, so
    // list the rows and remove each one.
    const admin = await apiAs(baseURL!, DEMO_USERS.companyAdmin.email);
    const list = await admin.get(
      `/api/tickets/${ticketId}/staff-assignments/`,
    );
    const listBody = (await list.json()) as { results: { id: number }[] };
    for (const row of listBody.results) {
      const remove = await admin.delete(
        `/api/tickets/${ticketId}/staff-assignments/${row.id}/`,
      );
      expect(remove.status()).toBe(204);
    }
    await admin.dispose();
  });

  test("No raw i18n keys leak on the staff-assignment section or its Assign dialog", async ({
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
    await openTicketTab(page, "people");
    const section = page.locator('[data-testid="staff-assignment-section"]');
    await expect(section).toBeVisible({ timeout: 15_000 });
    await section.locator('[data-testid="staff-assignment-assign"]').first().click();
    await expect(
      page.locator('[data-testid="staff-assignment-list-modal"]'),
    ).toBeVisible({ timeout: 10_000 });
    // i18next returns the KEY when a lookup misses; a key literal has
    // the shape `namespace:group.key` or `group.key` with an underscore
    // vocabulary. Scan the rendered text for the section's namespaces.
    const bodyText = (await page.locator("body").textContent()) ?? "";
    for (const pattern of [
      /\bstaff_slots:[a-z_.]+/,
      /\bassign\.[a-z_]+\b/,
      /\bassigned_staff_[a-z_]+\b/,
    ]) {
      expect(
        bodyText,
        `Raw i18n key matching ${pattern} leaked into rendered text — check src/i18n/{en,nl}/`,
      ).not.toMatch(pattern);
    }
    await page.locator('[data-testid="staff-assignment-list-cancel"]').click();
  });
});
