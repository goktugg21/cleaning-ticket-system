import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 23C UI hardening tests.
 *
 *   1. /admin/staff-assignment-requests must not develop a horizontal
 *      page scroll at phone-class viewports (390 / 430 / 480 px). The
 *      Sprint 22 invariant is that body.scrollWidth ≤ viewport width
 *      (small rounding tolerance). The page previously rendered the
 *      desktop `.data-table` (min-width: 860px from index.css) without
 *      a mobile parallel; this hardening adds an `admin-card-list`
 *      sibling that the existing @media (max-width: 600px) rule swaps
 *      in.
 *
 *   2. TicketDetailPage must not render the raw i18n keys
 *      `assigned_staff_title`, `assigned_staff_empty`, or
 *      `assigned_staff_role`. Sprint 23B accidentally used a
 *      `:` namespace separator (`t("ticket_detail:assigned_staff_title")`)
 *      against a key whose home is the `common` namespace's flat
 *      prefix, which made i18next return the raw key. Sprint 23C
 *      moves the keys into the `ticket_detail` namespace and switches
 *      the calls to short keys, matching every other key on the page.
 *
 * Both tests are focused — they do not snapshot the whole page or
 * assert on copy beyond the presence/absence of the raw key strings.
 */

const MOBILE_390 = { width: 390, height: 844 };
const MOBILE_430 = { width: 430, height: 932 };
const MOBILE_480 = { width: 480, height: 853 };

async function expectNoBodyHorizontalOverflow(
  page: import("@playwright/test").Page,
  viewportWidth: number,
) {
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(scrollWidth).toBeLessThanOrEqual(viewportWidth + 1);
}

// =====================================================================
// /admin/staff-assignment-requests — mobile layout
// =====================================================================

for (const vp of [MOBILE_390, MOBILE_430, MOBILE_480]) {
  test(`/admin/staff-assignment-requests at ${vp.width}x${vp.height}: no horizontal page overflow`, async ({
    page,
  }) => {
    await page.setViewportSize(vp);
    await loginAs(page, DEMO_USERS.companyAdmin);
    await page.goto("/admin/staff-assignment-requests");
    await expect(
      page.locator('[data-testid="staff-requests-page"]'),
    ).toBeVisible({ timeout: 10_000 });
    // The desktop table sits inside `.admin-list-wrap` and must be
    // hidden at this viewport (the @media rule kicks in at <=600px).
    // We assert by reading computed display rather than absence so
    // the test still works in dark mode / future skin changes.
    const desktopDisplay = await page
      .locator(".admin-list-wrap")
      .first()
      .evaluate((el) => getComputedStyle(el as HTMLElement).display);
    expect(desktopDisplay).toBe("none");

    // The card list <ul> is always emitted (even empty); the empty-
    // state is a sibling. We only need to know the page settled
    // enough to render either, then check the invariant.
    const cardList = page.locator('[data-testid="staff-requests-card-list"]');
    await expect(cardList).toBeAttached({ timeout: 10_000 });

    // The core invariant: body must not scroll horizontally.
    await expectNoBodyHorizontalOverflow(page, vp.width);
  });
}

test("/admin/staff-assignment-requests at desktop width: table still renders", async ({
  page,
}) => {
  // Guards against the hardening accidentally hiding the desktop
  // layout everywhere. At a desktop viewport the admin-list-wrap
  // must be visible and the admin-card-list must be hidden.
  await page.setViewportSize({ width: 1280, height: 800 });
  await loginAs(page, DEMO_USERS.companyAdmin);
  await page.goto("/admin/staff-assignment-requests");
  await expect(
    page.locator('[data-testid="staff-requests-page"]'),
  ).toBeVisible({ timeout: 10_000 });
  const desktopDisplay = await page
    .locator(".admin-list-wrap")
    .first()
    .evaluate((el) => getComputedStyle(el as HTMLElement).display);
  expect(desktopDisplay).not.toBe("none");
  const cardListDisplay = await page
    .locator('[data-testid="staff-requests-card-list"]')
    .evaluate((el) => getComputedStyle(el as HTMLElement).display);
  expect(cardListDisplay).toBe("none");
});

// =====================================================================
// TicketDetailPage — no raw i18n keys
// =====================================================================

const RAW_I18N_KEYS = [
  "assigned_staff_title",
  "assigned_staff_empty",
  "assigned_staff_role",
  "request_assignment_hint",
  "request_assignment_success",
  "request_assignment_already_pending",
  "requesting_assignment",
];

test("Ticket detail does not render raw assigned_staff_* keys (SUPER_ADMIN view)", async ({
  page,
}) => {
  // Super admin sees every ticket and the full assigned_staff card.
  // Navigate to the dashboard, click the first ticket, then scan
  // the rendered body text for any of the raw key tokens. A real
  // translation must NOT contain the snake_case key literal.
  await loginAs(page, DEMO_USERS.super);
  await page.waitForLoadState("networkidle");
  const firstRow = page.locator(".data-table tbody tr").first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });
  await firstRow.locator("a.td-id").click();
  await expect(
    page.locator('[data-testid="assigned-staff-card"]'),
  ).toBeVisible({ timeout: 10_000 });
  const bodyText = (await page.locator("body").textContent()) ?? "";
  for (const key of RAW_I18N_KEYS) {
    expect(
      bodyText.includes(key),
      `Ticket detail must not render the raw i18n key "${key}"; ` +
        `if it does, the key is missing from its namespace JSON or ` +
        `the call uses the wrong namespace separator.`,
    ).toBe(false);
  }
});

test("Ticket detail does not render raw assigned_staff_* keys (STAFF view, with Request assignment block)", async ({
  page,
  baseURL,
}) => {
  // Staff sees the Request-assignment button — exercises 4 more keys
  // (request_assignment{,_hint,_success,_already_pending} +
  // requesting_assignment). Use the SUPER_ADMIN session via API
  // discovery to find a ticket in Ahmet's visibility (Osius
  // buildings), then sign in as Ahmet and navigate.
  void baseURL;
  await loginAs(page, DEMO_USERS.staffOsius);
  await page.waitForLoadState("networkidle");
  // STAFF dashboard shows the tickets they see. Open the first one.
  const firstRow = page.locator(".data-table tbody tr").first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });
  await firstRow.locator("a.td-id").click();
  await expect(
    page.locator('[data-testid="assigned-staff-card"]'),
  ).toBeVisible({ timeout: 10_000 });
  const bodyText = (await page.locator("body").textContent()) ?? "";
  for (const key of RAW_I18N_KEYS) {
    expect(bodyText.includes(key)).toBe(false);
  }
});
