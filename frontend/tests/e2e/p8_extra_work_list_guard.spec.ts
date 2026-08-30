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
 * loaded, the "All" tile and the sum of the phase tiles must all equal
 * the server's own `count` for the same actor. Read-only.
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

  // The tiles: "All" equals the server, and the phase tiles add up to it.
  const readCount = async (testId: string): Promise<number> => {
    const text = await page
      .getByTestId(testId)
      .locator(".status-tile-count")
      .innerText();
    return Number(text.replace(/\D/g, "") || "0");
  };
  if (serverCount > 0) {
    await expect(page.getByTestId("extra-work-list-empty")).toHaveCount(0);
    expect(await page.locator("table tbody tr").count()).toBeGreaterThan(0);
  }
  expect(await readCount("extra-work-status-tile-all")).toBe(serverCount);
  const phaseTiles = page.locator(
    '[data-testid^="extra-work-status-tile-"]:not([data-testid="extra-work-status-tile-all"])',
  );
  let sum = 0;
  for (let i = 0; i < (await phaseTiles.count()); i++) {
    const text = await phaseTiles.nth(i).locator(".status-tile-count").innerText();
    sum += Number(text.replace(/\D/g, "") || "0");
  }
  expect(sum).toBe(serverCount);
});
