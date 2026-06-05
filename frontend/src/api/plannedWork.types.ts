// Sprint 11/12 frontend — planned / recurring work API types.
//
// Mirrors the backend planned-work serializers 1:1 (read shapes from
// `RecurringJobReadSerializer` / `PlannedOccurrenceSerializer`, write
// shape from `RecurringJobWriteSerializer`). The surface is mounted at
// `/api/planned-work/` and is PROVIDER-ONLY — STAFF / CUSTOMER_USER get
// 403 on every route, including reads. Source of truth:
//   backend/planned_work/serializers.py
//   backend/planned_work/models.py
//
// Money note: `fixed_price` is the VAT-EXCLUSIVE amount; the backend
// computes the occurrence VAT/total breakdown on top. Decimal fields
// arrive from Django as decimal STRINGS (e.g. "150.00"), not numbers.

export type RecurringJobFrequency = "WEEKLY" | "BIWEEKLY" | "MONTHLY";

// Full model pricing enum. HOURLY is reserved enum space only — the
// backend rejects writes with `pricing_mode_not_supported`, so the
// form must not offer it (see `SELECTABLE_PRICING_MODES`). It can still
// appear on a read payload, so the read type keeps it.
export type PlannedWorkPricingMode = "CONTRACT_INCLUDED" | "FIXED" | "HOURLY";

// The two modes the write/override serializers accept.
export type SelectablePricingMode = "CONTRACT_INCLUDED" | "FIXED";

export type PlannedOccurrenceStatus =
  | "PLANNED"
  | "TICKET_CREATED"
  | "COMPLETED"
  | "MISSED"
  | "RESCHEDULED"
  | "SKIPPED"
  | "CANCELLED";

// ISO weekday numbers (Monday=1 .. Sunday=7). A WEEKLY / BIWEEKLY job
// runs on this SET of weekdays; MONTHLY ignores it.
export type IsoWeekday = 1 | 2 | 3 | 4 | 5 | 6 | 7;

// ---------------------------------------------------------------------------
// RecurringJobWindow — one per-day time window (the AM/PM model). The
// generator materializes one occurrence per (date x active window). A
// window may carry an OPTIONAL per-window pricing override; when its
// `pricing_mode` is null the occurrence falls back to the job's pricing.
// ---------------------------------------------------------------------------
export interface RecurringJobWindow {
  id: number;
  label: string;
  start_time: string | null; // HH:MM:SS
  ordering: number;
  is_active: boolean;
  pricing_mode: PlannedWorkPricingMode | null;
  fixed_price: string | null; // VAT-exclusive decimal string
  vat_pct: string | null;
}

// Window shape sent on create / update. `id` (when present) re-targets an
// existing window in place; omit it to create a new one.
export interface RecurringJobWindowInput {
  id?: number;
  label?: string;
  start_time?: string | null; // HH:MM (or HH:MM:SS)
  ordering?: number;
  pricing_mode?: SelectablePricingMode | null;
  fixed_price?: string | null;
  vat_pct?: string | null;
}

// ---------------------------------------------------------------------------
// RecurringJob — read (GET list/detail, archive/unarchive responses)
// ---------------------------------------------------------------------------
export interface RecurringJob {
  id: number;
  company: number;
  company_name: string;
  building: number;
  building_name: string;
  customer: number;
  customer_name: string;
  title: string;
  description: string;
  frequency: RecurringJobFrequency;
  start_date: string; // YYYY-MM-DD
  end_date: string | null;
  preferred_start_time: string | null; // HH:MM:SS (legacy; superseded by windows)
  time_window_label: string; // legacy; superseded by windows
  // Recurring day-model: the chosen ISO weekday set + the active windows.
  weekdays: number[];
  windows: RecurringJobWindow[];
  pricing_mode: PlannedWorkPricingMode;
  fixed_price: string | null; // VAT-exclusive decimal string
  vat_pct: string;
  is_active: boolean;
  archived_at: string | null;
  created_by: number;
  created_by_email: string;
  created_at: string;
  updated_at: string;
  default_staff_ids: number[];
  default_manager_ids: number[];
  occurrences_count: number;
}

// ---------------------------------------------------------------------------
// RecurringJob — write (POST create / PATCH update)
//
// NOTE: the backend serializes create/update RESPONSES with the WRITE
// serializer, whose `Meta.fields` omits `id` and marks the crew id lists
// write-only. The response is therefore NOT a full `RecurringJob`. The
// API helpers below re-`GET` after PATCH so callers always receive a
// full read object; create navigates to the list (no id to route to).
// ---------------------------------------------------------------------------
export interface RecurringJobWritePayload {
  building: number;
  customer: number;
  title: string;
  description?: string;
  frequency: RecurringJobFrequency;
  start_date: string;
  end_date?: string | null;
  preferred_start_time?: string | null;
  time_window_label?: string;
  // Recurring day-model (both optional; the backend defaults weekdays to
  // start_date's weekday and synthesizes one window when omitted, so a
  // legacy payload keeps working).
  weekdays?: number[];
  windows?: RecurringJobWindowInput[];
  pricing_mode: SelectablePricingMode;
  fixed_price?: string | null;
  vat_pct?: string;
  is_active?: boolean;
  default_staff_ids?: number[];
  default_manager_ids?: number[];
}

// ---------------------------------------------------------------------------
// PlannedOccurrence — read-only
// ---------------------------------------------------------------------------
export interface PlannedOccurrence {
  id: number;
  recurring_job: number;
  recurring_job_title: string;
  company: number;
  building: number;
  customer: number;
  building_name: string;
  customer_name: string;
  planned_date: string; // YYYY-MM-DD (immutable plan-of-record)
  actual_date: string | null;
  status: PlannedOccurrenceStatus;
  // Sprint 6 — true when this occurrence was hand-added on a date OUTSIDE
  // the recurrence rule (the calendar "tick an off-rule date" control).
  is_ad_hoc: boolean;
  ticket_id: number | null;
  // The window this occurrence was materialized from (the AM/PM model).
  source_window: number;
  source_window_label: string;
  source_window_start_time: string | null; // HH:MM:SS
  pricing_mode: PlannedWorkPricingMode;
  fixed_price: string | null; // VAT-exclusive decimal string
  vat_pct: string;
  preferred_start_time: string | null;
  time_window_label: string;
  // Per-occurrence billable breakdown. Null unless FIXED + fixed_price
  // set (CONTRACT_INCLUDED / HOURLY carry no separate billing).
  subtotal_ex_vat: string | null;
  vat_amount: string | null;
  total_inc_vat: string | null;
  completed_at: string | null;
  missed_at: string | null;
  cancelled_at: string | null;
  skipped_at: string | null;
  generated_at: string | null;
  created_at: string;
  updated_at: string;
}

// PATCH …/override/ — any subset of these five snapshotted fields.
export interface PlannedOccurrenceOverridePayload {
  pricing_mode?: SelectablePricingMode;
  fixed_price?: string | null;
  vat_pct?: string;
  preferred_start_time?: string | null;
  time_window_label?: string;
}

// POST …/generate/ result.
export interface GenerateOccurrencesResult {
  occurrences_created: number;
  tickets_created: number;
}

// ---------------------------------------------------------------------------
// Sprint 6 — recurring-job calendar projection (GET …/calendar/) + the
// explicit per-date actions' response. One cell per (date x window): the
// UNION of rule-projected dates (unmaterialized -> PLANNED, occurrence_id
// null) and persisted occurrences (their real state). Mirrors
// `_build_job_calendar` in backend/planned_work/views.py.
// ---------------------------------------------------------------------------
export interface RecurringJobCalendarWindow {
  window_id: number;
  window_label: string;
  status: PlannedOccurrenceStatus;
  is_ad_hoc: boolean;
  occurrence_id: number | null;
  ticket_id: number | null;
}

export interface RecurringJobCalendarDate {
  date: string; // YYYY-MM-DD
  windows: RecurringJobCalendarWindow[];
}

export interface RecurringJobCalendar {
  from: string; // YYYY-MM-DD (effective, after horizon caps)
  to: string; // YYYY-MM-DD
  dates: RecurringJobCalendarDate[];
}

export interface RecurringJobCalendarParams {
  from?: string;
  to?: string;
}

export interface ListRecurringJobsParams {
  page?: number;
  page_size?: number;
}

export interface ListPlannedOccurrencesParams {
  status?: PlannedOccurrenceStatus;
  building?: number;
  customer?: number;
  recurring_job?: number;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}
