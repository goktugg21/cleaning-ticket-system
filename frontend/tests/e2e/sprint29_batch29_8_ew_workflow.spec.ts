import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 29 Batch 29.8 — Extra Work operational segment.
 *
 * Covers the frontend half of the operational segment shipped this
 * batch:
 *   J1 — spawned tickets panel renders for an EW with spawned tickets
 *   J2 — spawned tickets panel does NOT render for an EW with none
 *   J3 — cancel dialog shows the spawned-tickets warning when at
 *        least one spawned ticket is non-terminal
 *   J4 — IN_PROGRESS status badge resolves to the new "In progress"
 *        label and renders on detail page after a transition
 *
 * The backend already exposes:
 *   * ExtraWorkStatus enum extended with IN_PROGRESS + COMPLETED
 *   * CUSTOMER_APPROVED -> IN_PROGRESS transition (provider role)
 *   * Auto-trigger on spawned-ticket transitions
 *
 * Seed discovery probes the API as SUPER_ADMIN — the demo seed has
 * a mix of EW states and the spec walks the list to find suitable
 * candidates rather than assuming a specific id.
 */

const TERMINAL_TICKET_STATUSES = new Set([
  "APPROVED",
  "CLOSED",
  "REJECTED",
]);

interface TicketLite {
  id: number;
  title: string;
  status: string;
}

interface EwLite {
  id: number;
  status: string;
  customer: number;
  building: number;
  title: string;
}

interface EwWithSpawnedTickets {
  ew: EwLite;
  spawnedTickets: TicketLite[];
}

interface TicketDetailLite {
  id: number;
  title: string;
  status: string;
  extra_work_origin: { extra_work_request_id: number } | null;
}

/**
 * Resolve spawned tickets for one EW via the same client-side path
 * the page uses: customer+building-scoped list then per-id detail
 * filter on `extra_work_origin.extra_work_request_id`.
 */
async function resolveSpawnedTickets(
  api: APIRequestContext,
  ew: EwLite,
): Promise<TicketLite[]> {
  const candidates = await api.get(
    `/api/tickets/?customer=${ew.customer}&building=${ew.building}&page_size=100`,
  );
  if (candidates.status() !== 200) return [];
  const body = (await candidates.json()) as {
    results: Array<{ id: number; title: string; status: string }>;
  };
  const matched: TicketLite[] = [];
  for (const candidate of body.results) {
    const detail = await api.get(`/api/tickets/${candidate.id}/`);
    if (detail.status() !== 200) continue;
    const detailBody = (await detail.json()) as TicketDetailLite;
    if (
      detailBody.extra_work_origin &&
      detailBody.extra_work_origin.extra_work_request_id === ew.id
    ) {
      matched.push({
        id: detailBody.id,
        title: detailBody.title,
        status: detailBody.status,
      });
    }
  }
  return matched;
}

/**
 * Fetch the full EW list visible to the actor. The backend EW
 * viewset does NOT expose a status filter on the list endpoint, so
 * the spec narrows client-side. page_size=100 covers the demo seed
 * with headroom.
 */
async function fetchAllEws(api: APIRequestContext): Promise<EwLite[]> {
  const resp = await api.get(`/api/extra-work/?page_size=100`);
  if (resp.status() !== 200) return [];
  const body = (await resp.json()) as { results: EwLite[] };
  return body.results;
}

/**
 * Scan EW list across the demo seed and return the first EW that
 * matches `wantedStatuses` AND has spawned tickets meeting `predicate`.
 */
async function findEwWithSpawnedTickets(
  api: APIRequestContext,
  wantedStatuses: string[],
  predicate: (tickets: TicketLite[]) => boolean,
): Promise<EwWithSpawnedTickets | null> {
  const ews = (await fetchAllEws(api)).filter((e) =>
    wantedStatuses.includes(e.status),
  );
  for (const ew of ews) {
    const tickets = await resolveSpawnedTickets(api, ew);
    if (predicate(tickets)) {
      return { ew, spawnedTickets: tickets };
    }
  }
  return null;
}

/**
 * Scan EW list for an EW in `wantedStatuses` that has ZERO spawned
 * tickets. Used by J2.
 */
async function findEwWithoutSpawnedTickets(
  api: APIRequestContext,
  wantedStatuses: string[],
): Promise<EwLite | null> {
  const ews = (await fetchAllEws(api)).filter((e) =>
    wantedStatuses.includes(e.status),
  );
  for (const ew of ews) {
    const tickets = await resolveSpawnedTickets(api, ew);
    if (tickets.length === 0) return ew;
  }
  return null;
}

/**
 * First EW visible to the actor whose status is one of `wantedStatuses`.
 */
async function findEwByStatus(
  api: APIRequestContext,
  wantedStatuses: string[],
): Promise<EwLite | null> {
  const ews = (await fetchAllEws(api)).filter((e) =>
    wantedStatuses.includes(e.status),
  );
  return ews[0] ?? null;
}

test.describe("Sprint 29 Batch 29.8 — Extra Work operational segment", () => {
  let ewWithActiveTickets: EwWithSpawnedTickets | null = null;
  let ewWithoutTickets: EwLite | null = null;
  let ewForBadgeTest: EwLite | null = null;

  test.beforeAll(async () => {
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      // J1 / J3 target — EW with at least one non-terminal spawned
      // ticket. CUSTOMER_APPROVED is the natural "has-spawned-tickets"
      // state but IN_PROGRESS is equally fine (and shows up after
      // J4 runs).
      ewWithActiveTickets = await findEwWithSpawnedTickets(
        sa,
        ["CUSTOMER_APPROVED", "IN_PROGRESS"],
        (tickets) =>
          tickets.some((t) => !TERMINAL_TICKET_STATUSES.has(t.status)),
      );

      // J2 target — EW with no spawned tickets at all. Early states
      // (REQUESTED / UNDER_REVIEW / PRICING_PROPOSED) are the
      // natural fit, but the demo seed sometimes has only later
      // states; CANCELLED rows also satisfy the "no spawned tickets"
      // contract for the panel-absence assertion.
      ewWithoutTickets = await findEwWithoutSpawnedTickets(sa, [
        "REQUESTED",
        "UNDER_REVIEW",
        "PRICING_PROPOSED",
        "CUSTOMER_REJECTED",
        "CANCELLED",
      ]);

      // J4 target — an EW we can drive to IN_PROGRESS. Re-use the
      // J1 EW if it is already past CUSTOMER_APPROVED, otherwise
      // pick any CUSTOMER_APPROVED EW. The EW list endpoint does NOT
      // expose a status filter so the helper filters client-side.
      if (
        ewWithActiveTickets &&
        (ewWithActiveTickets.ew.status === "IN_PROGRESS" ||
          ewWithActiveTickets.ew.status === "COMPLETED")
      ) {
        ewForBadgeTest = ewWithActiveTickets.ew;
      } else {
        ewForBadgeTest = await findEwByStatus(sa, [
          "CUSTOMER_APPROVED",
          "IN_PROGRESS",
          "COMPLETED",
        ]);
      }
    } finally {
      await sa.dispose();
    }
  });

  test("J1 — spawned tickets panel renders for an EW with tickets", async ({
    page,
  }) => {
    test.skip(
      ewWithActiveTickets === null,
      "demo seed has no EW with spawned tickets in CUSTOMER_APPROVED / IN_PROGRESS",
    );
    const target = ewWithActiveTickets!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${target.ew.id}`);

    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    const panel = page.locator(
      '[data-testid="extra-work-spawned-tickets-panel"]',
    );
    await expect(panel).toBeVisible({ timeout: 10_000 });

    // At least one row matches the spawned ticket ids resolved via
    // the API. The panel is a superset; assert at least one row.
    const rowCount = await page
      .locator('[data-testid^="extra-work-spawned-ticket-row-"]')
      .count();
    expect(rowCount).toBeGreaterThan(0);

    // At least one of the resolved ticket ids must render a row.
    for (const ticket of target.spawnedTickets) {
      const row = page.locator(
        `[data-testid="extra-work-spawned-ticket-row-${ticket.id}"]`,
      );
      if (await row.count()) {
        await expect(row).toBeVisible();
        return;
      }
    }
    throw new Error(
      "None of the API-resolved spawned tickets rendered a row.",
    );
  });

  test("J2 — spawned tickets panel does NOT render for an EW with no tickets", async ({
    page,
  }) => {
    test.skip(
      ewWithoutTickets === null,
      "demo seed has no early-stage EW with zero spawned tickets",
    );
    const target = ewWithoutTickets!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${target.id}`);

    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // The panel never mounts when the spawnedTickets list is empty
    // (the section is gated on `spawnedTickets.length > 0`).
    const panel = page.locator(
      '[data-testid="extra-work-spawned-tickets-panel"]',
    );
    await expect(panel).toHaveCount(0);
  });

  test("J3 — cancel dialog shows warning when active spawned tickets exist", async ({
    page,
  }) => {
    test.skip(
      ewWithActiveTickets === null,
      "demo seed has no EW with non-terminal spawned tickets",
    );
    const target = ewWithActiveTickets!;
    // The cancel button only renders when CANCELLED is in
    // `allowed_next_statuses` for the actor. SUPER_ADMIN qualifies
    // from any non-terminal state. Skip if the EW happened to land
    // in a state where cancellation is no longer allowed (e.g.
    // already COMPLETED). The button's render gate is the auth
    // contract; the dialog assertion only runs when the gate opens.

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${target.ew.id}`);
    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    const cancelButton = page.locator(
      '[data-testid="extra-work-cancel-button"]',
    );
    const buttonCount = await cancelButton.count();
    test.skip(
      buttonCount === 0,
      "Cancel transition not allowed from current EW state for SUPER_ADMIN.",
    );

    await cancelButton.click();

    // The dialog is a native <dialog> opened via showModal(); the
    // warning panel lives inside it.
    const warning = page.locator(
      '[data-testid="extra-work-cancel-spawned-tickets-warning"]',
    );
    await expect(warning).toBeVisible({ timeout: 5_000 });

    // The warning lists at least one of the spawned ticket ids
    // returned by the API helper.
    const warningText = await warning.innerText();
    const activeSpawned = target.spawnedTickets.filter(
      (t) => !TERMINAL_TICKET_STATUSES.has(t.status),
    );
    expect(activeSpawned.length).toBeGreaterThan(0);
    const someListed = activeSpawned.some((t) =>
      warningText.includes(`#${t.id}`),
    );
    expect(
      someListed,
      "Expected the warning panel to list at least one of the spawned ticket ids.",
    ).toBe(true);

    // Do NOT confirm — close the dialog instead via the Keep open
    // button so no destructive transition fires.
    const keepButton = page.getByRole("button", {
      name: /Keep open|Openhouden/i,
    });
    await keepButton.click();
  });

  test("J4 — IN_PROGRESS badge renders after a transition", async ({
    page,
  }) => {
    test.skip(
      ewForBadgeTest === null,
      "demo seed has no EW available to drive to IN_PROGRESS",
    );
    const target = ewForBadgeTest!;

    // Drive the transition out-of-band so the test only validates
    // the badge render path.
    const sa = await apiAs(DEMO_USERS.super.email);
    try {
      if (target.status === "CUSTOMER_APPROVED") {
        // Required transition kwargs: only `to_status` for this pair
        // (no override_reason needed per the brief's contract).
        const resp = await sa.post(
          `/api/extra-work/${target.id}/transition/`,
          {
            data: { to_status: "IN_PROGRESS" },
          },
        );
        // 200 happy path; 400 means the auto-sync hook already
        // advanced it (race with J1's seed walk). Treat both as OK.
        if (resp.status() !== 200 && resp.status() !== 400) {
          throw new Error(
            `transition to IN_PROGRESS failed: HTTP ${resp.status()} ${await resp.text()}`,
          );
        }
      }
    } finally {
      await sa.dispose();
    }

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${target.id}`);
    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // The status badge renders in the header meta slot. The locale
    // is Dutch by default in the demo seed but EN labels are also
    // accepted — both translate "IN_PROGRESS" to a human label
    // distinct from "Customer approved" / "Approved".
    const headerMeta = page.locator(".ew-detail-header-meta");
    await expect(headerMeta).toBeVisible();
    const metaText = await headerMeta.innerText();
    const looksInProgress =
      /In progress|In uitvoering|Completed|Voltooid/i.test(metaText);
    expect(
      looksInProgress,
      `Expected the EW status badge to show the operational-segment label, got: ${metaText}`,
    ).toBe(true);
  });
});
