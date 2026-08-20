/**
 * W3-H — the hours booked to one extra work, and what they cost.
 *
 * `GET /api/reports/extra-work/<id>/hours/`, served by
 * `backend/reports/views_extra_work_hours.py`.
 *
 * ## Why the endpoint is under `reports/` and not `timesheets/`
 *
 * Two rules, both written down on the server side. `timesheets` records
 * hours and weighted hours and never computes money, and it imports
 * nothing from `extra_work` — so neither the cost nor the "may this
 * caller read this job" question can be answered there. `reports/` is
 * the app that reads across. The panel says the same thing to the
 * operator in one line of helper text, so nobody hunts the hours screen
 * for a wage field that will never be on it.
 *
 * ## Its own module
 *
 * A NEW file rather than a function added to `api/reports.ts`: this is
 * the only caller, and the shapes below (a grid keyed by date, a cost
 * block that is legitimately null) belong with it.
 *
 * ## Nulls here mean "not knowable", never zero
 *
 * `budget_hours` null = nobody budgeted the job. `cost` null = the
 * caller may not see labour cost. `hours_cost` / `total_cost` null = no
 * hourly rate is configured. Every one of those renders as an em dash
 * with a reason, never as 0,00 — a cost of zero would claim the work
 * was free.
 */
import { api } from "./client";

/** One row of the grid: one person, one hour type, across days. */
export interface ExtraWorkHoursRow {
  employee_id: number;
  employee_name: string;
  hour_type_id: number;
  hour_type_name: string;
  /** ISO date -> hours, 2dp strings. Only the days the server drew. */
  days: Record<string, string>;
  /** The row's WHOLE total, including days outside the drawn window. */
  hours: string;
  weighted_hours: string;
}

/**
 * The cost block. Absent (null) for an actor who may not see labour
 * cost; present with null figures when no rate is configured.
 */
export interface ExtraWorkLabourCost {
  hourly_rate: string | null;
  rate_source: string | null;
  rate_configured: boolean;
  hours_cost: string | null;
  travel_costs: string;
  total_cost: string | null;
}

export interface ExtraWorkHoursReport {
  extra_work_id: number;
  /** "company" = every row of the job; "self" = only the caller's own. */
  visibility: "company" | "self";
  /** The day columns actually drawn, ascending. */
  days: string[];
  /** Earlier days the window left out. Totals still cover them. */
  days_omitted: number;
  rows: ExtraWorkHoursRow[];
  totals: { hours: string; weighted_hours: string };
  rollup: {
    /** W2-D's planning number. Read here, never multiplied by anything. */
    budget_hours: string | null;
    entered_hours: string;
    weighted_hours: string;
    /** entered - budget. Positive is over. Hours, never money. */
    variance_hours: string | null;
  };
  cost: ExtraWorkLabourCost | null;
}

export async function fetchExtraWorkHours(
  extraWorkId: number,
): Promise<ExtraWorkHoursReport> {
  const { data } = await api.get<ExtraWorkHoursReport>(
    `/reports/extra-work/${extraWorkId}/hours/`,
  );
  return data;
}
