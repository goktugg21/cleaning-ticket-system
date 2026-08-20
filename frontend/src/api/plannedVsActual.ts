/**
 * W7 — planned hours beside worked hours, per person, for one job.
 *
 * `GET /api/reports/extra-work/<id>/planned-vs-actual/`, served by
 * `backend/reports/views_planned_vs_actual.py`.
 *
 * ## Not the hours report next door
 *
 * `api/extraWorkHours.ts` reads the job's FULL hours picture — a
 * worker x day x hour-type grid, the budget roll-up, and a labour cost.
 * It is a manager's screen and the server refuses it to STAFF outright,
 * because it carries money.
 *
 * This is the smaller question the owner actually asked — "I planned
 * this person for X hours; how many did they work?" — and it carries no
 * money at all, which is exactly why a worker may read their own line
 * from the ticket they are standing on.
 *
 * ## Null is never zero here
 *
 * `planned_hours` is null for somebody who worked without being planned,
 * and the job's planned total is null when nobody has been planned at
 * all. 0.00 there would claim we planned nobody for no hours, which is a
 * decision; null is the absence of one. Any difference derived from a
 * null plan is null for the same reason.
 *
 * An `actual_hours` of "0.00" IS a real zero: somebody on the plan who
 * has booked nothing yet.
 */
import { api } from "./client";

export interface PlannedVsActualPerson {
  employee_id: number;
  employee_name: string;
  /** null = this person was never planned onto the job. */
  planned_hours: string | null;
  /** "0.00" is real: on the plan, nothing booked yet. */
  actual_hours: string;
  /** worked minus planned. Positive is over. null when unplanned. */
  difference_hours: string | null;
}

export interface PlannedVsActualReport {
  extra_work_id: number;
  /** "company" = the crew. "self" = the caller's own line only. */
  visibility: "company" | "self";
  /** false = nobody the caller may see has been planned. */
  has_plan: boolean;
  people: PlannedVsActualPerson[];
  totals: {
    planned_hours: string | null;
    actual_hours: string;
    difference_hours: string | null;
  };
}

export async function fetchPlannedVsActual(
  extraWorkId: number,
): Promise<PlannedVsActualReport> {
  const { data } = await api.get<PlannedVsActualReport>(
    `/reports/extra-work/${extraWorkId}/planned-vs-actual/`,
  );
  return data;
}
