import { expect, request, test } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * P-8R A1 — THE LIST NEVER RENDERS EMPTY OVER A FULL SERVER.
 *
 * Web-Claude's audit of the P-7 build saw /extra-work with every chip at
 * 0 and zero rows while `GET /api/extra-work/` returned 16 rows: the page
 * filtered the fetched rows down to one track and counted the chips over
 * what was left. This spec is the guard: the number the page says it
 * loaded must equal the server's own `count` for the same actor, and the
 * page's buckets must add up to it.
 *
 * P-9 B — the phase tiles became four tabs plus a cancelled door at the
 * foot of Finished. The guard is unchanged in meaning: page count ==
 * server count, and the four tab counts + cancelled == server count.
 * Read-only.
 */
test("the Extra work list shows and counts every row the server returns", async ({
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
  await page.goto("/extra-work");
  const loaded = page.getByTestId("extra-work-list-loaded-count");
  await expect(loaded).toBeVisible();
  await expect(loaded).toHaveAttribute("data-count", String(serverCount));
  await expect(page.getByTestId("extra-work-list-guard")).toHaveCount(0);

  // The bare address lands on the first tab that has rows, so a
  // non-empty server never shows an empty first screen.
  if (serverCount > 0) {
    await expect(page.getByTestId("extra-work-list-empty")).toHaveCount(0);
    expect(await page.getByTestId("extra-work-row").count()).toBeGreaterThan(0);
  }

  // The tabs plus the cancelled door add up to the server.
  const readCount = async (testId: string): Promise<number> =>
    Number((await page.getByTestId(testId).getAttribute("data-count")) ?? "0");
  let sum = 0;
  for (const tab of ["to-price", "with-customer", "approved", "finished"]) {
    sum += await readCount(`extra-work-tab-${tab}`);
  }
  await page.goto("/extra-work/finished");
  sum += await readCount("extra-work-cancelled-link");
  expect(sum).toBe(serverCount);
});
