import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

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
    const url = `http://localhost:8000/api/tickets/?search=${encodeURIComponent(
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
