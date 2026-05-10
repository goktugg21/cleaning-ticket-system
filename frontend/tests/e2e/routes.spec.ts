import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 17 — route access matrix.
 *
 * The SPA's `/admin/*` routes share a URL prefix with Django's
 * `admin/` (see backend/config/urls.py). The prod nginx config
 * forwards every `/admin/*` request to the backend so Django's admin
 * console works (frontend/nginx.conf::location /admin/), which means
 * a fresh page load at `/admin/companies` does NOT reach the SPA at
 * all — it reaches Django and is redirected to `/admin/login/`. The
 * SPA's `/admin/*` routes are therefore reachable only via in-SPA
 * navigation (React Router push). This is documented as a NEEDS
 * FOLLOW-UP in `docs/audit/sprint-17-full-business-logic-audit.md`.
 *
 * Until that quirk is resolved (the planned fix is to move Django's
 * admin to `/django-admin/`), we exercise the access matrix by
 * asserting on the AppShell sidebar:
 *
 *   - /admin/* nav links render only when the user role is in
 *     `STAFF_ROLES` (SUPER_ADMIN, COMPANY_ADMIN). This mirrors the
 *     `AdminRoute` guard.
 *   - /reports nav link renders only when the user role is in
 *     `REPORTS_ROLES` (SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER).
 *
 * For the SPA-only routes (/, /tickets/new, /reports) we also do a
 * direct-URL navigation check, because those paths are served by
 * nginx's SPA fallback (`try_files $uri $uri/ /index.html`).
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

const EXPECTATIONS: Record<RoleKey, RoleExpectations> = {
  super: {
    spaAllow: ["/", "/tickets/new", "/reports"],
    spaDeny: [],
    navAllow: [
      "/",
      "/tickets/new",
      "/reports",
      "/admin/companies",
      "/admin/buildings",
      "/admin/customers",
      "/admin/users",
      "/admin/invitations",
    ],
    navDeny: [],
  },
  companyAdmin: {
    spaAllow: ["/", "/tickets/new", "/reports"],
    spaDeny: [],
    navAllow: [
      "/",
      "/tickets/new",
      "/reports",
      "/admin/companies",
      "/admin/buildings",
      "/admin/customers",
      "/admin/users",
      "/admin/invitations",
    ],
    navDeny: [],
  },
  managerAll: {
    spaAllow: ["/", "/tickets/new", "/reports"],
    spaDeny: [],
    navAllow: ["/", "/tickets/new", "/reports"],
    navDeny: [
      "/admin/companies",
      "/admin/buildings",
      "/admin/customers",
      "/admin/users",
      "/admin/invitations",
    ],
  },
  customerAll: {
    spaAllow: ["/", "/tickets/new"],
    spaDeny: ["/reports"],
    navAllow: ["/", "/tickets/new"],
    navDeny: [
      "/reports",
      "/admin/companies",
      "/admin/buildings",
      "/admin/customers",
      "/admin/users",
      "/admin/invitations",
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
