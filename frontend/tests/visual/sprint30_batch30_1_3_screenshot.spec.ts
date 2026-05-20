import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "../e2e/fixtures/demoUsers";
import { loginAs } from "../e2e/fixtures/login";

/**
 * Sprint 30 Batch 30.1.3 — visual evidence for the workflow-card
 * unification of the customer-decision override flow.
 *
 *   1. tid=83 (WAITING_CUSTOMER_APPROVAL) at rest as SUPER_ADMIN —
 *      exactly two primary buttons (Approve top, Reject bottom). No
 *      separate override card.
 *   2. Same view after pressing Approve — the button arms inline with
 *      a compact reason textarea + Confirm/Cancel pair.
 *   3. STAFF (Ahmet) on the IN_PROGRESS hallway-scuff ticket opening
 *      the Complete Work modal — label reads "note or photo
 *      (required)", submit is disabled until evidence is provided.
 *
 * Output is checked into `frontend/tests/visual/`, NOT under
 * `tests/e2e/`, so it does not run in the regular spec bundle. Each
 * spec uses runtime ID resolution via the ticket list so the
 * screenshots remain robust under `--reset-tickets` autoincrement
 * churn.
 */

async function resolveTicketId(
  page: import("@playwright/test").Page,
  title: string,
): Promise<number> {
  return page.evaluate(async (searchTitle: string) => {
    const token = localStorage.getItem("accessToken");
    if (!token) throw new Error("no token");
    const url = `http://localhost:8000/api/tickets/?search=${encodeURIComponent(
      searchTitle,
    )}&page_size=20`;
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(`GET tickets ${response.status}`);
    const body = (await response.json()) as {
      results?: Array<{ id: number; title: string }>;
    };
    const match = (body.results ?? []).find((t) => t.title === searchTitle);
    if (!match) throw new Error(`no ticket "${searchTitle}"`);
    return match.id;
  }, title);
}

test("WCA workflow card at rest — Approve top / Reject bottom, no separate override card", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  const ticketId = await resolveTicketId(page, "[DEMO] Pantry zeepdispenser");
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);
  // Two primary override targets must be visible. Their data-testids
  // are explicit (workflow-move-APPROVED above workflow-move-REJECTED).
  await expect(
    page.locator('[data-testid="workflow-move-APPROVED"]'),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.locator('[data-testid="workflow-move-REJECTED"]'),
  ).toBeVisible();
  // No separate override card mounted — the override-modal testid
  // only resolves once a decision button is pressed.
  await expect(
    page.locator('[data-testid="ticket-override-modal"]'),
  ).toHaveCount(0);
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_3_wca_at_rest.png",
    fullPage: true,
  });
});

test("WCA workflow card armed — pressing Approve expands inline reason + Confirm/Cancel", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.super);
  const ticketId = await resolveTicketId(page, "[DEMO] Pantry zeepdispenser");
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);
  await page.locator('[data-testid="workflow-move-APPROVED"]').click();
  // Inline arming block resolves via the 27F-preserved testid.
  await expect(
    page.locator('[data-testid="ticket-override-modal"]'),
  ).toBeVisible({ timeout: 5_000 });
  await expect(
    page.locator('[data-testid="ticket-override-reason"]'),
  ).toBeVisible();
  await expect(
    page.locator('[data-testid="ticket-override-submit"]'),
  ).toBeVisible();
  await expect(
    page.locator('[data-testid="ticket-override-cancel"]'),
  ).toBeVisible();
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_3_wca_armed.png",
    fullPage: true,
  });
});

test("STAFF completion-evidence required state — note or photo gate, submit disabled", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.staffOsius);
  const ticketId = await resolveTicketId(
    page,
    "[DEMO] In progress hallway scuff",
  );
  await page.goto(`/tickets/${ticketId}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_500);
  // Open the Complete work modal — Ahmet is the assigned STAFF on this
  // IN_PROGRESS ticket, so the CTA is rendered.
  await page.locator('[data-testid="ticket-staff-complete-button"]').click();
  await expect(
    page.locator('[data-testid="ticket-staff-complete-modal"]'),
  ).toBeVisible({ timeout: 10_000 });
  // The submit button must be disabled until either a note is typed
  // or a photo is attached.
  await expect(
    page.locator('[data-testid="ticket-staff-complete-submit"]'),
  ).toBeDisabled();
  await page.screenshot({
    path: "tests/visual/sprint30_batch30_1_3_staff_required.png",
    fullPage: true,
  });
});
