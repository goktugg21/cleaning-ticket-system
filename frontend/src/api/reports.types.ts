// Wire-shape types for /api/reports/* responses. Source of truth is the B1
// commit's backend/reports/views.py.

export interface ReportScope {
  company_id: number | null;
  company_name: string | null;
  building_id: number | null;
  building_name: string | null;
}

// Status distribution

export interface StatusBucket {
  status: string;
  label: string;
  count: number;
}

export interface StatusDistributionResponse {
  as_of: string;
  scope: ReportScope;
  buckets: StatusBucket[];
  total: number;
}

// Tickets over time

export type Granularity = "day" | "week" | "month";

export interface SeriesPoint {
  period_start: string; // YYYY-MM-DD
  count: number;
}

export interface TicketsOverTimeResponse {
  from: string;
  to: string;
  granularity: Granularity;
  scope: ReportScope;
  series: SeriesPoint[];
  total: number;
}

// Manager throughput

export interface ManagerRow {
  user_id: number;
  full_name: string;
  email: string;
  resolved_count: number;
}

export interface ManagerThroughputResponse {
  from: string;
  to: string;
  scope: ReportScope;
  managers: ManagerRow[];
}

// Age buckets

export interface AgeBucket {
  key: string;
  label: string;
  min_days: number;
  max_days: number | null;
  count: number;
}

export interface AgeBucketsResponse {
  as_of: string;
  scope: ReportScope;
  buckets: AgeBucket[];
  total_open: number;
}

// SLA distribution

export type SLADisplayState =
  | "ON_TRACK"
  | "AT_RISK"
  | "BREACHED"
  | "PAUSED"
  | "COMPLETED"
  | "HISTORICAL";

export interface SLADistributionBucket {
  state: SLADisplayState;
  label: string;
  count: number;
}

export interface SLADistributionResponse {
  as_of: string;
  scope: ReportScope;
  buckets: SLADistributionBucket[];
  total: number;
}

// SLA breach rate over time

export interface SLABreachRateBucket {
  period_start: string; // YYYY-MM-DD
  total: number;
  breached: number;
  breach_rate: number; // 0..1
}

export interface SLABreachRateOverTimeResponse {
  from: string;
  to: string;
  granularity: Granularity;
  scope: ReportScope;
  buckets: SLABreachRateBucket[];
}

// Sprint 5 — tickets-by-{type, customer, building}
// All three responses share a `scope`-extended summary that carries
// the optional customer / type / status filters alongside the standard
// company / building scope.

export interface DimensionScope extends ReportScope {
  customer_id: number | null;
  customer_name: string | null;
  type: string | null;
  status: string | null;
  // Sprint 14A — the dimension `scope_summary()` also echoes the
  // optional `?origin=` filter alongside customer/type/status. Null
  // when no origin filter is applied. Surfaced here so the shared
  // DimensionScope honestly reflects the backend wire shape used by
  // the tickets-by-origin report (and every other dimension report).
  origin: string | null;
}

export interface TicketsByTypeBucket {
  ticket_type: string;
  ticket_type_label: string;
  count: number;
}

export interface TicketsByTypeResponse {
  from: string;
  to: string;
  scope: DimensionScope;
  buckets: TicketsByTypeBucket[];
  total: number;
  generated_at: string;
}

export interface TicketsByCustomerBucket {
  customer_id: number;
  customer_name: string;
  building_id: number;
  building_name: string;
  company_id: number;
  company_name: string;
  count: number;
}

export interface TicketsByCustomerResponse {
  from: string;
  to: string;
  scope: DimensionScope;
  buckets: TicketsByCustomerBucket[];
  total: number;
  generated_at: string;
}

export interface TicketsByBuildingBucket {
  building_id: number;
  building_name: string;
  company_id: number;
  company_name: string;
  count: number;
}

export interface TicketsByBuildingResponse {
  from: string;
  to: string;
  scope: DimensionScope;
  buckets: TicketsByBuildingBucket[];
  total: number;
  generated_at: string;
}

// Sprint 14A — tickets-by-origin. The backend classifies every in-scope
// ticket into exactly one origin axis (see backend/reports/dimensions.py
// `_origin_case`): NORMAL, EXTRA_WORK (spawned from an EW request line),
// CONVERTED (ticket converted into an EW request), or PLANNED (spawned
// from a planned/recurring occurrence). Buckets are emitted in the
// pinned ORIGIN_ORDER and only non-zero origins appear.
export type TicketOrigin = "NORMAL" | "EXTRA_WORK" | "CONVERTED" | "PLANNED";

export interface TicketsByOriginBucket {
  origin: TicketOrigin;
  origin_label: string;
  count: number;
}

export interface TicketsByOriginResponse {
  from: string;
  to: string;
  scope: DimensionScope;
  buckets: TicketsByOriginBucket[];
  total: number;
  generated_at: string;
}

// Sprint 14A (Part B) — Extra Work revenue states. Unlike the dimension
// reports this is NOT a `buckets` list grouped by building/customer/month:
// the backend (backend/reports/dimensions.py `compute_extra_work_revenue`)
// classifies every in-scope ExtraWorkRequest into exactly ONE mutually
// exclusive revenue STATE and sums its billable amounts:
//   earned          -> the spawned operational ticket is CLOSED.
//   in_progress     -> spawned ticket exists but is not yet terminal (or no
//                      ticket yet and the EW is approved / in progress /
//                      completed).
//   quoted_pipeline -> no ticket yet; EW still requested / under review /
//                      pricing proposed.
//   lost            -> spawned ticket rejected / converted, or the EW was
//                      customer-rejected / cancelled.
// EARNED + IN_PROGRESS prefer the FINAL (post-approval) amounts and fall
// back to the estimate; PIPELINE + LOST use the estimate. The date window
// is anchored on `requested_at`. Provider-management only — STAFF and
// CUSTOMER_USER get 403 (the report exposes commercial amounts).
//
// Money is serialized as 2-decimal STRINGS (Django Decimal), e.g. "242.00",
// NOT numbers — keep them as strings and run them through `formatMoney`
// (lib/intl) for display so locale + currency rendering stays consistent.
export type ExtraWorkRevenueState =
  | "earned"
  | "in_progress"
  | "quoted_pipeline"
  | "lost";

export interface ExtraWorkRevenueBucket {
  count: number;
  subtotal: string; // 2dp decimal string (excl. VAT)
  vat: string; // 2dp decimal string
  total: string; // 2dp decimal string (incl. VAT)
}

export interface ExtraWorkRevenueResponse {
  from: string;
  to: string;
  // Plain company/building scope (the view uses `scope.to_dict()`, not the
  // dimension reports' extended `scope_summary()`), so no customer / type /
  // status / origin echo here.
  scope: ReportScope;
  states: Record<ExtraWorkRevenueState, ExtraWorkRevenueBucket>;
  totals: ExtraWorkRevenueBucket;
  generated_at: string;
}
