/**
 * P-14 A1 — THE ONE TAB TABLE of the Hours page.
 *
 * P-13 W6 took the "Weekly schedule" view off the Hours page, calling
 * it planning. It is not: it is each person's standing weekly pattern
 * per building (`timesheets.ContractHours`), the thing that seeds the
 * standard lines in Enter hours — a Hours concept, and the owner wants
 * it where it was. It comes back as the People-style second tab,
 * URL-backed: **Hours worked** (`/admin/hours`) | **Agreed hours**
 * (`/admin/hours/agreed`).
 *
 * Pure data and pure functions only (no React, no i18n — labels are
 * keys, resolved by the page), so vitest pins the table in the node
 * harness. The page iterates the exported constant and keeps no second
 * copy (CLAUDE.md's exhaustiveness rule).
 */

export type HoursTab = "worked" | "agreed";

/** Render order of the tab strip; every consumer iterates THIS. */
export const HOURS_TABS: ReadonlyArray<{
  key: HoursTab;
  labelKey: string;
  path: string;
}> = [
  { key: "worked", labelKey: "hours_admin.tab_worked", path: "/admin/hours" },
  { key: "agreed", labelKey: "contract_hours.tab", path: "/admin/hours/agreed" },
];

/**
 * Which tab a location means.
 *
 * `?tab=schedule` is the STANDING deep link P-13 W6 left behind (the
 * hours-comparison report's "Weekly schedule" door and the agenda
 * header pointed at it); it lands on the Agreed tab so no saved link
 * goes dead. The page redirects it onto the real path.
 */
export function hoursTabOf(
  pathname: string,
  legacyTabParam: string | null | undefined,
): HoursTab {
  if (pathname.replace(/\/+$/, "").endsWith("/admin/hours/agreed")) {
    return "agreed";
  }
  if (legacyTabParam === "schedule") return "agreed";
  return "worked";
}
