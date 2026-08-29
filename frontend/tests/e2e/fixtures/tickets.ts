import { expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiAs } from "./apiAs";
import { DEMO_USERS } from "./demoUsers";

/**
 * Sprint 30 Batch 30.1.2 Phase F — demo-ticket fixture lookups.
 *
 * Specs that previously navigated via the dashboard table
 * (`.data-table tbody tr` + `a.td-id`) now resolve the demo ticket's
 * ID via the API at the start of each test and `goto()` the detail
 * route directly. This is both faster and resilient to dashboard
 * table selector changes.
 *
 * IDs cannot be hardcoded because `python manage.py seed_demo_data
 * --reset-tickets` deletes the existing tickets and advances the
 * autoincrement past any previous value. Looking up by title at
 * runtime sidesteps that churn entirely.
 *
 * The lookup runs inside the page context via `page.evaluate`, so it
 * reuses the access token the prior `loginAs` already stashed in
 * `localStorage`. This avoids burning a second `/api/auth/token/`
 * call per test and keeps the spec under the auth-endpoint rate
 * limit when the bundle runs hot.
 *
 * FE-6 (Addendum D) — the tickets list at `/tickets` opens on the
 * "Open" tab and on the current month. Every spec that wants to see
 * a specific seeded row (a WAITING_CUSTOMER_APPROVAL ticket lives on
 * the "Wacht op klant" tab, a CLOSED one on "Afgehandeld") either
 * selects the tab or deep-links with `TICKETS_LIST_ALL` which clears
 * both the tab and the period narrowing. The dashboard at `/` no
 * longer carries a ticket table at all.
 */

export const DEMO_TICKET_TITLES = {
  // B3 Amsterdam — WAITING_CUSTOMER_APPROVAL. Used by Sprint 16, 17,
  // 27F-F1 specs. Amanda (B3 CUSTOMER_USER) sees Approve / Reject;
  // Iris (B1+B2) cannot reach it; building manager Gokhan can reach
  // it but does NOT see Approve / Reject; SUPER_ADMIN / COMPANY_ADMIN
  // clicking Approve opens the override modal.
  pantry_wca: "[DEMO] Pantry zeepdispenser",
  // B1 Amsterdam — CLOSED. Used by Sprint 17, 22 mobile + copy
  // polish specs. Walks through 4 transitions during seed.
  kitchen_closed: "[DEMO] Closed kitchen tap",
} as const;

/**
 * FE-6 — the tickets list with no tab pin and no period pin. `status=ALL`
 * parses to "no status filter" (every tab), `period=all_time` lifts the
 * default this-month window, so every seeded ticket the actor may see
 * is on the first page regardless of when the seed ran.
 */
export const TICKETS_LIST_ALL = "/tickets?status=ALL&period=all_time";

/**
 * FE-3 — the ticket detail page is tabbed (`?tab=`). The assignment
 * surfaces (responsible managers, staff assignment, the STAFF
 * "request assignment" block) live under the People tab; the fact
 * block, the primary action and the messages composer are on
 * Overview. Click the tab button so the tabbed section mounts.
 */
export async function openTicketTab(
  page: Page,
  tab: "overview" | "people" | "plan" | "money" | "messages",
): Promise<void> {
  const button = page.locator(`[data-testid="ticket-tab-${tab}"]`);
  await expect(button).toBeVisible({ timeout: 10_000 });
  await button.click();
}

/**
 * FE-3 — corrections and provider overrides sit behind the
 * "Geavanceerd" / "Advanced" fold of the workflow card, and the
 * non-primary forward steps behind the "other steps" fold. Open
 * whichever folds exist so every `workflow-move-*` button is in the
 * DOM before a spec counts or clicks them. Both toggles are optional:
 * a ticket with nothing to fold renders neither.
 */
export async function openWorkflowFolds(page: Page): Promise<void> {
  for (const testId of [
    "ticket-other-steps-toggle",
    "workflow-corrections-toggle",
  ]) {
    const toggle = page.locator(`[data-testid="${testId}"]`);
    if ((await toggle.count()) > 0) {
      const expanded = await toggle.first().getAttribute("aria-expanded");
      if (expanded !== "true") await toggle.first().click();
    }
  }
}

/**
 * Resolves the numeric ticket ID for a given demo title via the
 * authenticated backend API. The actor under test must already be
 * logged in on the supplied page (i.e. `loginAs` ran first) — we
 * read their access token from `localStorage` and reuse it.
 *
 * Throws if no match. Callers should cache the result for the
 * lifetime of a single test.
 */
export async function resolveDemoTicketId(
  page: Page,
  title: string,
): Promise<number> {
  const id = await page.evaluate(async (searchTitle: string) => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      throw new Error(
        "resolveDemoTicketId: no accessToken in localStorage; call loginAs first",
      );
    }
    // FE-7 — the page's own origin proxies /api in every harness (the
    // Vite dev server, vite preview, the prod nginx); a hardcoded
    // backend host fails CORS/ALLOWED_HOSTS the moment the frontend is
    // served through a proxy.
    const url = `/api/tickets/?search=${encodeURIComponent(
      searchTitle,
    )}&page_size=20`;
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      throw new Error(
        `resolveDemoTicketId: GET /api/tickets/?search=${searchTitle} → ${response.status}`,
      );
    }
    const body = (await response.json()) as {
      results?: Array<{ id: number; title: string }>;
    };
    const match = (body.results ?? []).find((t) => t.title === searchTitle);
    if (!match) {
      throw new Error(
        `resolveDemoTicketId: no ticket with title "${searchTitle}" in /api/tickets/ scope`,
      );
    }
    return match.id;
  }, title);
  return id;
}

/**
 * GET a backend path from inside the page context with the signed-in
 * actor's own token (the same trick as `resolveDemoTicketId`): scope
 * assertions read what the API tells THIS actor, without a second
 * login and regardless of how the harness proxies the API.
 */
export async function pageApiGet<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (apiPath: string) => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      throw new Error("pageApiGet: no accessToken in localStorage; call loginAs first");
    }
    const response = await fetch(`http://localhost:8000${apiPath}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      throw new Error(`pageApiGet: GET ${apiPath} → ${response.status}`);
    }
    return (await response.json()) as T;
  }, path) as Promise<T>;
}

/** The building id for a seeded building name, as seen by the actor. */
export async function resolveBuildingIdForPage(
  page: Page,
  buildingName: string,
): Promise<number | null> {
  const body = await pageApiGet<{ results: Array<{ id: number; name: string }> }>(
    page,
    "/api/buildings/?page_size=200",
  );
  return body.results.find((b) => b.name === buildingName)?.id ?? null;
}

/**
 * FE-6 — the tickets list is paginated (25 newest first), so "every
 * building in scope appears on page 1" is not a claim the page can
 * make. The count endpoint with the list's own `building` filter is:
 * how many tickets THIS actor may see at that building, every page.
 */
export async function ticketCountAtBuilding(
  page: Page,
  buildingName: string,
): Promise<number> {
  const buildingId = await resolveBuildingIdForPage(page, buildingName);
  if (buildingId === null) return 0;
  const body = await pageApiGet<{ count: number }>(
    page,
    `/api/tickets/?building=${buildingId}&page_size=1`,
  );
  return body.count;
}

/**
 * Sprint 27F's mutating spec drives "[DEMO] Pantry zeepdispenser" from
 * WAITING_CUSTOMER_APPROVAL to APPROVED, and every later spec that
 * needs Amanda's Approve / Reject then finds a settled ticket. Walk it
 * back as SUPER_ADMIN along the state machine's own path
 * (APPROVED -> CLOSED -> REOPENED_BY_ADMIN -> IN_PROGRESS ->
 * WAITING_CUSTOMER_APPROVAL) so the fixture is what the seed made it.
 * Best-effort: a step the machine refuses simply ends the walk.
 */
export async function restorePantryToWaitingCustomerApproval(): Promise<void> {
  const sa: APIRequestContext = await apiAs(DEMO_USERS.super.email);
  try {
    const list = await sa.get(
      `/api/tickets/?search=${encodeURIComponent(DEMO_TICKET_TITLES.pantry_wca)}&page_size=20`,
    );
    if (list.status() !== 200) return;
    const body = (await list.json()) as {
      results: Array<{ id: number; title: string; status: string }>;
    };
    const ticket = body.results.find((t) => t.title === DEMO_TICKET_TITLES.pantry_wca);
    if (!ticket || ticket.status === "WAITING_CUSTOMER_APPROVAL") return;
    const path: Record<string, string> = {
      APPROVED: "CLOSED",
      REJECTED: "IN_PROGRESS",
      CLOSED: "REOPENED_BY_ADMIN",
      REOPENED_BY_ADMIN: "IN_PROGRESS",
      IN_PROGRESS: "WAITING_CUSTOMER_APPROVAL",
    };
    let status = ticket.status;
    for (let step = 0; step < 6 && status !== "WAITING_CUSTOMER_APPROVAL"; step++) {
      const next = path[status];
      if (!next) return;
      const response = await sa.post(`/api/tickets/${ticket.id}/status/`, {
        data: {
          to_status: next,
          note: "e2e fixture reset",
          override_reason: "e2e fixture reset",
        },
      });
      if (response.status() !== 200) return;
      status = next;
    }
  } finally {
    await sa.dispose();
  }
}
