import { expect, request, test } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * P-9 B — THE EXTRA WORK LIST IS FOUR TABS, AND THE TABS COVER THE SERVER.
 *
 * `/extra-work` lands on the first tab that has rows; each tab carries
 * its count; the four counts plus the cancelled door at the foot of
 * Finished equal the server's own `count` for the same actor (the P-8
 * guard, one level up). Every tab opens with one purpose sentence, one
 * money line, at most six columns and a next-step button per row; the
 * cancelled view has a way back; a `?status=` deep link lands on the
 * tab that holds it with the matching chip lit. Read-only.
 */
const TABS = ["to-price", "with-customer", "approved", "finished"] as const;

test("the Extra work tabs add up to the server and each tab says what it is for", async ({
  page,
  baseURL,
}) => {
  const apiBase = process.env.PLAYWRIGHT_API_BASE_URL ?? baseURL ?? "";
  const api = await request.newContext({ baseURL: apiBase });
  const token = await api.post("/api/auth/token/", {
    data: { email: DEMO_USERS.super.email, password: DEMO_PASSWORD },
  });
  expect(token.ok()).toBeTruthy();
  const { access } = (await token.json()) as { access: string };
  const list = await api.get("/api/extra-work/?page_size=100", {
    headers: { Authorization: `Bearer ${access}` },
  });
  expect(list.ok()).toBeTruthy();
  const serverCount = ((await list.json()) as { count: number }).count;

  await loginAs(page, DEMO_USERS.super);

  // The bare address lands on a tab.
  await page.goto("/extra-work");
  await expect(page).toHaveURL(/\/extra-work\/(to-price|with-customer|approved|finished)/);
  const loaded = page.getByTestId("extra-work-list-loaded-count");
  await expect(loaded).toBeVisible();
  await expect(loaded).toHaveAttribute("data-count", String(serverCount));
  await expect(page.getByTestId("extra-work-list-guard")).toHaveCount(0);

  const readCount = async (testId: string): Promise<number> =>
    Number((await page.getByTestId(testId).getAttribute("data-count")) ?? "0");

  // The four tab counts plus the cancelled door equal the server.
  let sum = 0;
  for (const tab of TABS) sum += await readCount(`extra-work-tab-${tab}`);
  await page.getByTestId("extra-work-tab-finished").click();
  await expect(page).toHaveURL(/\/extra-work\/finished/);
  const cancelled = await readCount("extra-work-cancelled-link");
  expect(sum + cancelled).toBe(serverCount);

  // Every tab: a purpose sentence; when it has rows, a money line, at
  // most six columns, rows and a next step on each; when it has none,
  // the empty state — never a blank.
  for (const tab of TABS) {
    await page.goto(`/extra-work/${tab}`);
    await expect(page.getByTestId(`extra-work-tab-${tab}`)).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("extra-work-tab-purpose")).toBeVisible();
    const count = await readCount(`extra-work-tab-${tab}`);
    if (count > 0) {
      await expect(page.getByTestId("extra-work-tab-money")).toBeVisible();
      expect(await page.locator("table thead th").count()).toBeLessThanOrEqual(6);
      const rows = page.getByTestId("extra-work-row");
      expect(await rows.count()).toBeGreaterThan(0);
      expect(await page.getByTestId("extra-work-next-step").count()).toBe(
        await rows.count(),
      );
      await expect(page.getByTestId("extra-work-list-empty")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("extra-work-list-empty")).toBeVisible();
    }
    await expect(page.getByTestId("extra-work-list-guard")).toHaveCount(0);
  }

  // The cancelled view: the same table, cancelled rows only, a way back.
  await page.goto("/extra-work/finished?view=cancelled");
  await expect(page.getByTestId("extra-work-cancelled-title")).toBeVisible();
  if (cancelled > 0) {
    expect(await page.getByTestId("extra-work-row").count()).toBeGreaterThan(0);
  } else {
    await expect(page.getByTestId("extra-work-list-empty")).toBeVisible();
  }
  await page.getByTestId("extra-work-back-to-finished").click();
  await expect(page).toHaveURL(/\/extra-work\/finished$/);
  await expect(page.getByTestId("extra-work-cancelled-title")).toHaveCount(0);

  // A dashboard deep link lands on the tab that holds the status, with
  // the matching chip lit.
  await page.goto("/extra-work?status=CUSTOMER_REJECTED");
  await expect(page).toHaveURL(/\/extra-work\/with-customer/);
  await expect(page.getByTestId("extra-work-chip-declined")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.goto("/extra-work?status=CANCELLED");
  await expect(page).toHaveURL(/\/extra-work\/finished\?view=cancelled/);
  await expect(page.getByTestId("extra-work-cancelled-title")).toBeVisible();
});
