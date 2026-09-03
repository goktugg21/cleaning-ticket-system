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

/** P-5 S7 — one customer's share of a building's bills. */
export interface ContractBuildingCostShare {
  customer_id: number;
  customer_name: string;
  share_pct: string;
}

export interface ContractBuildingRef {
  id: number;
  name: string;
  /** P-5 S7 — present on the detail only. */
  cost_shares?: ContractBuildingCostShare[];
}

/** P-5 S7 — one visit of a contract's recurring work (an occurrence). */
export interface ContractVisit {
  id: number;
  planned_date: string;
  status: string;
  recurring_job_id: number;
  recurring_job_title: string;
  ticket_id: number | null;
  ticket_no: string | null;
}

export interface ContractVisits {
  recent: ContractVisit[];
  next: ContractVisit[];
  total: number;
}

/** P-5 S7 — one invoice a contract produced. */
export interface ContractInvoiceTrailRow {
  invoice_id: number;
  number: string | null;
  status: string;
  period_start: string;
  period_end: string;
  invoice_date: string;
  total_amount: string;
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
  /** W16 — the chargeable job this line MIRRORS, on an extra work
   *  register. NULL on every ordinary contract line. Read-only: the
   *  link is made by the server's sync, and the amount comes with it. */
  extra_work: number | null;
  extra_work_no: number | null;
  /** P-12 C3 (§D.24 rule 6) — which recurring work runs this line. */
  recurring?: {
    id: number;
    title: string;
    frequency: string;
    is_active: boolean;
  }[];
}

/** W16 — one building's slice of a customer's extra work register. */
export interface ExtraWorkRegisterBuilding {
  id: number;
  name: string;
  job_count: number;
  total_amount: string;
  lines: ContractLine[];
}

/**
 * W16 — the per-customer register of chargeable work.
 *
 * THREE money figures, not one, and the difference between two of them
 * is the number that matters: `earned_amount - invoiced_amount` is
 * exactly what the Extra Work run still has to bill. A single "total"
 * would be a lie whichever one it was — measured on the demo data the
 * register held EUR 990.99 of finished work while only EUR 660.66 was
 * still billable, the rest already invoiced.
 */
export interface ExtraWorkRegister {
  /** W-FIX1 D2 — null until the first explicit sync has made it. */
  contract: {
    id: number;
    contract_no: string;
    kind: string;
    customer: number;
    customer_name: string;
    revision: number;
  } | null;
  buildings: ExtraWorkRegisterBuilding[];
  summary: {
    job_count: number;
    building_count: number;
    total_amount: string;
    earned_amount: string;
    invoiced_amount: string;
  };
  changed?: { added: number; updated: number; removed: number };
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
  /** P-15 §1.2 — money-bearing: has generated invoices, so the list's
   *  Delete cannot take it (the row says why; the server refuses with
   *  `contract_has_invoices`). */
  has_invoices: boolean;
  description: string;
  notes: string;
  billing_period: BillingPeriod;
  billing_day: number;
  billing_type: BillingType;
  payment_terms_days: number;
  start_proration: boolean;
  buildings: ContractBuildingRef[];
  /** P-5 S7 — connected facts; null on the list. */
  visits?: ContractVisits | null;
  invoice_trail?: ContractInvoiceTrailRow[] | null;
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
  /** P-12 C1 — the road's buckets and the Start-here facts. */
  ending_soon: number;
  draft_without_lines: number;
  monthly_by_status: {
    active: string;
    ending_soon: string;
    draft: string;
    expired: string;
    cancelled: string;
  };
  ending_soon_days: number;
  start_here: {
    draft_no_lines: ContractStartHereRow | null;
    ending_soonest: ContractStartHereRow | null;
  };
}

export interface ContractStartHereRow {
  id: number;
  contract_no: string;
  customer_name: string;
  end_date: string | null;
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
  status?: ContractStatus | "ENDING" | "";
  /** P-12 C1 — "exclude" narrows an ACTIVE read to not-ending-soon,
   *  so the Active and Ending tabs partition. */
  ending?: "exclude";
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

// ---------------------------------------------------------------------
// W23 — the year×week planning grid (GET /contracts/<id>/planning/).
// Mirrors `contracts.serializers.ContractPlanningSerializer` verbatim.
// ---------------------------------------------------------------------
export interface ContractPlanningWeek {
  week: number;
  count: number;
  /** Dominant `PlannedOccurrenceStatus` for the week's cell tint. */
  status: string;
  /** The recurring job to open when the cell is clicked. */
  job_id: number;
}

export interface ContractPlanningLine {
  line_id: number;
  name: string;
  frequency_per_year: number | null;
  planned_count: number;
  job_ids: number[];
  weeks: ContractPlanningWeek[];
}

export interface ContractPlanning {
  year: number;
  lines: ContractPlanningLine[];
}
