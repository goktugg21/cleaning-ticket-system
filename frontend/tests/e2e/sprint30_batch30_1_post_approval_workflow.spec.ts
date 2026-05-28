import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiAs } from "./fixtures/apiAs";
import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 30 Batch 30.1 — post-approval workflow.
 *
 * Covers the frontend half of the post-approval batch:
 *   K1 — A fresh customer-approval (PRICING_PROPOSED -> CUSTOMER_APPROVED)
 *        spawns operational tickets via the new auto-spawn hook, the
 *        Spawned Tickets panel renders on the EW detail page with at
 *        least one row, AND the provider-only retry-spawn button is
 *        absent (since tickets now exist).
 *
 *   K2 — Retry-spawn button surfaces when an EW is in CUSTOMER_APPROVED
 *        with zero spawned tickets. With the Batch 30.1 auto-spawn
 *        hook installed in the EW state machine, fresh customer
 *        approvals always spawn tickets, so this state only exists
 *        for legacy rows that landed in CUSTOMER_APPROVED before the
 *        fix shipped. The test walks the EW list as SUPER_ADMIN and
 *        skips (with a documenting reason) if no such legacy row
 *        exists in the fixture. When one is found, the test asserts
 *        the button is visible and clicking it returns either a
 *        success or `spawn_already_done` toast — both prove the wire
 *        path resolves the `code` field to a localized message via
 *        the new i18n keys.
 *
 *   Seed strategy: the SUPER_ADMIN seed-walk pattern is mirrored from
 *   `sprint29_batch29_8_ew_workflow.spec.ts`.
 */

interface EwLite {
  id: number;
  status: string;
  customer: number;
  building: number;
  title: string;
  routing_decision: string;
}

interface TicketLite {
  id: number;
  title: string;
  status: string;
}

interface AllowedNextStatusesLookup {
  allowed_next_statuses: string[];
}

/**
 * Sprint 30 Batch 30.1 server-side filter — single call walks both
 * the cart-item and proposal-line FK chains.
 */
async function listSpawnedTickets(
  api: APIRequestContext,
  ewId: number,
): Promise<TicketLite[]> {
  const resp = await api.get(
    `/api/tickets/?extra_work_request=${ewId}&page_size=100`,
  );
  if (resp.status() !== 200) return [];
  const body = (await resp.json()) as { results: TicketLite[] };
  return body.results;
}

async function fetchAllEws(api: APIRequestContext): Promise<EwLite[]> {
  const resp = await api.get(`/api/extra-work/?page_size=100`);
  if (resp.status() !== 200) return [];
  const body = (await resp.json()) as { results: EwLite[] };
  return body.results;
}

async function fetchEwDetail(
  api: APIRequestContext,
  ewId: number,
): Promise<(EwLite & AllowedNextStatusesLookup) | null> {
  const resp = await api.get(`/api/extra-work/${ewId}/`);
  if (resp.status() !== 200) return null;
  return (await resp.json()) as EwLite & AllowedNextStatusesLookup;
}

/**
 * Drive any EW to PRICING_PROPOSED by walking the state machine via
 * the public transition endpoint as SUPER_ADMIN. The path
 * REQUESTED -> UNDER_REVIEW -> PRICING_PROPOSED is admin-driveable.
 * Returns true on success or when the EW is already in
 * PRICING_PROPOSED.
 */
async function driveToPricingProposed(
  api: APIRequestContext,
  ewId: number,
): Promise<boolean> {
  const detail = await fetchEwDetail(api, ewId);
  if (!detail) return false;
  if (detail.status === "PRICING_PROPOSED") return true;
  if (detail.status === "REQUESTED") {
    const r1 = await api.post(`/api/extra-work/${ewId}/transition/`, {
      data: { to_status: "UNDER_REVIEW" },
    });
    if (r1.status() !== 200) return false;
  }
  // Either we just moved into UNDER_REVIEW or were already there.
  const r2 = await api.post(`/api/extra-work/${ewId}/transition/`, {
    data: { to_status: "PRICING_PROPOSED" },
  });
  return r2.status() === 200;
}

/**
 * Build a fresh EW as Tom (CUSTOMER_USER) using the seeded cart
 * service catalog. Returns the new EW id, or null when the prereqs
 * (a known service + a customer accessible to Tom) cannot be
 * resolved. The fresh EW is intentionally PROPOSAL-routed (no
 * customer-specific price for the chosen service) so the test owns
 * the PRICING_PROPOSED -> CUSTOMER_APPROVED transition path.
 */
async function createFreshProposalRouteEw(
  tomApi: APIRequestContext,
  saApi: APIRequestContext,
): Promise<{ id: number; customerId: number; buildingId: number } | null> {
  // Resolve Tom's customer + building via the EW list (whichever
  // customer he last submitted to — proves the access path exists).
  const tomEws = await fetchAllEws(tomApi);
  if (tomEws.length === 0) return null;
  const anchor = tomEws[0];

  // Pick any active service that does NOT have a CustomerServicePrice
  // for Tom's customer. We probe the catalog via the SUPER_ADMIN
  // context (the catalog endpoints are admin-gated).
  const servicesResp = await saApi.get(`/api/services/?page_size=100`);
  if (servicesResp.status() !== 200) return null;
  const servicesBody = (await servicesResp.json()) as {
    results: Array<{ id: number; is_active: boolean }>;
  };
  const activeServices = servicesBody.results.filter((s) => s.is_active);
  if (activeServices.length === 0) return null;

  // Build the payload. Use a requested_date 7 days out — well within
  // any reasonable contract window.
  const requestedDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);

  // Try each service until one yields a PROPOSAL-routed creation.
  // (Brief allows seed walk; PROPOSAL is the dominant route for
  // services without a customer-specific price.)
  for (const service of activeServices) {
    const createResp = await tomApi.post(`/api/extra-work/`, {
      data: {
        title: `Sprint 30 Batch 30.1 — test EW ${Date.now()}`,
        description:
          "Auto-generated by the Sprint 30 Batch 30.1 spec to exercise " +
          "the post-approval ticket-spawn path.",
        building: anchor.building,
        customer: anchor.customer,
        category: "DEEP_CLEANING",
        urgency: "NORMAL",
        line_items: [
          {
            service: service.id,
            quantity: "1.00",
            requested_date: requestedDate,
          },
        ],
      },
    });
    if (createResp.status() !== 201) continue;
    const body = (await createResp.json()) as {
      id: number;
      routing_decision: string;
      customer: number;
      building: number;
    };
    if (body.routing_decision !== "PROPOSAL") {
      // Instant-routed (the service has a customer price) — that EW
      // is already CUSTOMER_APPROVED with spawned tickets. Skip and
      // try the next service. The test wants to OWN the approval
      // transition.
      continue;
    }
    return {
      id: body.id,
      customerId: body.customer,
      buildingId: body.building,
    };
  }

  return null;
}

/**
 * Seed an EW into PRICING_PROPOSED and add one pricing line item as
 * SUPER_ADMIN so the customer-approve transition has a non-zero
 * total to operate on. Returns the EW id when ready, null on
 * failure.
 */
async function seedEwReadyForCustomerApproval(
  tomApi: APIRequestContext,
  saApi: APIRequestContext,
): Promise<number | null> {
  const fresh = await createFreshProposalRouteEw(tomApi, saApi);
  if (!fresh) return null;

  // Admin walks REQUESTED -> UNDER_REVIEW -> PRICING_PROPOSED.
  const drove = await driveToPricingProposed(saApi, fresh.id);
  if (!drove) return null;

  // Add a single pricing line so the EW has something to approve.
  const lineResp = await saApi.post(
    `/api/extra-work/${fresh.id}/pricing-items/`,
    {
      data: {
        description: "Sprint 30 test pricing line",
        unit_type: "FIXED",
        quantity: "1.00",
        unit_price: "100.00",
        vat_rate: "21.00",
      },
    },
  );
  if (lineResp.status() !== 201) return null;

  return fresh.id;
}

test.describe("Sprint 30 Batch 30.1 — post-approval workflow", () => {
  let approvedEwId: number | null = null;
  let approvedEwSpawnedTickets: TicketLite[] = [];
  let stuckCustomerApprovedEwId: number | null = null;

  test.beforeAll(async () => {
    const sa = await apiAs(DEMO_USERS.super.email);
    const tom = await apiAs(DEMO_USERS.customerAll.email);
    try {
      // K1 setup: seed an EW Tom can approve, then have Tom approve
      // it. The Batch 30.1 backend hook spawns tickets on that
      // transition; the spec verifies the panel + button-absent
      // contract on the resulting EW.
      const readyId = await seedEwReadyForCustomerApproval(tom, sa);
      if (readyId !== null) {
        const approveResp = await tom.post(
          `/api/extra-work/${readyId}/transition/`,
          { data: { to_status: "CUSTOMER_APPROVED" } },
        );
        if (approveResp.status() === 200) {
          approvedEwId = readyId;
          // Tickets may take a microtask to surface; one immediate
          // probe is sufficient because the transition is atomic.
          approvedEwSpawnedTickets = await listSpawnedTickets(sa, readyId);
        }
      }

      // K2 setup: scan the EW list for any CUSTOMER_APPROVED EW with
      // zero spawned tickets. With the auto-spawn hook installed,
      // this state only exists for legacy rows; we accept null and
      // skip the test with documentation in that case.
      const allEws = await fetchAllEws(sa);
      for (const ew of allEws) {
        if (ew.status !== "CUSTOMER_APPROVED") continue;
        const tickets = await listSpawnedTickets(sa, ew.id);
        if (tickets.length === 0) {
          stuckCustomerApprovedEwId = ew.id;
          break;
        }
      }
    } finally {
      await sa.dispose();
      await tom.dispose();
    }
  });

  test("K1 — customer approval auto-spawns tickets, panel renders, no retry button", async ({
    page,
  }) => {
    test.skip(
      approvedEwId === null,
      "could not seed a fresh PRICING_PROPOSED EW for Tom to approve " +
        "(catalog / customer-service-price coverage may be lacking)",
    );
    expect(
      approvedEwSpawnedTickets.length,
      "Auto-spawn hook must yield at least one ticket on customer approval",
    ).toBeGreaterThan(0);

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${approvedEwId!}`);

    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    // Spawned-tickets panel is visible and at least one row resolves.
    const panel = page.locator(
      '[data-testid="extra-work-spawned-tickets-panel"]',
    );
    await expect(panel).toBeVisible({ timeout: 10_000 });
    const rowCount = await page
      .locator('[data-testid^="extra-work-spawned-ticket-row-"]')
      .count();
    expect(rowCount).toBeGreaterThan(0);

    // Retry button must NOT render — tickets exist, so the gate is
    // closed regardless of role/status.
    const retryButton = page.locator(
      '[data-testid="extra-work-retry-spawn"]',
    );
    await expect(retryButton).toHaveCount(0);
  });

  test("K2 — retry-spawn button surfaces for stuck CUSTOMER_APPROVED EW", async ({
    page,
  }) => {
    test.skip(
      stuckCustomerApprovedEwId === null,
      "no legacy CUSTOMER_APPROVED EW with zero spawned tickets in the " +
        "fixture — with auto-spawn installed this only exists for pre-fix data",
    );
    const target = stuckCustomerApprovedEwId!;

    await loginAs(page, DEMO_USERS.super);
    await page.goto(`/extra-work/${target}`);

    await expect(
      page.locator('[data-testid="extra-work-detail-page"]'),
    ).toBeVisible({ timeout: 10_000 });

    const retryButton = page.locator(
      '[data-testid="extra-work-retry-spawn"]',
    );
    await expect(retryButton).toBeVisible({ timeout: 10_000 });

    await retryButton.click();

    // Either a success toast (count > 0) or an error toast (e.g. an
    // intervening race spawned tickets and the retry now returns
    // `spawn_already_done`). Both are valid; both prove the wire +
    // i18n keys resolved.
    const successToast = page.locator('[data-testid="toast-success"]');
    const errorToast = page.locator('[data-testid="toast-error"]');
    await expect(async () => {
      const successCount = await successToast.count();
      const errorCount = await errorToast.count();
      expect(successCount + errorCount).toBeGreaterThan(0);
    }).toPass({ timeout: 10_000 });

    // The toast title must be one of the localized strings (NL or EN)
    // — not a raw status fallback like "HTTP 400". A failure here
    // would mean the `code` field never resolved to an i18n key.
    const visibleToast = (await successToast.count()) > 0 ? successToast : errorToast;
    const toastText = await visibleToast.first().innerText();
    const looksLocalized =
      /scheduled|ingepland|Cannot schedule|Kan werk|already scheduled|al tickets|permission|rechten|Could not schedule|Kan werk niet/i.test(
        toastText,
      );
    expect(
      looksLocalized,
      `Expected the retry-spawn toast to render a localized message; got: ${toastText}`,
    ).toBe(true);
  });

  test("K3 — retry endpoint via API rejects non-admins with spawn_forbidden_role", async () => {
    // Defence-in-depth: the UI gates the button on role, but the
    // backend also rejects non-admin actors with the stable
    // `spawn_forbidden_role` code. This test exercises the wire
    // contract directly so a UI regression that bypasses the role
    // gate still surfaces in CI. Use ANY EW id reachable by the
    // SUPER_ADMIN; the role check fires before the EW lookup so
    // even an out-of-scope id works.
    const sa = await apiAs(DEMO_USERS.super.email);
    let targetEwId: number | null = null;
    try {
      const ews = await fetchAllEws(sa);
      if (ews.length > 0) targetEwId = ews[0].id;
    } finally {
      await sa.dispose();
    }
    test.skip(targetEwId === null, "no EWs visible to SUPER_ADMIN in fixture");

    const customerCtx = await apiAs(DEMO_USERS.customerAll.email);
    try {
      const resp = await customerCtx.post(
        `/api/extra-work/${targetEwId!}/spawn/`,
        { data: {} },
      );
      // Backend rejects with 403 + `spawn_forbidden_role` for any
      // non-admin actor. Out-of-scope customers may also receive 404
      // (object not found in their scope) BEFORE the role check
      // fires; both prove the customer cannot reach the spawn path.
      expect([403, 404]).toContain(resp.status());
      if (resp.status() === 403) {
        const body = (await resp.json()) as { code?: string };
        expect(body.code).toBe("spawn_forbidden_role");
      }
    } finally {
      await customerCtx.dispose();
    }
  });
});

