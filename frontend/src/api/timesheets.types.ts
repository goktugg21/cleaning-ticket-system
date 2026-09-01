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
   * Sprint 152.3 — which of the six standard kinds this row is
   * recognised as, or `""` for a custom type. DERIVED server-side from
   * `name`, so it is read-only: the API rejects nothing, it simply
   * ignores a client-supplied value.
   *
   * `name` remains the STORED, operator-typed value in every payload —
   * the fallback for a custom type and the thing an admin edits. Use
   * `lib/hourTypeLabel` to decide what to display; never render one of
   * the two directly.
   */
  standard_slot: string;
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
export type HourSourceType = "CONTRACT" | "EXTRA_WORK" | "TICKET" | "OTHER";

export interface TimeEntry {
  /** Sprint 173 §1 — which job produced this hour. A type + id pair,
   *  never a foreign key: `timesheets` may not import `tickets` or
   *  `extra_work`, so resolution happens in the reporting layer. */
  source_type: HourSourceType;
  source_id: number | null;
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
  /** Sprint 152.3 — see `HourType.standard_slot`. */
  hour_type_standard_slot: string;
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
  /** Sprint 180 §3 — WHICH JOB, on the WRITE side.
   *
   *  The serializer has accepted these two since Sprint 173 and the
   *  entries table has been sending them since Sprint 178 §4a — by
   *  spreading `decodeSource(...)` into this payload, which TypeScript
   *  permits from a spread and therefore never checked. The wire shape
   *  and the type disagreed, and a new caller had no way to learn from
   *  the type that a source could be written at all.
   *
   *  `string`, not the `HourSourceType` union the READ side uses:
   *  `decodeSource` returns a plain string because it parses a
   *  `<select>` value, and narrowing here would only push a cast into
   *  every caller. The server validates against `HourSource.choices`
   *  and 400s anything else, which is the check that matters. */
  source_type?: string;
  source_id?: number | null;
}

export interface TimeEntryFilters {
  company?: number | "";
  /** Sprint 174 §1 — filter by where the hour came from. */
  source_type?: string;
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
  /** Sprint 152.3 — see `HourType.standard_slot`. */
  standard_slot: string;
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

/**
 * W12 §5 — the WEEKLY PATTERN half of a standing agreement.
 *
 * Deliberately not the whole `ContractHours` row: **My hours** reads it
 * for exactly one purpose — which weekdays this person is scheduled to
 * work — and typing the rest here would invite a second screen to grow
 * out of the same call. The admin tab that edits the full row keeps its
 * own untyped read; this is the worker-side slice.
 */
export interface ContractHoursPattern {
  id: number;
  employee: number;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
}

/** P-9 D3 — one week of a year that holds saved hours
 *  (`GET /api/timesheets/weeks/with-hours/`). `hours` is the summed
 *  decimal as a string, the module's convention for every amount. */
export interface WeekWithHours {
  iso_year: number;
  iso_week: number;
  hours: string;
  entries: number;
}

export interface WeeksWithHours {
  iso_year: number;
  weeks: WeekWithHours[];
}
