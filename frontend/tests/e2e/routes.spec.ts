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
 * FE-6 — the admin area was regrouped:
 *   - Users / Employees / Invitations are tabs of ONE People page at
 *     `/admin/people/:tab`; `/admin/users`, `/admin/employees` and
 *     `/admin/invitations` REDIRECT there. A BUILDING_MANAGER may open
 *     the People page (its Employees tab is a reader surface) but not
 *     the Users / Invitations tabs.
 *   - Services + catalogs are `/admin/services-catalogs/:tab`;
 *     `/admin/services` redirects there.
 *   - The provider nav has ONE create door (`/new`, `sidebar-new`);
 *     `/tickets/new` stays reachable as a deep link. The customer nav
 *     keeps `/tickets/new` (the Melding flow) as its own entry.
 *
 * Mirrors the SPA route guards:
 *
 *   /                  every authenticated user.
 *   /tickets/new       every authenticated user (backend rejects
 *                      out-of-scope creations on submit).
 *   /reports           SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER.
 *   /admin/*           SUPER_ADMIN, COMPANY_ADMIN (AdminRoute), except
 *                      the People page's Employees tab (BM too).
 *   /admin/audit-logs  SUPER_ADMIN only (SuperAdminRoute).
 *
 * The denied paths land on `/?admin_required=ok` for /admin/* and on
 * `/` for /reports. We do not assert the exact destination — only
 * that the URL no longer contains the disallowed path. An allowed
 * path that redirects asserts the path it LANDS on.
 *
 * A separate test confirms /django-admin/login/ still serves Django's
 * admin login page after the move.
 */

type RoleKey = "super" | "companyAdmin" | "managerAll" | "customerAll";

/** A route to open plus the pathname it must settle on. */
interface AllowedRoute {
  path: string;
  lands: string;
}

interface RoleExpectations {
  // SPA routes that nginx serves directly via the SPA fallback.
  spaAllow: AllowedRoute[];
  spaDeny: string[];
  // Sidebar link hrefs we expect to render (or NOT render) under
  // `.sidebar-nav` for this role.
  navAllow: string[];
  navDeny: string[];
}

const direct = (path: string): AllowedRoute => ({ path, lands: path });

/** The admin surfaces, each with the URL the redirect map settles on. */
const SPA_ADMIN_ROUTES: AllowedRoute[] = [
  direct("/admin/companies"),
  direct("/admin/buildings"),
  direct("/admin/customers"),
  { path: "/admin/users", lands: "/admin/people/users" },
  { path: "/admin/invitations", lands: "/admin/people/invitations" },
  { path: "/admin/services", lands: "/admin/services-catalogs/services" },
];
const SPA_ADMIN_PATHS = SPA_ADMIN_ROUTES.map((r) => r.path);
const SPA_ADMIN_LANDINGS = SPA_ADMIN_ROUTES.map((r) => r.lands);

/** The provider-side sidebar hrefs behind the admin gate. */
const NAV_ADMIN_HREFS = [
  "/admin/companies",
  "/admin/buildings",
  "/admin/customers",
  "/admin/people",
  "/admin/services-catalogs",
];

const EXPECTATIONS: Record<RoleKey, RoleExpectations> = {
  super: {
    // Sprint 18: every /admin/* route is now SPA-direct-URL reachable.
    // Audit log is super-admin-only (SuperAdminRoute).
    spaAllow: [
      direct("/"),
      direct("/tickets/new"),
      direct("/reports"),
      ...SPA_ADMIN_ROUTES,
      direct("/admin/audit-logs"),
    ],
    spaDeny: [],
    navAllow: ["/", "/new", "/reports", ...NAV_ADMIN_HREFS, "/admin/audit-logs"],
    navDeny: [],
  },
  companyAdmin: {
    spaAllow: [
      direct("/"),
      direct("/tickets/new"),
      direct("/reports"),
      ...SPA_ADMIN_ROUTES,
    ],
    // Audit log is super-admin-only — direct URL must redirect away.
    spaDeny: ["/admin/audit-logs"],
    navAllow: ["/", "/new", "/reports", ...NAV_ADMIN_HREFS],
    navDeny: ["/admin/audit-logs"],
  },
  managerAll: {
    spaAllow: [
      direct("/"),
      direct("/tickets/new"),
      direct("/reports"),
      // The People page admits a BM on its Employees tab only.
      { path: "/admin/employees", lands: "/admin/people/employees" },
      { path: "/admin/people", lands: "/admin/people/employees" },
    ],
    // A building manager READS the customers list (CustomerReadRoute),
    // so /admin/customers is not a denied address for this role; the
    // paths and their landings overlap, hence the Set.
    spaDeny: [
      ...new Set([...SPA_ADMIN_PATHS, ...SPA_ADMIN_LANDINGS, "/admin/audit-logs"]),
    ].filter((path) => path !== "/admin/customers"),
    navAllow: ["/", "/new", "/reports", "/admin/people"],
    navDeny: [
      "/admin/companies",
      "/admin/buildings",
      "/admin/customers",
      "/admin/services-catalogs",
      "/admin/audit-logs",
    ],
  },
  customerAll: {
    spaAllow: [direct("/"), direct("/tickets/new")],
    spaDeny: [
      "/reports",
      ...SPA_ADMIN_PATHS,
      ...SPA_ADMIN_LANDINGS,
      "/admin/people",
      "/admin/audit-logs",
    ],
    navAllow: ["/", "/tickets/new"],
    navDeny: [
      "/new",
      "/reports",
      ...NAV_ADMIN_HREFS,
      "/admin/audit-logs",
    ],
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
      test(`${roleKey} → ${route.path} (SPA allowed, lands on ${route.lands})`, async ({
        page,
      }) => {
        await page.goto(route.path);
        await page.waitForURL((url) => url.pathname === route.lands, {
          timeout: 10_000,
        });
        await page.waitForLoadState("networkidle");
        const url = new URL(page.url());
        expect(url.pathname).toBe(route.lands);
      });
    }

    for (const route of [...new Set(exp.spaDeny)]) {
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
          page.locator(`.sidebar-nav a[href="${href}"]`).first(),
        ).toBeVisible({ timeout: 10_000 });
      });
    }

    for (const href of exp.navDeny) {
      test(`${roleKey} sidebar hides ${href}`, async ({ page }) => {
        await expect(page.locator(".sidebar-nav")).toBeVisible({
          timeout: 10_000,
        });
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
