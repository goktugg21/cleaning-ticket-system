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
