import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 16 — login smoke for every demo persona.
 *
 * Confirms `seed_demo_data` produced working credentials for every
 * role and that the login form lands on a non-/login URL after a
 * successful POST.
 */
for (const [key, user] of Object.entries(DEMO_USERS)) {
  test(`login as ${key} (${user.role})`, async ({ page }) => {
    await loginAs(page, user);
    expect(page.url()).not.toContain("/login");
    // The sidebar brand row is on every authenticated page.
    await expect(page.locator(".brand-name")).toBeVisible();
  });
}

test("demo cards render when VITE_DEMO_MODE=true", async ({ page }) => {
  await page.goto("/login");
  // Skipped automatically if the build under test was produced
  // without VITE_DEMO_MODE=true (e.g. a near-production preview).
  const cards = page.locator('[data-testid="demo-cards"]');
  if ((await cards.count()) === 0) {
    test.skip(true, "VITE_DEMO_MODE not enabled for this build");
    return;
  }
  await expect(cards).toBeVisible();
  // Sprint 21: 1 super-admin + 6 Company A cards (admin, two manager
  // flavours, three customer-user flavours) + 3 Company B cards
  // (admin-b, manager-b, customer-b) → 10 cards total.
  await expect(page.locator('[data-testid^="demo-card-"]')).toHaveCount(10);
  // Both company groupings are labelled and addressable.
  await expect(page.locator('[data-testid="demo-company-a-label"]')).toBeVisible();
  await expect(page.locator('[data-testid="demo-company-b-label"]')).toBeVisible();
  await expect(
    page.locator('[data-demo-company="A"]'),
  ).toHaveCount(6);
  await expect(
    page.locator('[data-demo-company="B"]'),
  ).toHaveCount(3);
});

test("demo card click fills the login form", async ({ page }) => {
  await page.goto("/login");
  const card = page.locator('[data-testid="demo-card-customer-b3"]');
  if ((await card.count()) === 0) {
    test.skip(true, "VITE_DEMO_MODE not enabled for this build");
    return;
  }
  await card.click();
  await expect(page.locator("#login-email")).toHaveValue(
    "amanda-customer-b-amsterdam@b-amsterdam.demo",
  );
  await expect(page.locator("#login-password")).toHaveValue("Demo12345!");
});
