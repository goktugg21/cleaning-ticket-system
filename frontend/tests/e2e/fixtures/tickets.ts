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
