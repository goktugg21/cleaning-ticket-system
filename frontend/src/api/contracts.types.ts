// Sprint 160 — types for the contracts module (`backend/contracts/`).
//
// Its own file rather than an extension of `types.ts`, mirroring the
// `timesheets.types.ts` precedent: the module is independent on the
// backend and the frontend mirrors that, so nothing here reaches into
// the ticket / extra-work clients and nothing there needs to reach in.
//
// Kept in lockstep with `backend/contracts/serializers.py` — every
// field below exists on the serializer, and the two enums below repeat
// `contracts/models.py`'s TextChoices values exactly.

/** The status an operator SEES. Derived server-side from the stored
 *  lifecycle plus `end_date` — EXPIRED is never stored, so this union
 *  is wider than what a write may set (see `ContractLifecycle`). */
export type ContractStatus = "DRAFT" | "ACTIVE" | "EXPIRED" | "CANCELLED";

/** What a write may SET. Deliberately narrower than `ContractStatus`:
 *  EXPIRED is a consequence of the dates, not a choice. */
export type ContractLifecycle = "DRAFT" | "ACTIVE" | "CANCELLED";

export type BillingPeriod = "MONTHLY" | "QUARTERLY" | "YEARLY";
export type BillingType = "ADVANCE" | "ARREARS";

export interface ContractType {
  id: number;
  company: number;
  name: string;
  is_active: boolean;
  sort_order: number;
  contract_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContractBuildingRef {
  id: number;
  name: string;
}

/** One project on a revision. `amount` and `hours` are per BILLING
 *  PERIOD of the parent contract, not per month — the contract's
 *  `billing_period` is what makes them comparable. */
export interface ContractLine {
  id: number;
  name: string;
  building: number | null;
  building_name: string | null;
  sort_order: number;
  hours: string;
  area_m2: string | null;
  amount: string;
  vat_pct: string;
}

export interface ContractRevisionSummary {
  id: number;
  label: string;
  effective_from: string;
  amount: string;
  hours: string;
  line_count: number;
}

export interface ContractRevision {
  id: number;
  contract: number;
  label: string;
  effective_from: string;
  notes: string;
  created_by: number | null;
  created_by_name: string | null;
  created_at: string;
  amount: string;
  hours: string;
  line_count: number;
  /** Derived: true once `effective_from` has arrived. A locked
   *  revision is corrected by authoring a NEW one, never by editing. */
  is_locked: boolean;
  /** Derived: the one revision currently shown as in force. */
  is_active: boolean;
  lines: ContractLine[];
}

export interface Contract {
  id: number;
  company: number;
  company_name: string | null;
  customer: number;
  customer_name: string | null;
  contract_type: number | null;
  contract_type_name: string | null;
  /** Sprint 169 §4 — pairs with the name; render through
   *  `lib/contractTypeLabel.ts`, never on its own. */
  contract_type_standard_slot: string;
  contract_no: string;
  start_date: string;
  end_date: string | null;
  lifecycle: ContractLifecycle;
  status: ContractStatus;
  description: string;
  notes: string;
  billing_period: BillingPeriod;
  billing_day: number;
  billing_type: BillingType;
  payment_terms_days: number;
  start_proration: boolean;
  buildings: ContractBuildingRef[];
  active_revision: ContractRevisionSummary | null;
  /** All four are DERIVED from the active revision's lines server-side
   *  and stored nowhere — never cache them into a second copy here. */
  monthly_amount: string;
  yearly_amount: string;
  total_hours: string;
  line_count: number;
  projects: ContractLine[];
  created_at: string;
  updated_at: string;
}

export interface ContractWritePayload {
  company?: number;
  customer: number;
  contract_type?: number | null;
  start_date: string;
  end_date?: string | null;
  lifecycle?: ContractLifecycle;
  description?: string;
  notes?: string;
  billing_period?: BillingPeriod;
  billing_day?: number;
  billing_type?: BillingType;
  payment_terms_days?: number;
  start_proration?: boolean;
  building_ids?: number[];
  /** Label for the first revision, created with the contract. Sent as
   *  the viewer's own translation so an operator sees it in their
   *  language; the backend falls back to the Dutch default. */
  initial_revision_label?: string;
}

export interface ContractLineWritePayload {
  name: string;
  building?: number | null;
  sort_order?: number;
  hours?: string;
  area_m2?: string | null;
  amount?: string;
  vat_pct?: string;
}

export interface ContractRevisionWritePayload {
  label: string;
  effective_from: string;
  notes?: string;
  /** Default true: a new revision starts as a copy of the current one,
   *  so raising one price is an edit of a copy rather than retyping
   *  every project. */
  copy_lines?: boolean;
}

export interface ContractStats {
  total: number;
  active: number;
  draft: number;
  expired: number;
  cancelled: number;
  monthly_total: string;
  yearly_total: string;
}

export interface ContractOptions {
  company: { id: number; name: string };
  customers: { id: number; name: string }[];
  buildings: { id: number; name: string }[];
  contract_types: { id: number; name: string; standard_slot?: string }[];
}

export interface ContractFilters {
  company?: number | "";
  search?: string;
  customer?: number | "";
  building?: number | "";
  status?: ContractStatus | "";
  type?: number | "";
  sort?: string;
  page?: number;
  page_size?: number;
}

/** One PLANNED invoice. Never an `Invoice`: this sprint computes the
 *  forecast and writes nothing (Sprint 158 turns a due row into a real
 *  invoice). */
export interface ForecastRow {
  invoice_date: string;
  due_date: string;
  period_start: string;
  period_end: string;
  amount: string;
  is_prorated: boolean;
  covered_days: number;
  period_days: number;
  status: "PLANNED";
}

export interface ContractForecast {
  year: number;
  /** The invoices STILL TO COME in `year` — the already-raised first
   *  invoice is excluded, which is why `rows_total` is legitimately
   *  smaller than `yearly_amount`. */
  rows: ForecastRow[];
  rows_total: string;
  /** The sum of the ACTUAL period amounts in the year, first invoice
   *  included. NOT `monthly_amount * 12` once proration is involved. */
  yearly_amount: string;
  monthly_amount: string;
  invoices_per_year: number;
  first_invoice_date: string | null;
  excluded_first_invoice: boolean;
}
