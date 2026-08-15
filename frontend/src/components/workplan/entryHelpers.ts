/**
 * Sprint 183 — the two pure helpers the Work Plan's card and its page
 * both need.
 *
 * Their own module because `react-refresh/only-export-components` is
 * right: a file that exports a component AND a function loses fast
 * refresh for the whole file. The repo's ESLint baseline is a fixed
 * number, so "it is only a warning" is not available — and the rule is
 * pointing at a real seam anyway. These are not components.
 */
import type { Role } from "../../api/types";
import type { WorkPlanEntry } from "../../api/workPlan";
import { canAccessExtraWork } from "../../auth/permissions";
import { formatDate } from "../../lib/intl";

/** Where a card's title points, or null when this viewer may not open
 *  it. STAFF are gated out of `/extra-work/:id` by `ExtraWorkRoute` and
 *  by `scope_extra_work_for`, so an extra-work card is a plain title for
 *  them — a link to a page that 403s is worse than no link. */
export function detailPath(entry: WorkPlanEntry, role: Role | null): string | null {
  if (entry.kind === "TICKET_SLOT" && entry.ticket_id !== null) {
    return `/tickets/${entry.ticket_id}`;
  }
  if (entry.kind === "EXTRA_WORK" && canAccessExtraWork(role)) {
    return `/extra-work/${entry.extra_work_id}`;
  }
  return null;
}

/** A "YYYY-MM-DD" in the viewer's locale. The explicit midnight matters:
 *  a bare date string parses as UTC, which anywhere east of Greenwich
 *  prints the previous day. */
export function formatDay(iso: string): string {
  return formatDate(`${iso}T00:00:00`);
}
