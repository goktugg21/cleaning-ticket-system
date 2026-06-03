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
  preferred_start_time: string | null; // HH:MM:SS
  time_window_label: string;
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
  ticket_id: number | null;
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
