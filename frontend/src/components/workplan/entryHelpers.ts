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
import type { WorkPlanEntry, WorkPlanPart } from "../../api/workPlan";
import { canAccessExtraWork } from "../../auth/permissions";
import { formatDate, formatDateWeekday } from "../../lib/intl";

/** Where a card's title points, or null when this viewer may not open
 *  it. STAFF are gated out of `/extra-work/:id` by `ExtraWorkRoute` and
 *  by `scope_extra_work_for`, so an extra-work card is a plain title for
 *  them — a link to a page that 403s is worse than no link. */
export function detailPath(entry: WorkPlanEntry, role: Role | null): string | null {
  // W-VIEWER — a JOB card and a SLOT card both open the ticket. They are
  // two kinds because they carry two status vocabularies, not because
  // they point at two different records.
  if (
    (entry.kind === "TICKET" || entry.kind === "TICKET_SLOT") &&
    entry.ticket_id !== null
  ) {
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

/** WP-1 G0 — "ma 24 aug": the placement-marker date. Same explicit
 *  midnight, same reason. */
export function formatPlannedDay(iso: string): string {
  return formatDateWeekday(`${iso}T00:00:00`);
}

/**
 * W24-FX1 §2b — one row per JOB, for the lists that are about jobs.
 *
 * The Work Plan's ticket source is `TicketStaffAssignment`
 * (`backend/tickets/views_work_plan.py::_slot_source`), so it answers
 * one entry PER ASSIGNED PERSON: a ticket with two staff on it arrives
 * as two entries with the same `ticket_id` and the same `ticket_no`,
 * differing only in `key`, `source_id` and `assignee_names`. In the week
 * grid that is correct and deliberate — each person has their own card
 * to complete, and `can_complete` is per slot.
 *
 * In the undated lane it is not. That lane is a list of work with no
 * date, and its one action, "plan for today", writes the TICKET's
 * schedule (`setTicketSchedule(entry.ticket_id, ...)`) — not the slot's.
 * Two rows for one ticket therefore offer the identical action against
 * the identical record, and after it runs both disappear together. The
 * owner saw TCK-2026-000355 twice, on two consecutive rows.
 *
 * Note where the asymmetry comes from: the extra-work source next door
 * already does this, filtering through an `id__in` subquery expressly so
 * that "a person holding both roles on it" yields one row. The ticket
 * source never got the equivalent. Fixing it server-side would change
 * the week grid too, where the duplication is the feature — so the
 * collapse belongs to the lane that wants it, here.
 *
 * Collapses on `ticket_id`, keeping the first entry and merging the
 * assignee names of the ones it absorbs, so the surviving row still says
 * who the work belongs to. Extra-work entries carry `ticket_id: null`
 * and are keyed on their own `key`, so they are never merged with each
 * other or with a ticket.
 */
export function dedupeByJob(entries: WorkPlanEntry[]): WorkPlanEntry[] {
  // W-VIEWER — in the manager's scope the server already answers one row
  // per job (`kind: "TICKET"`), so this is a no-op there. It still earns
  // its place for a caller reading their OWN week, where a person can
  // hold a base slot and one slot per part on the same ticket.
  const byJob = new Map<string, WorkPlanEntry>();
  for (const entry of entries) {
    const jobKey =
      entry.ticket_id !== null ? `ticket-${entry.ticket_id}` : entry.key;
    const seen = byJob.get(jobKey);
    if (seen === undefined) {
      byJob.set(jobKey, entry);
      continue;
    }
    const names = [...seen.assignee_names];
    for (const name of entry.assignee_names) {
      if (!names.includes(name)) names.push(name);
    }
    byJob.set(jobKey, {
      ...seen,
      assignee_names: names,
      assignee_count: names.length,
    });
  }
  return [...byJob.values()];
}

/**
 * W-LATE §3b — the days of the week a part is windowed on.
 *
 * A part with a window renders as its chip inside its day(s) under its
 * ticket. The ticket's own card hangs on ONE day of the week (§12B's
 * `day_for`), so on every OTHER day a part covers, the page renders a
 * HOST card — the ticket's heading and that day's chips, nothing else.
 * This is the pure half: for one entry, `{ dayKey -> parts }` over the
 * seven keys, skipping the entry's own day (its own card already shows
 * every part). A part with no window is on no day but the card's.
 */
export function partHostDays(
  entry: WorkPlanEntry,
  dayKeys: string[],
): Map<string, WorkPlanPart[]> {
  const out = new Map<string, WorkPlanPart[]>();
  for (const part of entry.parts) {
    if (!part.planned_start) continue;
    const start = part.planned_start;
    const end = part.planned_end ?? part.planned_start;
    for (const key of dayKeys) {
      if (key === entry.day) continue;
      if (key >= start && key <= end) {
        const bucket = out.get(key) ?? [];
        bucket.push(part);
        out.set(key, bucket);
      }
    }
  }
  return out;
}

/** P-10 — "TCK-2026-000123 · Title", the one heading a row or a toast
 *  prints for a job; the bare title for an extra work. */
export function entryLabel(entry: WorkPlanEntry): string {
  return entry.ticket_no ? `${entry.ticket_no} · ${entry.title}` : entry.title;
}
