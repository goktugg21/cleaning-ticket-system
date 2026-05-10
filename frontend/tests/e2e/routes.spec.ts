import { expect, request, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 17 — route access matrix.
 * Sprint 18 — Django admin moved to /django-admin/, so the SPA's
 * /admin/* routes are now reachable via direct URL too. The matrix
 * below tests both the direct-URL path (nginx SPA fallback) and the
 * sidebar-nav presence for each role.
 *
 * Mirrors the SPA route guards:
 *
 *   /                  every authenticated user.
 *   /tickets/new       every authenticated user (backend rejects
 *                      out-of-scope creations on submit).
 *   /reports           SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER.
 *   /admin/*           SUPER_ADMIN, COMPANY_ADMIN (AdminRoute).
 *   /admin/audit-logs  SUPER_ADMIN only (SuperAdminRoute).
 *
 * The denied paths land on `/?admin_required=ok` for /admin/* and on
 * `/` for /reports. We do not assert the exact destination — only
 * that the URL no longer contains the disallowed path.
 *
 * A separate test confirms /django-admin/login/ still serves Django's
 * admin login page after the move.
 */

type RoleKey = "super" | "companyAdmin" | "managerAll" | "customerAll";

interface RoleExpectations {
  // SPA routes that nginx serves directly via the SPA fallback.
  spaAllow: string[];
  spaDeny: string[];
  // Sidebar link hrefs we expect to render (or NOT render) under
  // `.sidebar-nav` for this role.
  navAllow: string[];
  navDeny: string[];
}

const SPA_ADMIN_ROUTES = [
  "/admin/companies",
  "/admin/buildings",
  "/admin/customers",
  "/admin/users",
  "/admin/invitations",
];

const EXPECTATIONS: Record<RoleKey, RoleExpectations> = {
  super: {
    // Sprint 18: every /admin/* route is now SPA-direct-URL reachable.
    // Audit log is super-admin-only (SuperAdminRoute).
    spaAllow: ["/", "/tickets/new", "/reports", ...SPA_ADMIN_ROUTES, "/admin/audit-logs"],
    spaDeny: [],
    navAllow: [
      "/",
      "/tickets/new",
      "/reports",
      ...SPA_ADMIN_ROUTES,
      "/admin/audit-logs",
    ],
    navDeny: [],
  },
  companyAdmin: {
    spaAllow: ["/", "/tickets/new", "/reports", ...SPA_ADMIN_ROUTES],
    // Audit log is super-admin-only — direct URL must redirect away.
    spaDeny: ["/admin/audit-logs"],
    navAllow: ["/", "/tickets/new", "/reports", ...SPA_ADMIN_ROUTES],
    navDeny: ["/admin/audit-logs"],
  },
  managerAll: {
    spaAllow: ["/", "/tickets/new", "/reports"],
    spaDeny: [...SPA_ADMIN_ROUTES, "/admin/audit-logs"],
    navAllow: ["/", "/tickets/new", "/reports"],
    navDeny: [...SPA_ADMIN_ROUTES, "/admin/audit-logs"],
  },
  customerAll: {
    spaAllow: ["/", "/tickets/new"],
    spaDeny: ["/reports", ...SPA_ADMIN_ROUTES, "/admin/audit-logs"],
    navAllow: ["/", "/tickets/new"],
    navDeny: ["/reports", ...SPA_ADMIN_ROUTES, "/admin/audit-logs"],
  },
};

const ROLE_KEYS: RoleKey[] = [
  "super",
  "companyAdmin",
  "managerAll",
  "customerAll",
];

for (const roleKey of ROLE_KEYS) {
  test.describe(`route matrix — ${roleKey}`, () => {
    test.beforeEach(async ({ page }) => {
      await loginAs(page, DEMO_USERS[roleKey]);
    });

    const exp = EXPECTATIONS[roleKey];

    for (const route of exp.spaAllow) {
      test(`${roleKey} → ${route} (SPA allowed)`, async ({ page }) => {
        await page.goto(route);
        await page.waitForLoadState("networkidle");
        const url = new URL(page.url());
        expect(url.pathname).toBe(route);
      });
    }

    for (const route of exp.spaDeny) {
      test(`${roleKey} → ${route} (SPA denied)`, async ({ page }) => {
        await page.goto(route);
        await page.waitForLoadState("networkidle");
        const url = new URL(page.url());
        expect(url.pathname).not.toBe(route);
      });
    }

    for (const href of exp.navAllow) {
      test(`${roleKey} sidebar shows ${href}`, async ({ page }) => {
        await expect(
          page.locator(`.sidebar-nav a[href="${href}"]`),
        ).toBeVisible({ timeout: 10_000 });
      });
    }

    for (const href of exp.navDeny) {
      test(`${roleKey} sidebar hides ${href}`, async ({ page }) => {
        await expect(
          page.locator(`.sidebar-nav a[href="${href}"]`),
        ).toHaveCount(0);
      });
    }
  });
}

// ---------------------------------------------------------------------------
// Sprint 18 — Django admin still reachable at /django-admin/login/.
//
// nginx now proxies /django-admin/ to the backend; the SPA owns
// /admin/*. The check uses raw HTTP (no browser session) so the test
// doesn't need a Django superuser to be authenticated.
// ---------------------------------------------------------------------------

test("/django-admin/login/ still serves Django's admin login page", async ({
  baseURL,
}) => {
  const ctx = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
  });
  const response = await ctx.get("/django-admin/login/");
  expect(response.status()).toBe(200);
  const body = await response.text();
  // Django ships an unmistakable signature on its admin login template;
  // checking for "Django administration" is more robust than asserting
  // the form field IDs which can shift with version bumps.
  expect(body).toMatch(/Django administration|django/i);
  await ctx.dispose();
});
