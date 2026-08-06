// Sprint 152 — types for the employee-hours module
// (`/api/timesheets/`). In lockstep with
// `backend/timesheets/serializers.py`.
//
// Decimals arrive as STRINGS (DRF renders them that way) and stay
// strings here. They are not parsed into numbers: `hours` and
// `multiplier` are exact 2-decimal quantities, and a round-trip through
// a JS float is a silent precision loss on exactly the values that must
// not lose precision. Formatting for display is a string operation.

/** One hour kind and its weighting factor, owned by one provider company. */
export interface HourType {
  id: number;
  company: number;
  company_name: string;
  name: string;
  /** "1.50". 0.00 is legal (unpaid leave). A WEIGHT, never a wage. */
  multiplier: string;
  is_active: boolean;
  sort_order: number;
  /**
   * How many TimeEntry rows reference this type. Drives the delete
   * affordance: `TimeEntry.hour_type` is PROTECT, so anything above 0
   * can only be archived, never deleted.
   */
  entry_count: number;
  created_at: string;
  updated_at: string;
}

export interface HourTypeWritePayload {
  company?: number;
  name: string;
  multiplier?: string;
  is_active?: boolean;
  sort_order?: number;
}

/** Response of POST /api/timesheets/hour-types/standard-set/. */
export interface StandardSetResult {
  company: number;
  created: string[];
  skipped: string[];
  created_count: number;
  skipped_count: number;
}

/** One amount of work, one employee, one day. */
export interface TimeEntry {
  id: number;
  company: number;
  company_name: string;
  employee: number;
  employee_name: string;
  /** ISO date, "2026-08-03". Past AND future are legal. */
  date: string;
  iso_year: number;
  iso_week: number;
  hour_type: number;
  hour_type_name: string;
  /**
   * The type's CURRENT multiplier. NOT the one that produced
   * `weighted_hours` — that is `multiplier_snapshot`. The two differ on
   * an entry in a closed week after a multiplier edit, which is the
   * system working as designed.
   */
  hour_type_multiplier: string;
  hours: string;
  /** The multiplier as of this entry's last write. The billing-style truth. */
  multiplier_snapshot: string;
  /** `hours * multiplier_snapshot`, precomputed server-side. */
  weighted_hours: string;
  building: number | null;
  building_name: string | null;
  note: string;
  /** True when this entry's week is closed — the UI disables its actions. */
  is_locked: boolean;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface TimeEntryWritePayload {
  company?: number;
  /** Omitted means "me". A non-manager naming anyone else gets a 403. */
  employee?: number;
  date: string;
  hour_type: number;
  hours: string;
  building?: number | null;
  note?: string;
}

export interface TimeEntryFilters {
  company?: number | "";
  employee?: number | "";
  hour_type?: number | "";
  building?: number | "";
  date_from?: string;
  date_to?: string;
  iso_year?: number;
  iso_week?: number;
  page?: number;
  page_size?: number;
}

/**
 * Sprint 152.1 — one row of `GET /api/timesheets/employees/`.
 *
 * Distinct from `ProviderEmployee` (`/api/employees/`) on purpose: this
 * one is resolved per COMPANY through the same helper the write path
 * validates against, so every row it returns is an employee the entry
 * form can actually file hours for.
 */
export interface TimesheetEmployee {
  id: number;
  full_name: string;
  email: string;
  role: string;
}

/** A closed week. Its EXISTENCE is what "closed" means. */
export interface WeekLock {
  id: number;
  company: number;
  company_name: string;
  iso_year: number;
  iso_week: number;
  closed_at: string;
  closed_by: number;
  closed_by_name: string;
}

/** GET /api/timesheets/weeks/status/ — definite answer for ONE week. */
export interface WeekStatus {
  company: number;
  company_name: string;
  iso_year: number;
  iso_week: number;
  is_closed: boolean;
  lock: WeekLock | null;
}

export interface TimesheetSummaryHourTypeBucket {
  hour_type: number;
  hour_type_name: string;
  current_multiplier: string;
  entries: number;
  hours: string;
  weighted_hours: string;
}

/**
 * Sprint 152.2 — the sentinel the API returns as `building_name` for
 * entries with no building recorded. A marker, not a label: the backend
 * does not pick a display language, so the UI maps this to a translated
 * string. Must stay in lockstep with
 * `backend/timesheets/summary.py::NO_BUILDING_MARKER`.
 */
export const NO_BUILDING_MARKER = "__none__";

export interface TimesheetSummaryEmployeeBucket {
  employee: number;
  employee_name: string;
  entries: number;
  hours: string;
  weighted_hours: string;
}

export interface TimesheetSummaryBuildingBucket {
  /** `null` is the "no building recorded" bucket. */
  building: number | null;
  /** `NO_BUILDING_MARKER` when `building` is null — translate it. */
  building_name: string;
  entries: number;
  hours: string;
  weighted_hours: string;
}

export interface TimesheetSummaryWeekBucket {
  iso_year: number;
  iso_week: number;
  week_start: string;
  week_end: string;
  is_closed: boolean;
  entries: number;
  hours: string;
  weighted_hours: string;
}

export interface TimesheetSummary {
  company: number;
  company_name: string;
  date_from: string | null;
  date_to: string | null;
  total_entries: number;
  total_hours: string;
  total_weighted_hours: string;
  by_hour_type: TimesheetSummaryHourTypeBucket[];
  // Sprint 152.2 — additive.
  by_employee: TimesheetSummaryEmployeeBucket[];
  by_building: TimesheetSummaryBuildingBucket[];
  by_week: TimesheetSummaryWeekBucket[];
}
