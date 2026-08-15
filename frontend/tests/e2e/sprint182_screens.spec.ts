import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 182 C — the screens: one word, one meaning, fewer controls.
 *
 * Read-only assertions against the `seed_demo_data` fixture. What each
 * one is here to catch:
 *
 *   §1 the chips and the "All" tile counted different sets. The chips
 *      came from a hand-written eight-status array while `TicketStatus`
 *      has nine, so a converted ticket was counted by the total and by
 *      no chip. The invariant is arithmetic, so the test is arithmetic:
 *      All == the sum of the chips, read off the rendered tiles.
 *
 *   §2 "Approved" labelled several different things. On a ticket it
 *      means the customer accepted the finished WORK, and the rendered
 *      string must say so — the bare word must not come back.
 *
 *   §3 an Extra Work's money was on the list row and not on the page
 *      you opened from it.
 *
 *   §4 ordinary tickets and chargeable-work tickets were mixed with no
 *      way to see only the ordinary ones.
 */

const STATUS_TILE = "tickets-status-tile-";

async function tileCount(page: import("@playwright/test").Page, value: string) {
  const tile = page.getByTestId(`${STATUS_TILE}${value}`);
  const text = await tile.locator(".status-tile-count").innerText();
  // An em dash is the honest "this list cannot know" (StatusTiles), and
  // it is not a number — the caller decides whether that is allowed.
  return text.trim() === "—" ? null : Number.parseInt(text.trim(), 10);
}

test.describe("Sprint 182 §1 — the chips and the total agree", () => {
  test("the All tile equals the sum of the status chips", async ({ page }) => {
    await loginAs(page, DEMO_USERS.super);
    // ?status=ALL so no chip is preselected and every tile is countable.
    await page.goto("/tickets?status=ALL");
    await expect(page.getByTestId("tickets-status-tiles")).toBeVisible({
      timeout: 10_000,
    });
    await page.waitForLoadState("networkidle");

    const all = await tileCount(page, "all");
    expect(all).not.toBeNull();

    const statuses = [
      "OPEN",
      "IN_PROGRESS",
      "WAITING_MANAGER_REVIEW",
      "WAITING_CUSTOMER_APPROVAL",
      "APPROVED",
      "REJECTED",
      "CLOSED",
      "REOPENED_BY_ADMIN",
    ];
    let sum = 0;
    for (const status of statuses) {
      const count = await tileCount(page, status);
      expect(count, `chip ${status} must carry a number`).not.toBeNull();
      sum += count ?? 0;
    }
    expect(sum).toBe(all);
  });

  test("there is no chip for the status the list does not work in", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/tickets?status=ALL");
    await expect(page.getByTestId("tickets-status-tiles")).toBeVisible({
      timeout: 10_000,
    });
    // A converted ticket became an Extra Work; it is tracked from there.
    await expect(
      page.getByTestId(`${STATUS_TILE}CONVERTED_TO_EXTRA_WORK`),
    ).toHaveCount(0);
  });
});

test.describe("Sprint 182 §2 — one word, one meaning", () => {
  test("an approved ticket reads 'Work approved', never the bare word", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/tickets?status=APPROVED");
    await expect(page.getByTestId("dashboard-tickets-section")).toBeVisible({
      timeout: 10_000,
    });

    // The chip carries the same string the rows do — one source.
    const chip = page.getByTestId(`${STATUS_TILE}APPROVED`);
    await expect(chip.locator(".status-tile-label")).toContainText(
      "Work approved",
    );
  });
});

test.describe("Sprint 182 §3 — the money is on the page you opened", () => {
  test("the Extra Work detail header carries the same total as the row", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/extra-work");
    await expect(page.getByTestId("extra-work-row").first()).toBeVisible({
      timeout: 10_000,
    });

    // The row's Total cell is the last-but-three column; read it from
    // the row, then open the row and read the header figure. The two are
    // the same `rowAmounts()` rule, so they must be the same string.
    const row = page.getByTestId("extra-work-row").first();
    const rowTotal = (await row.locator("td").nth(6).innerText()).trim();
    await row.click();

    const header = page.getByTestId("extra-work-header-total");
    await expect(header).toBeVisible({ timeout: 10_000 });
    await expect(header).toContainText(rowTotal);
  });
});

test.describe("Sprint 182 §4 — tickets only", () => {
  test("the work-type strip is visible and narrows the list", async ({
    page,
  }) => {
    await loginAs(page, DEMO_USERS.super);
    await page.goto("/tickets?status=ALL");
    await expect(page.getByTestId("tickets-work-type")).toBeVisible({
      timeout: 10_000,
    });

    // Always rendered, and "All work" is always one click away — the
    // house rule is that nothing is hidden with no way back.
    await expect(page.getByTestId("tickets-work-type-all")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await page.getByTestId("tickets-work-type-tickets").click();
    await expect(page.getByTestId("tickets-work-type-tickets")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // URL-backed, so the view survives a refresh and can be linked to.
    await expect(page).toHaveURL(/work=tickets/);
    await page.waitForLoadState("networkidle");

    // Nothing on this narrowed list carries an Extra Work origin pill.
    await expect(
      page.getByTestId("ticket-row-extra-work-origin"),
    ).toHaveCount(0);
  });
});
