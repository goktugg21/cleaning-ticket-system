// Sprint 5 — the sub-task / staff-slot admin shapes are co-located in
// `./admin` (alongside SlotStatus + TicketStaffAssignmentAdmin + their client
// fns). `TicketDetail` carries the nested read-only `sub_tasks`, so it
// re-uses that type. Type-only import — erased at build, no runtime cycle.
import type { SubTask } from "./admin";
// Sprint 184 §5 — the billing pair is declared beside the calls that
// write it (`api/invoices.ts`); a type-only import keeps ONE definition
// rather than a second copy of the same two unions here.
import type { InvoiceBillingTarget, InvoiceSplit } from "./invoices";

export type Role =
  | "SUPER_ADMIN"
  | "COMPANY_ADMIN"
  | "BUILDING_MANAGER"
  // Sprint 23A — service-provider-side field staff. Added here so
  // the frontend Role union stays in sync with backend UserRole.
  | "STAFF"
  | "CUSTOMER_USER";

// Employees directory — STAFF employment classification. Mirrors the
// backend `StaffProfile.EmploymentType` enum. Only STAFF rows carry a
// value; provider admins (SUPER_ADMIN / COMPANY_ADMIN) and building
// managers report `null` on the directory endpoint.
export type EmploymentType = "INTERNAL_STAFF" | "ZZP" | "INHUUR";

// Sprint 28 Batch 11 — new ticket status for the staff-completion
// default route: STAFF marks done -> here -> BM accepts (forward to
// WAITING_CUSTOMER_APPROVAL) or rejects (back to IN_PROGRESS). The
// optional per-building "routes_to_customer" flag bypasses this
// status entirely (STAFF completion goes straight to
// WAITING_CUSTOMER_APPROVAL). Placed chronologically between
// IN_PROGRESS and WAITING_CUSTOMER_APPROVAL.
export type TicketStatus =
  | "OPEN"
  // W10 §1 — seen and scheduled, work not begun. Between OPEN and
  // IN_PROGRESS so an operator opening a September job in August has a
  // true answer instead of choosing between "ignored" and "started".
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  // W10 §2 — stalled on something outside our control. Not cancelled,
  // not in progress, and not terminal: it has a way back to IN_PROGRESS
  // and it stays on the ticket list.
  | "ON_HOLD"
  | "WAITING_MANAGER_REVIEW"
  | "WAITING_CUSTOMER_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "CLOSED"
  | "REOPENED_BY_ADMIN"
  // Sprint 7B — terminal status for a ticket that has been converted
  // into an Extra Work request. Emitted by the backend ticket state
  // machine (tickets/models.py); surfaced as a transition target.
  | "CONVERTED_TO_EXTRA_WORK";

// B7 four-tier note taxonomy. Source of truth:
// backend/tickets/models.py::TicketMessageType.
//
//   PUBLIC_REPLY       — customer-visible reply.
//   INTERNAL_NOTE      — provider-internal (PROVIDER_INTERNAL in §9 of
//                        the canonical doc). Provider management only;
//                        STAFF and customer-side never see it.
//   STAFF_OPERATIONAL  — provider-side + STAFF; NOT customer-side.
//   STAFF_COMPLETION   — provider-side + STAFF; ALSO customer-visible as
//                        completion evidence.
//   CUSTOMER_INTERNAL  — M1 B5, customer-side's own internal note. Visible
//                        to customer-side + SA (forensic) only; NOT MGMT,
//                        NOT STAFF. PUBLIC_REPLY is now provider+customer
//                        only (STAFF dropped).
//
// Backend filters at the queryset level — the SPA renders whatever the
// API returns. The frontend's job is to render the correct badge / bubble
// class per tier and to gate the composer to tiers the viewer may write.
// Tier-create predicates live in frontend/src/auth/permissions.ts.
export type TicketMessageType =
  | "PUBLIC_REPLY"
  | "INTERNAL_NOTE"
  | "STAFF_OPERATIONAL"
  | "STAFF_COMPLETION"
  | "CUSTOMER_INTERNAL";

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Me {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  language: string;
  is_active: boolean;
  company_ids: number[];
  building_ids: number[];
  customer_ids: number[];
  // RF-1 — authed avatar URL (null when unset).
  profile_photo_url: string | null;
  // Sprint 126 — customer-side Documents access (any of the user's
  // customers). Drives the customer sidebar entry; always false for
  // provider roles. See MeSerializer.get_can_manage_documents.
  can_manage_documents: boolean;
  date_joined: string;
  last_login: string | null;
}

export interface Company {
  id: number;
  name: string;
  slug: string;
  default_language: string;
  is_active: boolean;
}

export interface Building {
  id: number;
  company: number;
  name: string;
  address: string;
  city: string;
  country: string;
  postal_code: string;
  is_active: boolean;
}

// Mirrors backend `customers/serializers.py::compute_customer_actions`.
// Used by both `CustomerSerializer.actions` (detail responses) and
// every row of `CustomerUserMembershipSerializer.actions` (per-customer
// user-membership listings). The frontend renders writable role
// dropdowns directly from `allowed_target_customer_access_roles` and
// gates management surfaces on the two booleans.
export interface CustomerActions {
  can_manage_customer_users: boolean;
  can_manage_customer_company_admins: boolean;
  allowed_target_customer_access_roles: CustomerAccessRole[];
}

/** Sprint 185 §3 — proposed, and awaiting the owner's veto. Mirrors
 *  `customers.models.CustomerLifecycle`. Nothing branches on the value;
 *  it is what the screens say, not what anyone may do. */
/** Sprint 185 §3 — the ONE ordered lifecycle list. Both the list page's
 *  filter and the form's picker iterate this; a second local copy is how
 *  a newly added state renders on one screen and silently not the other
 *  (CLAUDE.md — Sprint 126/130). Adding a state here and to the union
 *  below is the whole change. */
export const CUSTOMER_LIFECYCLE_VALUES = [
  "PROSPECT",
  "ONBOARDING",
  "ACTIVE",
  "NOTICE",
  "CHURNED",
] as const;

export type CustomerLifecycle =
  | "PROSPECT"
  | "ONBOARDING"
  | "ACTIVE"
  | "NOTICE"
  | "CHURNED";

export interface Customer {
  id: number;
  company: number;
  // Sprint 14: legacy single-building anchor, now nullable. New
  // consolidated customers (B Amsterdam-style) have building=null and
  // are linked to many buildings via the M:N table.
  building: number | null;
  // Sprint 14 hotfix: every linked building, sourced from
  // CustomerBuildingMembership. The list is the FULL set linked to
  // this customer (not filtered to the caller's allowed buildings),
  // so the frontend can match a selected building to a customer
  // without an extra fetch. Backend ticket-create still validates
  // the caller's per-building access on submit.
  linked_building_ids?: number[];
  name: string;
  contact_email: string;
  phone: string;
  language: string;
  // Sprint 185 §1 — the BILLING address. Every invoice carries the
  // CUSTOMER's address, never the building's: a building's address is
  // the work site.
  address: string;
  postal_code: string;
  city: string;
  country: string;
  /** Server-derived: street AND city are filled in. One definition
   *  (`Customer.has_billing_address`) so the screen's warning and the
   *  document cannot disagree about what counts as an address. */
  has_billing_address: boolean;
  is_active: boolean;
  /** Sprint 185 §3 — where the relationship is. DESCRIPTIVE ONLY:
   *  `is_active` above still decides access. */
  lifecycle: CustomerLifecycle;
  /** Sprint 182 §3 — which invoice this customer's work lands on by
   *  default. Read here so the Extra Work create form can say what
   *  "follow the customer" resolves to for THIS customer instead of
   *  naming a setting the reader would have to go and look up.
   *  Optional: a server that predates the split does not send it. */
  invoice_billing_target?: InvoiceBillingTarget;
  // RF-1 — customer company logo URL (null when unset).
  logo_url?: string | null;
  // Per-current-user, per-customer capability block. Optional so
  // older /me / non-customer-scoped responses don't break typing.
  actions?: CustomerActions;
}

export type SLAStatus =
  | "ON_TRACK"
  | "AT_RISK"
  | "BREACHED"
  | "COMPLETED"
  | "HISTORICAL";

export type SLADisplayState = SLAStatus | "PAUSED";

/** W13 — one row of the per-company ticket-category catalog
 *  (`GET /api/tickets/categories/`): the owner's list, Verzoek / Extra /
 *  Compliment / Melden / Storing / Ongegrond / Klacht.
 *
 *  Replaces `WorkCategory`, the Sprint 185 kind-of-work catalog, which
 *  sat beside the `TicketType` enum and gave a melding two overlapping
 *  classifications with near-identical labels. There is one now. */
export interface TicketCategory {
  id: number;
  company: number;
  company_name: string;
  /** Stable machine key. What code matches on, so a company renaming
   *  its label never breaks a mapping. */
  slug: string;
  /** The label in the READER's language, resolved server-side by the
   *  one resolver (`TicketCategory.label_for`). Read-only: write
   *  `label_nl` / `label_en`. */
  label: string;
  label_nl: string;
  label_en: string;
  /** "#rrggbb", or "" for no chip colour. */
  color: string;
  sort_order: number;
  is_active: boolean;
  /** W13 §4 — may this be chosen when a melding is CREATED? False for
   *  "Ongegrond", a verdict somebody reaches afterwards. The create
   *  forms ask the server for `available_at_intake=true` and render
   *  what comes back, so such a category is absent there rather than
   *  present and disabled. */
  available_at_intake: boolean;
  /** The pre-W13 `Ticket.type` this category stands in for. A
   *  compatibility bridge; see the model. */
  legacy_type: string;
  usage_count: number;
  created_at: string;
  updated_at: string;
}


// FE-2 (Addendum D §D.4) — the ONE presentation phase, computed
// server-side per viewer. Never inferred client-side.
export type ExtraWorkDisplayPhase =
  | "WAITING_PRICE"
  | "WAITING_YOUR_APPROVAL"
  | "WAITING_CUSTOMER_APPROVAL"
  | "SCHEDULED"
  | "IN_EXECUTION"
  | "WAITING_COMPLETION_APPROVAL"
  | "DONE"
  | "INVOICED"
  | "REJECTED"
  | "CANCELLED";

export type TicketDisplayPhase =
  | "RECEIVED"
  | "PLANNED"
  | "IN_EXECUTION"
  | "WAITING_YOUR_APPROVAL"
  | "WAITING_CUSTOMER_APPROVAL"
  | "DONE"
  | "REJECTED"
  | "CONVERTED";

export interface TicketList {
  // W-H §1 — the archive, on the LIST as well as the detail, so the
  // archive view can name who filed each row without a per-row fetch.
  // `archived_at` IS the state: set means the ticket has left the
  // working list. Nothing reads the other two to decide anything.
  archived_at?: string | null;
  archived_by_name?: string | null;
  archive_note?: string;
  id: number;
  ticket_no: string;
  title: string;
  type: string;
  /** W13 — WHAT KIND OF MELDING, from the company's catalog. The one
   *  classification any screen offers; `type` above is the superseded
   *  enum, still on the row and still written by the API, offered by
   *  nothing.
   *
   *  Null until somebody classifies it — a real and common state, and
   *  where the two legacy types with no home in the owner's list
   *  (SUGGESTION, OTHER) landed at migration.
   *
   *  `category_name` is already in the reader's language; the resolver
   *  is server-side so two screens cannot name one row two ways. */
  category: number | null;
  category_name: string | null;
  category_slug: string | null;
  /** "#rrggbb" or null. The chip colour, which is what turns a column
   *  of grey words into groups you can see. */
  category_color: string | null;
  priority: string;
  status: TicketStatus;
  display_phase: TicketDisplayPhase;
  company: number;
  // Sprint 30 Batch 30.1.2 — provider company display name. The
  // backend exposes this on BOTH list + detail serializers via
  // `source="company.name"`. Nullable on the wire to guard against
  // legacy tickets whose company row was hard-deleted in a fixture.
  company_name: string | null;
  building: number;
  building_name: string;
  customer: number;
  customer_name: string;
  assigned_to: number | null;
  assigned_to_email: string | null;
  created_at: string;
  updated_at: string;
  sla_is_paused: boolean;
  sla_remaining_business_seconds: number | null;
  sla_display_state: SLADisplayState;
  // Sprint 14A (frontend Part A2) — spawned-from-EW anchor surfaced on
  // the LIST serializer too (previously detail-only). Non-null only for
  // tickets created from an ExtraWorkRequest line; the ticket list
  // renders a small "Extra Work" route badge that deep-links to the
  // parent EW. Mirrors backend `TicketListSerializer.extra_work_origin`.
  extra_work_origin: TicketExtraWorkOrigin | null;
}

export interface TicketStatusHistory {
  id: number;
  old_status: TicketStatus;
  new_status: TicketStatus;
  // Sprint 180 Batch 2 — a system transition (auto-close on customer
  // approval) writes changed_by NULL, and the serializer OMITS
  // changed_by_email entirely rather than emitting null, because DRF
  // turns the null-FK traversal into SkipField.
  changed_by: number | null;
  changed_by_email?: string | null;
  note: string;
  // Sprint 27F-B1 — workflow override columns. Required on the
  // wire because the backend always emits them (`is_override`
  // defaults to `false`, `override_reason` defaults to `""`).
  is_override: boolean;
  override_reason: string;
  created_at: string;
}

// Sprint 27F-F1 — request body for POST /tickets/{id}/status/.
// `is_override` + `override_reason` are optional because non-
// override transitions omit them; the backend still coerces
// SUPER_ADMIN / COMPANY_ADMIN driving WAITING_CUSTOMER_APPROVAL
// → APPROVED|REJECTED to `is_override=true` regardless. The
// reason is still required when override=true and the backend
// rejects an empty/whitespace string with the stable code
// `override_reason_required`.
export interface TicketStatusChangePayload {
  to_status: TicketStatus;
  note?: string;
  is_override?: boolean;
  override_reason?: string;
  // W13-FIX §1 — the transition modal's answers, posted WITH the move so
  // "start the work" stays one action. Mirrors the optional fields on
  // `tickets/serializers.py::TicketStatusChangeSerializer`, which applies
  // them inside the same transaction as the transition.
  assigned_staff_ids?: number[];
  scheduled_start_at?: string;
}

// W13-FIX §1 — what a step needs before it may be taken. Mirrors
// `backend/tickets/transition_requirements.py`. The modal renders one
// field per UNSATISFIED requirement; `apply_transition` refuses the move
// while any is unmet, so the form and the gate read the same source.
export type TransitionRequirementKey =
  | "assignee"
  | "schedule"
  | "completion_evidence"
  // W14 §4 — the justification an OVERRIDE carries, reported by
  // `state_machine.transition_needs_override_reason`. Unlike the other
  // three it can never arrive satisfied: a reason is written FOR the
  // move, so there is nothing on the ticket that could already answer
  // it. Reported by the requirements ENDPOINT and rendered by the
  // modal; the refusal itself keeps its own stable code
  // (`override_reason_required`) one layer down in `apply_transition`.
  | "override_reason";

export interface TransitionRequirement {
  key: TransitionRequirementKey;
  satisfied: boolean;
}

export interface TransitionRequirements {
  from_status: TicketStatus;
  to_status: TicketStatus;
  requirements: TransitionRequirement[];
  unmet: TransitionRequirementKey[];
}

// Sprint 7B (frontend) — request body for
// POST /tickets/{id}/convert-to-extra-work/. Mirrors backend
// `tickets/serializers.py::TicketConvertToExtraWorkSerializer`, which
// reuses `ExtraWorkPreviewLineSerializer` for each cart line
// (service XOR custom_description; quantity > 0; requested_date;
// optional customer_note). The line's `unit_type` is NOT sent — the
// backend denormalises it from the chosen Service (or OTHER for a
// custom line). The convert endpoint is provider-only and the wire
// shape is identical to the create-cart line.
export interface TicketConvertLinePayload {
  // A catalog service id XOR a custom_description (exactly one).
  service?: number | null;
  custom_description?: string;
  // Decimal as string per DRF convention.
  quantity: string;
  requested_date: string;
  customer_note?: string;
}

export interface TicketConvertToExtraWorkPayload {
  request_intent: ExtraWorkRequestIntent;
  line_items: TicketConvertLinePayload[];
  customer_visible_note?: string;
  internal_note?: string;
}

// Response body for POST /tickets/{id}/convert-to-extra-work/. The
// backend supersedes the source ticket to CONVERTED_TO_EXTRA_WORK and
// returns the freshly-created ExtraWorkRequest (the page navigates to
// its detail) plus the source-ticket echo and any operational tickets
// spawned immediately on the INSTANT route.
export interface TicketConvertToExtraWorkResponse {
  extra_work_request: ExtraWorkRequestDetail;
  source_ticket: {
    id: number;
    ticket_no: string | null;
    status: TicketStatus;
  };
  operational_ticket_ids: number[];
}

// Sprint 7 — bulk manager-confirm (POST /tickets/bulk-status/). One
// result row per (deduped) requested ticket id; `ok` is false with a
// stable `error` code (`not_found`, `forbidden_transition`,
// `no_op_transition`, …) for any ticket the actor was out-of-scope for
// or whose state did not permit the transition. Mirrors the per-item
// envelope returned by `TicketViewSet.bulk_status`.
export interface TicketBulkStatusResultItem {
  id: number;
  ok: boolean;
  error?: string;
}

export interface TicketBulkStatusResponse {
  succeeded: number;
  failed: number;
  results: TicketBulkStatusResultItem[];
}

// Sprint 23B — list of staff currently assigned to a ticket via
// TicketStaffAssignment. The backend serializer gates this list
// through Customer.show_assigned_staff_* flags before returning
// it to a CUSTOMER_USER; if every flag is off the payload
// collapses to a single anonymous-label entry the UI translates
// via the `label_key` i18n key.
// M2 P5 — resolver-gated credential / property summaries the backend
// attaches to NAMED assigned-staff entries for CUSTOMER_USER viewers
// ONLY (tickets/serializers.py `_staff_credentials_payload_for_customer`).
// Both arrays are OPTIONAL: provider viewers never receive the keys, so
// the FE must render nothing when they are absent. EU_NATIONAL_ID can
// never appear (resolver + hard exclude on the backend).
export interface AssignedStaffCredential {
  type: "RESIDENCE_PERMIT" | "VCA";
  expiry_date: string | null;
  // RESIDENCE_PERMIT only.
  permit_number?: string;
  // Present iff the document sub-rule passes (e.g. the residence-permit
  // photocopy flag). A reverse() path starting "/api/..." — strip the
  // prefix before calling through the axios client (its baseURL already
  // ends in /api); use downloadDocumentFromUrl in api/staffCredentials.
  document_url?: string;
}

export interface AssignedStaffProperty {
  name: string;
  value: string;
  document_url?: string;
}

export interface AssignedStaffNamedEntry {
  id: number;
  full_name?: string;
  email?: string;
  phone?: string;
  anonymous?: false;
  credentials?: AssignedStaffCredential[];
  properties?: AssignedStaffProperty[];
}

export type AssignedStaffEntry =
  | AssignedStaffNamedEntry
  // W-N1 §4 — the anonymous row is now one PER MEMBER and carries the
  // same resolver-gated credentials the named row does. It still has no
  // name, no email, no phone and no `id`: a certificate says what the
  // work is covered for, not who is doing it.
  | {
      anonymous: true;
      label_key: string;
      credentials?: AssignedStaffCredential[];
    };

// Sprint 28 Batch 15.4 — ticket "spawned from extra work" anchor.
// Mirrors backend `TicketDetailSerializer.extra_work_origin`. Non-
// null only for tickets created from an ExtraWorkRequest. The
// `origin` value mirrors `RoutingDecision`: "INSTANT" tickets came
// from a cart line that resolved to an active CustomerServicePrice
// (no proposal phase), "PROPOSAL" tickets came from an accepted
// proposal line.
export interface TicketExtraWorkOrigin {
  extra_work_request_id: number;
  extra_work_request_title: string;
  extra_work_request_status: ExtraWorkStatus;
  extra_work_request_item_id: number;
  service_name: string | null;
  origin: "INSTANT" | "PROPOSAL";
  /** W6-H — the CALLER'S OWN planned days on the parent Extra Work, and
   *  nobody else's. Optional because the list serializer omits it.
   *
   *  This is the WORKER'S surface. A worker cannot open the parent
   *  Extra Work at all — `scope_extra_work_for` returns none() for
   *  STAFF, the P0 staff-privacy fix, with operational visibility
   *  living on the spawned ticket instead — so "which days am I on"
   *  had to be answered on the ticket they can already open.
   *
   *  `date: null` means "planned, day not decided". Hours only: no
   *  rate, no cost, no other person's name. */
  my_planned_hours?: { date: string | null; hours: string }[];
  actual_hours_required?: boolean;
  /** W-H — THE PARENT EXTRA WORK'S DATES.
   *
   *  The backend has sent all four since Sprint 184 §1 and this type
   *  did not declare them, so no screen could read them: the ticket
   *  page showed a lone `Scheduled date` while the answers to "when was
   *  this asked for, by when is it owed, what did we commit to" sat
   *  unread in the same response.
   *
   *  Two pairs and one due date, exactly as
   *  `extra_work/models.py` documents them:
   *    ASKED FOR   preferred_date -> planned_end_date
   *    COMMITTED   provider_planned_date -> provider_planned_end_date
   *    OWED BY     deadline
   *
   *  Borrowed, never copied: the extra work owns them and the ticket
   *  links back. Optional because the list serializer stops before the
   *  heavier keys. */
  preferred_date?: string | null;
  planned_end_date?: string | null;
  deadline?: string | null;
  provider_planned_date?: string | null;
  provider_planned_end_date?: string | null;
}

// Sprint 9B (backend) — operational schedule lifecycle on a ticket.
// UNSCHEDULED until a provider operator sets a date; SCHEDULED on the
// first set; RESCHEDULED once an existing schedule is changed; back to
// UNSCHEDULED when cleared. Mirrors backend
// `tickets/models.py::TicketScheduleStatus`.
export type TicketScheduleStatus =
  | "UNSCHEDULED"
  | "SCHEDULED"
  | "RESCHEDULED";

export interface TicketDetail extends TicketList {
  description: string;
  room_label: string;
  created_by: number;
  created_by_email: string;
  first_response_at: string | null;
  sent_for_approval_at: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  // Sprint 28 Batch 15.4 — non-null when this ticket was spawned by
  // an ExtraWorkRequest line. The frontend renders a "Spawned from"
  // panel in the ticket detail header that links back to the EW.
  // (Sprint 14A frontend Part A2 — declaration moved up to `TicketList`,
  // which `TicketDetail` extends; the field is inherited from there.)
  // Sprint 28 Batch 11 — timestamp the ticket entered
  // WAITING_MANAGER_REVIEW (null until STAFF marks the work as
  // completed on the manager-review default route). Mirrored from
  // the backend `Ticket.manager_review_at` column.
  manager_review_at: string | null;
  status_history: TicketStatusHistory[];
  /** Sprint 184 §3 — the date the CUSTOMER would like this done. A wish,
   *  never a commitment: it decides nothing and never makes a ticket
   *  late. On the wire since Sprint 184 and undeclared here until W-H,
   *  which is why the Scheduling card could not show the operator what
   *  was asked for while they set their own date. */
  customer_wanted_date: string | null;
  /** W-H — who set the current schedule, and when. Computed by the
   *  backend from the schedule annotation row on `status_history`;
   *  nothing new is stored. Null for a CUSTOMER_USER (which employee
   *  typed the date is internal staffing detail, gated like
   *  `reschedule_reason`) and null on a ticket nobody has planned. */
  schedule_planned_by_name: string | null;
  schedule_planned_at: string | null;
  allowed_next_statuses: TicketStatus[];
  sla_status: SLAStatus;
  sla_due_at: string | null;
  sla_started_at: string | null;
  sla_completed_at: string | null;
  sla_paused_at: string | null;
  sla_paused_seconds: number;
  sla_first_breached_at: string | null;
  // Sprint 23B — staff currently assigned via TicketStaffAssignment.
  // Empty array means no one is assigned (existing Sprint 22
  // single-assignee `assigned_to` is the legacy "primary
  // assignee" and remains the field the assign-dropdown writes).
  assigned_staff: AssignedStaffEntry[];
  // Sprint 28 Batch 11 — true when the viewer (request.user) is in
  // the ticket's TicketStaffAssignment set. Used by the frontend
  // to render the "Complete work" button only when the viewer is
  // actually assigned (and is STAFF). Backend enforces the same
  // gate on the status transition — this is purely a UX hint.
  is_assigned_staff: boolean;
  // Sprint 9B (backend) — operational scheduling. Read-only on the
  // detail serializer; mutated via the dedicated POST/DELETE
  // /tickets/<id>/schedule/ endpoint (provider-management only,
  // additive — never touches `status` or SLA). Every role that sees
  // the detail reads these (operational, no amounts). For a
  // CUSTOMER_USER the backend redacts the provider-internal reschedule
  // audit fields: `reschedule_reason` -> "" and `rescheduled_from` ->
  // null (the current date/window + schedule_status stay visible).
  scheduled_start_at: string | null;
  scheduled_end_at: string | null;
  time_window_label: string;
  schedule_status: TicketScheduleStatus;
  rescheduled_from: string | null;
  reschedule_reason: string;
  // Sprint 4 (backend) / Sprint 5 (frontend) — the ticket's named sub-tasks
  // (each with its compact staff slots + a computed `is_done`) and the
  // per-ticket PA/SA "auto-complete when every sub-task is done" opt-in.
  // Read-only here: sub-tasks are mutated via the SubTask CRUD endpoints and
  // the flag via PATCH /tickets/<id>/auto-complete-flag/. Additive.
  sub_tasks: SubTask[];
  auto_complete_on_subtasks: boolean;
  // Sprint 191 - the per-work photo-visibility setting. False (the
  // default) means a staff upload on this work lands INTERNAL and waits
  // for a provider manager to promote it; true means staff uploads here
  // are customer-visible the moment they arrive. Read-only on the detail
  // payload; mutated via PATCH
  // /tickets/<id>/attachment-visibility-policy/ (PA/SA only).
  staff_uploads_customer_visible: boolean;
  // Per-current-user, per-ticket capability block — backend
  // `TicketDetailSerializer.get_actions`. Optional so older list
  // serializers / pre-cherry-pick caches don't break typing; treat
  // an absent `actions` as all-false (hide every action-gated control).
  actions?: TicketDetailActions;
}

// Mirrors backend `tickets/serializers.py::TicketDetailSerializer.get_actions`.
// `allowed_next_statuses` is the same list as `TicketDetail.allowed_next_statuses`
// (the backend caches the computation between the two fields so they
// cannot drift). `status_transitions` is the same data reshaped as an
// O(1) lookup keyed by every TicketStatus value.
// `can_override_customer_decision` is TIGHTENED to current-record:
// True only when the viewer holds override authority AND the ticket
// is at WAITING_CUSTOMER_APPROVAL AND APPROVED/REJECTED is in the
// allowed-next list.
export interface TicketDetailActions {
  allowed_next_statuses: TicketStatus[];
  can_override_customer_decision: boolean;
  // M1 B5 — PUBLIC_REPLY is no longer "always allowed" (STAFF cannot post
  // it), so the composer needs an explicit flag; CUSTOMER_INTERNAL is the
  // new customer-only tier.
  can_post_public_reply: boolean;
  can_post_provider_internal_note: boolean;
  can_post_staff_operational_note: boolean;
  can_post_staff_completion_note: boolean;
  can_post_customer_internal_note: boolean;
  can_upload_hidden_attachment: boolean;
  status_transitions: Record<TicketStatus, boolean>;
}

// Sprint 23B — Staff-initiated "I want to do this work" request.
export type StaffAssignmentRequestStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CANCELLED";

export interface StaffAssignmentRequest {
  id: number;
  staff: number;
  staff_email: string;
  ticket: number;
  ticket_no: string | null;
  ticket_title: string;
  status: StaffAssignmentRequestStatus;
  requested_at: string;
  reviewed_by: number | null;
  reviewer_email: string | null;
  reviewed_at: string | null;
  reviewer_note: string;
}

// M1 — message visibility mode (B1 model field; B2 enforces RESTRICTED on
// the read side). NORMAL = visible to the message_type audience; RESTRICTED
// = only the author + directed_to users.
export type TicketMessageVisibility = "NORMAL" | "RESTRICTED";

export interface DirectedRecipientLabel {
  id: number;
  full_name: string;
}

export interface TicketMessage {
  id: number;
  ticket: number;
  author: number;
  author_email: string;
  message: string;
  message_type: TicketMessageType;
  // M1 B1/B3 — attention targets (writable ids) + read-only label detail +
  // visibility mode. directed_to_detail is for rendering the "-> directed
  // to X" chip; visibility_mode drives the "Private" badge.
  directed_to: number[];
  directed_to_detail: DirectedRecipientLabel[];
  visibility_mode: TicketMessageVisibility;
  is_hidden: boolean;
  created_at: string;
}

// M1 B3 — a valid directed_to target for the composer picker, from
// GET /api/tickets/<id>/message-recipients/. `side` groups the picker.
// M1 B5: the endpoint is side-aware by caller (STAFF -> [], CUSTOMER ->
// customer-side only) and no longer returns an `email` field.
export interface MessageRecipient {
  id: number;
  full_name: string;
  side: "provider" | "staff" | "customer";
}

// M1 — in-app notification (mirrors notifications.serializers.
// NotificationSerializer). Deep-link is derived from `ticket` (-> the
// ticket detail) or `extra_work` (-> EW detail, wired for B4).
/** W-LATE addendum 2 — the rung a notification stands on. INFO is
 *  activity (the soft green); L1 is the standard warning tone (orange);
 *  L2 red; L3 dark red, and its toast stays until dismissed. Mirrors
 *  `notifications.models.NotificationSeverity`. */
export type NotificationSeverity = "INFO" | "L1" | "L2" | "L3";

export interface Notification {
  id: number;
  event_type: string;
  is_directed: boolean;
  summary: string;
  severity: NotificationSeverity;
  ticket: number | null;
  ticket_no: string | null;
  ticket_title: string | null;
  extra_work: number | null;
  extra_work_title: string | null;
  actor_id: number | null;
  actor_name: string | null;
  actor_email: string | null;
  read_at: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Notification[];
  unread_count: number;
}

// Sprint W4-Q §1 — the three TIME-DRIVEN feed types. Every other
// notification in the feed is a reaction to somebody doing something;
// these three exist because nothing happened and it should have, and
// the feed renders them as warnings rather than as activity.
//
// The strings match `notifications.models.NotificationType` (and, by
// design, its email twin `NotificationEventType` — one event, two
// channels, one spelling). An ORDERED exported constant that every
// consumer iterates, never a second local copy: a hardcoded array
// literal somewhere else is exactly what hid the `documents` permission
// group for three sprints.
export const SLA_WARNING_EVENT_TYPES = [
  "SLA_APPROVAL_CUTOFF_DUE",
  "SLA_MANAGER_REVIEW_OVERDUE",
  "SLA_WORK_NOT_STARTED",
  // W-LATE §2 — the three escalation steps of the late ladder. They
  // NAME themselves the same way the SLA three do; their tone comes
  // from the row's own `severity`, not from this list.
  "TICKET_LATE_L2_MANAGERS",
  "TICKET_LATE_L2_ESCALATED",
  "TICKET_LATE_L3_QUARANTINE",
] as const;
export type SlaWarningEventType = (typeof SLA_WARNING_EVENT_TYPES)[number];

export function isSlaWarningEvent(
  eventType: string,
): eventType is SlaWarningEventType {
  return (SLA_WARNING_EVENT_TYPES as readonly string[]).includes(eventType);
}

// Sprint W4-Q §2 — the per-company warning thresholds
// (backend/sla/serializers_thresholds.py).
//
// `effective`, `override` and `default` are three separate numbers on
// purpose. `override === null` means this company stored nothing and is
// running on the platform default; a stored 0 is a real, legal
// threshold ("warn me the moment it lands") and must never render the
// same as "not configured".
export const SLA_THRESHOLD_UNITS = [
  "days",
  "business_hours",
  "hours",
] as const;
export type SlaThresholdUnit = (typeof SLA_THRESHOLD_UNITS)[number];

export interface SlaThresholdRow {
  field: string;
  unit: SlaThresholdUnit;
  effective: number;
  override: number | null;
  default: number;
}

export interface SlaCompanyThresholds {
  company: number;
  company_name: string;
  updated_at: string | null;
  updated_by_name: string | null;
  is_customized: boolean;
  thresholds: SlaThresholdRow[];
}

export interface SlaBusinessWindow {
  start: string;
  end: string;
  /** Python weekday numbers, Mon=0. Labelled by the frontend so the
   *  sentence translates. */
  days: number[];
  hours_per_day: number;
}

export interface SlaThresholdListResponse {
  results: SlaCompanyThresholds[];
  defaults: Record<string, number>;
  fields: { field: string; unit: SlaThresholdUnit }[];
  business_window: SlaBusinessWindow;
}


// Sprint 191 - the two new attachment axes, deliberately independent of
// each other and of `is_hidden`. `visibility` is the customer wall
// (INTERNAL = provider side only, CUSTOMER = released to the customer);
// `phase` is a label and decides nothing. Mirrors
// tickets.models.AttachmentVisibility / AttachmentPhase.
export const ATTACHMENT_VISIBILITIES = ["INTERNAL", "CUSTOMER"] as const;
export type AttachmentVisibility = (typeof ATTACHMENT_VISIBILITIES)[number];

export const ATTACHMENT_PHASES = ["UNSPECIFIED", "BEFORE", "AFTER"] as const;
export type AttachmentPhase = (typeof ATTACHMENT_PHASES)[number];

// W4-P — tickets.models.UploadVisibilitySource. WHICH rung of the
// resolution ladder decided a stored attachment's visibility at upload:
// per-ticket > standing > per-work setting > default. "" is every row
// written before the column existed and reads "unrecorded", never
// "default".
export const UPLOAD_VISIBILITY_SOURCES = [
  "",
  "UPLOADER_CHOICE",
  "CUSTOMER_UPLOAD",
  "TICKET_GRANT",
  "STANDING_GRANT",
  "WORK_SETTING",
  "DEFAULT_INTERNAL",
  "MANUAL",
] as const;
export type UploadVisibilitySource =
  (typeof UPLOAD_VISIBILITY_SOURCES)[number];

// W4-P — one scope's answer for one person. `uploads_customer_visible`
// is a TRI-STATE and the three states are not interchangeable:
//   true  = a grant     — this person's uploads land customer-visible
//   false = a refusal   — they stay internal, beating anything less
//                         specific
//   null  = no decision — the next rung down answers
export interface UploadVisibilityGrantState {
  user_id: number;
  ticket_id: number | null;
  uploads_customer_visible: boolean | null;
  reason: string;
  granted_by_id: number | null;
  updated_at: string | null;
}

// W4-P — the per-ticket read (`GET /tickets/<id>/upload-visibility/`),
// one entry per DISTINCT person holding a slot on the ticket. Carries
// every rung so the Assignment card can state which one is deciding.
export interface TicketUploadVisibilityPerson
  extends UploadVisibilityGrantState {
  user_email: string;
  user_full_name: string;
  standing_uploads_customer_visible: boolean | null;
  effective_visibility: AttachmentVisibility;
  effective_source: UploadVisibilitySource;
}

export interface TicketUploadVisibility {
  ticket_id: number;
  staff_uploads_customer_visible: boolean;
  people: TicketUploadVisibilityPerson[];
}

export interface TicketAttachment {
  id: number;
  ticket: number;
  message: number | null;
  uploaded_by: number;
  uploaded_by_email: string;
  file_url: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  is_hidden: boolean;
  visibility: AttachmentVisibility;
  phase: AttachmentPhase;
  // W4-P — read-only record of WHICH rung produced `visibility`.
  visibility_source: UploadVisibilitySource;
  created_at: string;
}

export interface AssignableManager {
  id: number;
  email: string;
  full_name: string;
  role: "BUILDING_MANAGER";
}

export interface TicketStats {
  total: number;
  by_status: Partial<Record<TicketStatus, number>>;
  by_priority: Partial<Record<string, number>>;
  my_open: number;
  waiting_customer_approval: number;
  urgent: number;
}

export interface TicketStatsByBuildingRow {
  building_id: number;
  building_name: string;
  total: number;
  open: number;
  in_progress: number;
  waiting_customer_approval: number;
  urgent: number;
}

export type TicketStatsByBuildingResponse = TicketStatsByBuildingRow[];

// Sprint 28 Batch 9 — Extra Work dashboard aggregates.
//
// Mirrors backend/extra_work/views.py — `stats` and
// `stats/by-building` endpoints. The aliases reuse the existing
// `ExtraWorkStatus` / `ExtraWorkUrgency` / `RoutingDecision`
// nominal types (defined later in this file) so the wire-side
// vocabulary is enforced by the type system rather than being
// duplicated.
//
// `by_status` / `by_routing` / `by_urgency` are `Partial<Record<...>>`
// because the backend omits zero buckets. The KPI fields (`active`,
// `awaiting_pricing`, `awaiting_customer_approval`, `urgent`) are
// always present — they default to 0 when out-of-scope (e.g. STAFF,
// whose `scope_extra_work_for` returns `.none()`).
export type ExtraWorkStatusValue = ExtraWorkStatus;
export type ExtraWorkRoutingValue = RoutingDecision;
export type ExtraWorkUrgencyValue = ExtraWorkUrgency;

export interface ExtraWorkStats {
  total: number;
  by_status: Partial<Record<ExtraWorkStatusValue, number>>;
  by_routing: Partial<Record<ExtraWorkRoutingValue, number>>;
  by_urgency: Partial<Record<ExtraWorkUrgencyValue, number>>;
  active: number;
  awaiting_pricing: number;
  awaiting_customer_approval: number;
  urgent: number;
}

export interface ExtraWorkStatsByBuildingRow {
  building_id: number;
  building_name: string;
  total: number;
  active: number;
  awaiting_pricing: number;
  awaiting_customer_approval: number;
  urgent: number;
}

export type ExtraWorkStatsByBuildingResponse = ExtraWorkStatsByBuildingRow[];

export type InvitationStatus =
  | "PENDING"
  | "ACCEPTED"
  | "REVOKED"
  | "EXPIRED";

export interface InvitationPreview {
  email: string;
  full_name: string;
  role: Role;
  inviter_email: string;
  inviter_full_name: string;
  company_names: string[];
  building_names: string[];
  customer_names: string[];
  expires_at: string;
}

export interface CompanyAdmin {
  id: number;
  name: string;
  slug: string;
  default_language: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Provider-policy flags. All default false and are SUPER_ADMIN-only
  // WRITABLE (the backend CompanySerializer.validate_* methods reject a
  // non-SA writer); readable by anyone the CompanyViewSet admits. The
  // last one is the DANGEROUS quote-bypass grant (SoT §2.1 / §5.5).
  provider_admin_may_manage_customer_company_admins: boolean;
  provider_admin_may_manage_catalog: boolean;
  provider_admin_may_manage_customer_prices: boolean;
  provider_admin_may_quote_override_start: boolean;
  // RF-1 — provider company logo URL (null when unset).
  logo_url?: string | null;
}

// The four SUPER_ADMIN-only provider-policy flags, in display order. The
// quote-override grant is flagged dangerous so the UI can mark it.
export const COMPANY_POLICY_FLAGS = [
  "provider_admin_may_manage_customer_company_admins",
  "provider_admin_may_manage_catalog",
  "provider_admin_may_manage_customer_prices",
  "provider_admin_may_quote_override_start",
] as const;
export type CompanyPolicyFlag = (typeof COMPANY_POLICY_FLAGS)[number];

/** Sprint 178 §1 — one row of a company's own building-type catalog. */
export interface BuildingTypeOption {
  id: number;
  company: number;
  company_name?: string;
  name: string;
  is_active: boolean;
  sort_order?: number;
  usage_count?: number;
}

export interface BuildingAdmin {
  id: number;
  company: number;
  name: string;
  /** Sprint 178 §1 — the type's id, and its resolved name alongside.
   *  Both null when the building is unclassified; the keys are always
   *  present, so a client never has to tell "absent" from "null". */
  building_type?: number | null;
  building_type_name?: string | null;
  address: string;
  city: string;
  country: string;
  postal_code: string;
  is_active: boolean;
  // Sprint 154 §I.5 — per-row counts, annotated on the list queryset (no
  // N+1). Optional because the create/update responses and older cached
  // payloads may predate them.
  customer_count?: number;
  manager_count?: number;
  staff_count?: number;
  contact_count?: number;
  /** Bounded preview for the list's Customers column: the first few
   *  names plus the TRUE total, so the cell can render "A, B +3" without
   *  a second request and without an unbounded list. */
  customer_names?: { names: string[]; total: number };
  created_at: string;
  updated_at: string;
}

/**
 * Sprint 154 §I.6 — GET /api/buildings/<id>/summary/.
 *
 * Same contract as `CustomerSummary`: `null` means "this module is not
 * yours to read" and renders an em dash; `0` means "readable and empty".
 * Never collapse the two with `?? 0`.
 *
 * `room_count` is ALWAYS null: this system has no room concept — no
 * model, no app, no field. The key exists so the shape is stable.
 */
export interface BuildingSummary {
  room_count: number | null;
  customer_count: number | null;
  manager_count: number | null;
  staff_count: number | null;
  contact_count: number | null;
  ticket_count: number | null;
  open_ticket_count: number | null;
  extra_work_count: number | null;
  open_extra_work_count: number | null;
}

/** Sprint 154 §G.2 — one staff member linked to a building. The
 *  per-BUILDING view of `BuildingStaffVisibility`; the per-USER view is
 *  `StaffVisibilityRow`. `user_phone` is `User.phone`, NOT the
 *  staff-only, visibility-gated `StaffProfile.phone`. */
export interface BuildingStaffRow {
  id: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  user_phone: string;
  visibility_level: string;
  can_request_assignment: boolean;
  created_at: string;
}

/** Sprint 154 §G.2 — one contact person linked to a building. A contact
 *  may or may not have a login, which `has_login` reports. */
export interface BuildingContactRow {
  id: number;
  contact_id: number;
  full_name: string;
  email: string;
  phone: string;
  role_label: string;
  customer_id: number;
  customer_name: string;
  has_login: boolean;
  created_at: string;
}

/** Sprint 154 §I.2 — the four relations the bulk link/unlink endpoint
 *  understands. One endpoint, four bindings. */
export type BuildingLinkRelation =
  | "customers"
  | "managers"
  | "staff"
  | "contacts";

export interface BuildingBulkLinkResult {
  created: number;
  removed: number;
  already_linked: number;
  not_linked: number;
}

export interface CustomerAdmin {
  id: number;
  company: number;
  // Sprint 14: legacy single-building anchor, now nullable. New
  // consolidated customers can be created with no anchor and linked
  // to multiple buildings via the M:N CustomerBuildingMembership.
  building: number | null;
  // Sprint 153 — per-row counts, annotated on the list queryset (no
  // N+1). `linked_building_count` counts M:N membership rows only; it
  // deliberately ignores the deprecated `building` anchor above.
  linked_building_count: number;
  user_count: number;
  contact_count: number;
  name: string;
  contact_email: string;
  phone: string;
  language: string;
  is_active: boolean;
  /** Sprint 185 §1 — the BILLING address, printed on every invoice.
   *  A building's address is the work site and is NOT this. */
  address: string;
  postal_code: string;
  city: string;
  country: string;
  /** Server-computed: street AND city both filled. Read-only — the
   *  screen must not re-derive the rule the PDF actually applies. */
  has_billing_address: boolean;
  /** Sprint 185 §3 — where the relationship IS. Descriptive only:
   *  `is_active` above still decides access, and nothing here may
   *  change it. */
  lifecycle: CustomerLifecycle;
  // Sprint 23B — assigned-staff contact-visibility policy. Defaults
  // True. The CustomerFormPage exposes these as three checkboxes
  // for OSIUS Admin / Company Admin only.
  show_assigned_staff_name: boolean;
  show_assigned_staff_email: boolean;
  show_assigned_staff_phone: boolean;
  // RF-1 — customer company logo URL (null when unset).
  logo_url?: string | null;
  // Invoicing Phase 4a — billing schedule (writable by OSIUS admins) +
  // read-only contract-PDF URL. `invoice_day_rule` is "" when unset.
  invoice_day_rule?: InvoiceDayRule | "";
  // Arbitrary billing day (1..28); when set it takes precedence over the
  // first/last rule. NULL falls back to invoice_day_rule.
  invoice_day_of_month?: number | null;
  invoice_granularity_default?: InvoiceGranularity;
  contract_pdf_url?: string | null;
  created_at: string;
  updated_at: string;
  // Per-current-user, per-customer capability block from the
  // CustomerSerializer.actions field. Optional for older list payloads.
  actions?: CustomerActions;
}

/**
 * Sprint 153 §2.4 — GET /api/customers/<id>/summary/.
 *
 * Every field is nullable ON PURPOSE. `null` means "this module is not
 * yours to read" and renders as an unlinked em dash; `0` means "you can
 * read it and it is empty". Do not collapse the two with `?? 0` — that
 * would tell a staff user there is no extra work when in fact there is
 * extra work they may not see.
 */
export interface CustomerSummary {
  linked_building_count: number | null;
  user_count: number | null;
  contact_count: number | null;
  pricing_rule_count: number | null;
  open_ticket_count: number | null;
  ticket_count: number | null;
  open_extra_work_count: number | null;
  extra_work_count: number | null;
  unpaid_invoice_count: number | null;
  /** Decimal STRING (e.g. "1250.00") — money never goes through a float. */
  unpaid_invoice_total: string | null;
}

// Sprint 14 — Customer ↔ Building (M:N) link.
/** Sprint 156 §1 — the company detail page's stat tiles.
 *
 * Every count may be `null`, and `null` is NOT `0`: it means the block
 * was not answerable for this actor (the server wraps each one so a
 * single unreadable module degrades rather than 500s). The page renders
 * an em dash for null, never a zero. */
export interface CompanySummary {
  building_count: number | null;
  customer_count: number | null;
  admin_count: number | null;
  employee_count: number | null;
  ticket_count: number | null;
  open_ticket_count: number | null;
  extra_work_count: number | null;
  open_extra_work_count: number | null;
}

/** One COMPANY_ADMIN of a company. `phone` is `User.phone` — the ungated
 *  account field, never the visibility-gated `StaffProfile.phone`. */
export interface CompanyAdminPerson {
  id: number;
  email: string;
  full_name: string;
  phone: string;
  is_active: boolean;
}

/** One provider-side employee, with the buildings they are on — the
 *  "who can do what, where" row. */
export interface CompanyEmployee {
  id: number;
  email: string;
  full_name: string;
  phone: string;
  role: string;
  is_active: boolean;
  buildings: { id: number; name: string }[];
}

export interface CompanyBuildingRow {
  id: number;
  name: string;
  address: string;
  city: string;
  postal_code: string;
  is_active: boolean;
  customer_count: number;
}

export interface CompanyCustomerRow {
  id: number;
  name: string;
  is_active: boolean;
  building_count: number;
  user_count: number;
}

/** Sprint 157 §2 — who is assigned to an Extra Work request.
 *
 *  `role` is the ASSIGNMENT role (what they are doing on this request),
 *  deliberately not the same thing as `user_role`, the account role. A
 *  BUILDING_MANAGER may be assigned as a WORKER on a small job. */
export type ExtraWorkAssignmentRole = "WORKER" | "MANAGER";

export interface ExtraWorkAssignment {
  id: number;
  extra_work_request: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  /** `User.phone` — the ungated account field, never the
   *  visibility-gated `StaffProfile.phone`. */
  user_phone: string;
  user_role: string;
  role: ExtraWorkAssignmentRole;
  assigned_at: string;
}

/** Sprint 158 §1 — one eligible person for a given (request, role) or
 *  (ticket, role). The server decides eligibility from the BUILDING; the
 *  client never computes it. */
export interface AssignmentCandidate {
  id: number;
  email: string;
  full_name: string;
  role: string;
}

export interface ExtraWorkBulkAssignResult {
  created: number;
  removed: number;
  already_assigned: number;
  not_assigned: number;
}

export interface CustomerBuildingMembership {
  id: number;
  customer: number;
  building_id: number;
  building_name: string;
  building_address: string;
  // Sprint 153 §4.3 — "" when the building has no city on file.
  building_city: string;
  // Sprint 154 §G.2 — the row is read from BOTH ends now (the customer's
  // buildings page and the building's customers card), so it carries the
  // customer's name too.
  customer_name: string;
  // Sprint 155 §2 — what the customer overview's Linked buildings card
  // fills its empty right-hand half with. All annotated server-side; the
  // two counts are numbers, never null, because zero is a real answer.
  building_postal_code: string;
  building_is_active: boolean;
  building_customer_count: number;
  building_manager_count: number;
  // Sprint 157 §8 — the third count, annotated in the same pass.
  building_contact_count: number;
  created_at: string;
}

// Sprint 14 — per-customer-user, per-building access grant.
// Sprint 23A — per-building access role on the customer side.
export type CustomerAccessRole =
  | "CUSTOMER_USER"
  | "CUSTOMER_LOCATION_MANAGER"
  | "CUSTOMER_COMPANY_ADMIN";

export interface CustomerUserBuildingAccess {
  id: number;
  membership_id: number;
  user_id: number;
  user_email: string;
  building_id: number;
  building_name: string;
  // Sprint 23B — Sprint 23A fields surfaced read-only for the
  // admin UI. Sprint 23C added write support for access_role;
  // Sprint 27C added write support for permission_overrides
  // and is_active. Sprint 27E surfaces both as editable UI.
  access_role: CustomerAccessRole;
  is_active: boolean;
  permission_overrides: Record<string, boolean>;
  created_at: string;
}

// Sprint 23A — canonical customer-side permission keys (mirrors
// `customers.permissions.CUSTOMER_PERMISSION_KEYS`). Sprint 27E's
// permission-override editor renders one row per key with a 3-way
// Inherit/Grant/Revoke control. The key list lives in source code
// rather than being fetched so the UI can render synchronously;
// the backend serializer rejects unknown keys on PATCH so a stale
// frontend cannot widen the allow-list.
export const CUSTOMER_PERMISSION_KEYS = [
  "customer.ticket.create",
  "customer.ticket.view_own",
  "customer.ticket.view_location",
  "customer.ticket.view_company",
  "customer.ticket.approve_own",
  "customer.ticket.approve_location",
  "customer.extra_work.create",
  "customer.extra_work.view_own",
  "customer.extra_work.view_location",
  "customer.extra_work.view_company",
  "customer.extra_work.approve_own",
  "customer.extra_work.approve_location",
  "customer.users.invite",
  "customer.users.manage",
  "customer.users.assign_location_role",
  "customer.users.manage_permissions",
  // Sprint 125/126 — the Customer Documents module (one coarse key).
  "customer.documents.manage",
] as const;
export type CustomerPermissionKey = (typeof CUSTOMER_PERMISSION_KEYS)[number];

// Sprint 27E — per-customer policy row. Mirrors the backend
// `CustomerCompanyPolicy` model. Both halves (visibility + the
// four `customer_users_can_*` booleans) are editable from the
// Sprint 27E CustomerFormPage policy panel.
export interface CustomerCompanyPolicyAdmin {
  customer_id: number;
  show_assigned_staff_name: boolean;
  show_assigned_staff_email: boolean;
  show_assigned_staff_phone: boolean;
  customer_users_can_create_tickets: boolean;
  customer_users_can_approve_ticket_completion: boolean;
  customer_users_can_create_extra_work: boolean;
  customer_users_can_approve_extra_work_pricing: boolean;
  // Sprint 126 — company-wide toggle for the customer Documents module.
  customer_users_can_manage_documents: boolean;
}

// Sprint 126 — customer Documents. Mirrors the backend read serializers
// (documents/serializers.py). `parent` is null for a root folder; a file is
// addressed in the API only by its opaque `public_id` (never the row pk).
export type DocumentOrigin = "PROVIDER" | "CUSTOMER";

export interface DocumentFolder {
  id: number;
  parent: number | null;
  name: string;
  is_system: boolean;
  system_slug: string;
  origin: DocumentOrigin;
  // Sprint 155 §3 — this folder's OWN files, not its subtree's. Annotated
  // on the list queryset, so the number is free; it is the headline
  // figure on the folder cards.
  file_count: number;
  created_at: string;
}

export interface DocumentFile {
  public_id: string;
  folder: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  origin: DocumentOrigin;
  uploaded_by_email: string | null;
  created_at: string;
}

// Sprint 28 Batch 15.5 — user-list scope summary surfaced as a single
// chip per row on the Users admin page. Backend contract:
//   - SUPER_ADMIN  →  { label: "all", count: -1 }  (sentinel: all companies)
//   - COMPANY_ADMIN / BUILDING_MANAGER / STAFF / CUSTOMER_USER →
//     a real count keyed by the dominant scope axis for that role
//     (companies for provider admins, buildings for managers/staff,
//     customers for customer users). Backend resolver lives in
//     accounts/serializers_users.py::UserAdminListSerializer.
export interface UserScopeSummary {
  label: "all" | "companies" | "buildings" | "customers";
  count: number;
}

// Sprint 187B §1a — WHICH companies a user belongs to, beside
// `UserScopeSummary`'s HOW MANY. A sibling of `scope_summary`, not an
// extension of it: that field's `count` means a different thing per role
// (buildings for a building manager), so company names inside it would
// put two axes in one object. `all: true` is the SUPER_ADMIN sentinel and
// renders as "All companies", exactly as the scope chip already does.
export interface UserCompanies {
  all: boolean;
  names: string[];
}

export interface UserAdmin {
  id: number;
  email: string;
  full_name: string;
  // Sprint 154 §I.1 — the user's OWN contact number. Distinct from
  // `StaffProfile.phone`, which is staff-only and gated on the customer
  // side by `show_assigned_staff_phone`. "" when unset, never null.
  phone: string;
  role: Role;
  language: string;
  is_active: boolean;
  deleted_at: string | null;
  // Sprint 28 Batch 15.5 — added by the user-list serializer. The
  // field is required on the wire; if the backend ever returns a
  // payload without it the type-check here flags it at the call
  // site rather than silently rendering an empty chip.
  scope_summary: UserScopeSummary;
  // Sprint 187B §1a — the companies this user belongs to, by name.
  companies: UserCompanies;
  // Sprint 2c — read-only single HIGHEST effective customer access role the
  // user holds (CUSTOMER_COMPANY_ADMIN > CUSTOMER_LOCATION_MANAGER >
  // CUSTOMER_USER), company-scoped to the viewer; null for provider-side
  // users / no in-scope active grant. Editing stays in the per-customer
  // permission matrix / the contact->user surface.
  customer_access_role: CustomerAccessRole | null;
}

export interface UserAdminDetail extends UserAdmin {
  // Sprint 188 — the provider companies that EMPLOY this person, by name.
  // An OWN property, deliberately not reusing the list's `companies`:
  // that field includes the provider a CUSTOMER_USER buys from, which is
  // the exact conflation this one exists to end. Empty for a customer
  // user and for a SUPER_ADMIN (a platform admin is nobody's employee).
  employed_by: string[];
  company_ids: number[];
  building_ids: number[];
  customer_ids: number[];
}

// Employees directory (provider side) — one row from GET /api/employees/.
// Admits SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER. `employment_type`
// is non-null only for STAFF rows; provider-admin and building-manager
// rows report null.
export interface ProviderEmployee {
  id: number;
  full_name: string;
  email: string;
  // Sprint 154 §K — `User.phone`, the account's own number. NOT
  // `StaffProfile.phone`: that one is staff-only and gated by
  // `show_assigned_staff_phone`, and this directory's serializer has a
  // documented privacy floor that forbids it.
  phone: string;
  role: Role;
  employment_type: EmploymentType | null;
  // Sprint 187B §2 — the PROVIDER company(ies) employing this person. A
  // plain list, with no "all" sentinel: this directory lists only
  // COMPANY_ADMIN / BUILDING_MANAGER / STAFF rows and none of those roles
  // is global, so there is no all-companies case to represent. A provider
  // company name is not customer linkage; the serializer's docstring
  // carries the reasoning for amending that privacy floor.
  companies: string[];
  is_active: boolean;
}

// Employees directory (customer side) — one row from
// GET /api/customers/<cid>/employees/. `id` is the USER id.
// `customer_access_role` is the highest effective access role the user
// holds at this customer (null when none is active).
export interface CustomerEmployee {
  id: number;
  full_name: string;
  email: string;
  customer_access_role: CustomerAccessRole | null;
  is_active: boolean;
}

export interface InvitationAdmin {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  status: "PENDING" | "ACCEPTED" | "REVOKED" | "EXPIRED";
  created_at: string;
  expires_at: string;
  created_by_email: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

// Sprint 24A — admin write shape for the Sprint 23A StaffProfile.
export interface StaffProfileAdmin {
  id: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  phone: string;
  personnel_number: string;
  internal_note: string;
  can_request_assignment: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// Sprint 28 Batch 10 — per-row visibility level on BuildingStaffVisibility.
// Mirrors backend `BuildingStaffVisibility.VisibilityLevel`:
//   - "ASSIGNED_ONLY"            — STAFF recognised as a direct-assign
//                                   target for tickets in this building
//                                   but does NOT see other tickets.
//   - "BUILDING_READ"            — sees every ticket in the building
//                                   (legacy Sprint 24–28 behaviour;
//                                   default value on existing rows).
//   - "BUILDING_READ_AND_ASSIGN" — building-read PLUS may call
//                                   POST /tickets/<id>/assign/ (B3).
// The vocabulary is owned by the backend model field; the frontend
// must NEVER pre-filter the building dropdown by level — every BSV
// row (regardless of level) keeps the STAFF user reachable as an
// assign target. The selector below is purely a write surface.
export type StaffVisibilityLevel =
  | "ASSIGNED_ONLY"
  | "BUILDING_READ"
  | "BUILDING_READ_AND_ASSIGN";

// Sprint 24A — admin read/write shape for a single BuildingStaffVisibility
// row keyed on (user, building). Editing happens via PATCH on the
// detail URL; writable fields are `can_request_assignment` (Sprint 24A),
// `visibility_level` (Sprint 28 Batch 10), and
// `staff_completion_routes_to_customer` (Sprint 28 Batch 11). When the
// completion-routes flag is true, STAFF marking a ticket in this
// building as completed sends it straight to WAITING_CUSTOMER_APPROVAL
// (skipping the WAITING_MANAGER_REVIEW gate). Default false.
export interface BuildingStaffVisibilityAdmin {
  id: number;
  user_id: number;
  user_email: string;
  building_id: number;
  building_name: string;
  building_company_id: number;
  can_request_assignment: boolean;
  visibility_level: StaffVisibilityLevel;
  staff_completion_routes_to_customer: boolean;
  created_at: string;
}

// Sprint 28 Batch 11 — staff-completion routing helper. Returned by
// GET /api/tickets/<id>/staff-completion-route/. "manager_review" is
// the default (STAFF -> BM gate); "customer_approval" is the
// configured-bypass route from BuildingStaffVisibility.
export type StaffCompletionRoute = "manager_review" | "customer_approval";
export interface StaffCompletionRouteResponse {
  route: StaffCompletionRoute;
}

export type NotificationEventType =
  | "TICKET_CREATED"
  | "TICKET_STATUS_CHANGED"
  | "TICKET_ASSIGNED"
  | "TICKET_UNASSIGNED"
  // IA 2026-06-25 — in-app feed toggles (default muted: message events
  // left the notification feed; an unmuted row is the opt-in).
  | "TICKET_MESSAGE"
  | "EXTRA_WORK_MESSAGE";

export interface NotificationPreferenceEntry {
  event_type: NotificationEventType;
  label: string;
  muted: boolean;
}

export interface NotificationPreferencesResponse {
  preferences: NotificationPreferenceEntry[];
}

// Sprint 18 — audit log feed. Mirrors backend/audit/serializers.py
// and audit/models.py::AuditAction. `changes` is an opaque per-field
// diff; the schema is `{ field: { before, after } }` plus
// hand-crafted shapes for the membership/assignment models — see
// `audit/signals.py`. The page renders it as JSON so future schema
// drift does not silently hide fields.
export type AuditAction = "CREATE" | "UPDATE" | "DELETE";

// Sprint 14E (SoT §9.2) — audit severity / red-flag marker. NORMAL is the
// quiet default for routine mutations; HIGH marks a dangerous / red-flag
// business event the feed renders with a badge. Mirrors
// backend/audit/models.py::AuditSeverity.
export type AuditSeverity = "NORMAL" | "HIGH";

export interface AuditLog {
  id: number;
  actor: number | null;
  actor_email: string | null;
  action: AuditAction;
  target_model: string;
  target_id: number;
  changes: Record<string, unknown>;
  created_at: string;
  request_ip: string | null;
  request_id: string | null;
  // Sprint 27F-B2 — operator-supplied free text explaining a privileged
  // mutation. Default empty for legacy / system writes.
  reason: string;
  // Sprint 27F-B2 — snapshot of the actor's role + scope anchors at write
  // time. Shape: { role, user_id, company_ids, customer_id, building_id }.
  // Empty dict for anonymous / system writes.
  actor_scope: Record<string, unknown>;
  // Sprint 14E — severity marker + structured event metadata. The audit
  // serializer always returns both (severity defaults to NORMAL, metadata
  // to {}).
  severity: AuditSeverity;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Sprint 14A — unified ticket audit timeline (GET /api/audit/tickets/<id>/
// timeline/). A flat, timestamp-sorted feed merging five sources, keyed on
// the `source` discriminator. Mirrors backend/audit/views_ticket_timeline.py.
// Provider-audit only (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER); the
// SPA must not fetch it for STAFF / CUSTOMER_USER (the endpoint 403s them).
// ---------------------------------------------------------------------------
export type TicketTimelineSource =
  | "status_history"
  | "audit_log"
  | "extra_work_link"
  | "extra_work_status_history"
  | "planned_occurrence_link";

export interface TimelineStatusHistoryRow {
  source: "status_history";
  timestamp: string | null;
  old_status: string;
  new_status: string;
  note: string;
  is_override: boolean;
  override_reason: string;
  changed_by_email: string | null;
}

export interface TimelineAuditLogRow {
  source: "audit_log";
  timestamp: string | null;
  target_model: string;
  target_id: number;
  action: AuditAction;
  changes: Record<string, unknown>;
  reason: string;
  severity: AuditSeverity;
  metadata: Record<string, unknown>;
  actor_email: string | null;
}

export interface TimelineExtraWorkLinkRow {
  source: "extra_work_link";
  timestamp: string | null;
  extra_work_id: number;
  extra_work_status: string;
  relation: "spawned_from" | "converted_source";
}

export interface TimelineExtraWorkStatusHistoryRow {
  source: "extra_work_status_history";
  timestamp: string | null;
  extra_work_id: number;
  old_status: string;
  new_status: string;
  note: string;
  is_override: boolean;
  changed_by_email: string | null;
}

export interface TimelinePlannedOccurrenceLinkRow {
  source: "planned_occurrence_link";
  timestamp: string | null;
  occurrence_id: number;
  status: string;
  planned_date: string | null;
}

export type TicketTimelineRow =
  | TimelineStatusHistoryRow
  | TimelineAuditLogRow
  | TimelineExtraWorkLinkRow
  | TimelineExtraWorkStatusHistoryRow
  | TimelinePlannedOccurrenceLinkRow;

export interface TicketAuditTimeline {
  ticket_id: number;
  ticket_no: string;
  generated_at: string;
  timeline: TicketTimelineRow[];
}

// ---------------------------------------------------------------------------
// Sprint 26B — Extra Work MVP types
// ---------------------------------------------------------------------------
export type ExtraWorkCategory =
  | "DEEP_CLEANING"
  | "WINDOW_CLEANING"
  | "FLOOR_MAINTENANCE"
  | "SANITARY_SERVICE"
  | "WASTE_REMOVAL"
  | "FURNITURE_MOVING"
  | "EVENT_CLEANING"
  | "EMERGENCY_CLEANING"
  | "OTHER";

export type ExtraWorkUrgency = "NORMAL" | "HIGH" | "URGENT";

export type ExtraWorkStatus =
  | "REQUESTED"
  | "UNDER_REVIEW"
  | "PRICING_PROPOSED"
  | "CUSTOMER_APPROVED"
  // Sprint 29 Batch 29.8 — operational segment. CUSTOMER_APPROVED is
  // no longer terminal; the request progresses through IN_PROGRESS
  // (driven either by the auto-sync hook on the first spawned-ticket
  // IN_PROGRESS transition, or by a provider manual transition) into
  // COMPLETED (auto when all spawned tickets are terminal, or
  // provider manual).
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CUSTOMER_REJECTED"
  | "CANCELLED";

export type ExtraWorkUnitType =
  | "HOURS"
  | "SQUARE_METERS"
  | "FIXED"
  | "ITEM"
  | "OTHER";

/** Sprint 180 §3 — WHICH INVOICE this work's amount lands on: one
 *  addressed to the building, or one addressed to the customer
 *  organisation. It moves the line between documents and touches no
 *  amount, no VAT and no hour — `invoicing/billing_target.py` is the
 *  only reader.
 *
 *  NULL is the third state and the normal one (Sprint 182 §6, migration
 *  0032 nulled every existing row): "this job has no opinion, follow the
 *  customer's own `invoice_billing_target`". A non-null value overrules
 *  that customer setting for this one job, which is why it is never a
 *  default — writing BUILDING into a row nobody touched silently routes
 *  a customer-level customer per building.
 *
 *  Mirrors `extra_work.models.ExtraWorkBilledTo`. */
export type ExtraWorkBilledTo = "BUILDING" | "CUSTOMER";

/** Sprint 180 §2 — an operational ticket born from an Extra Work.
 *
 *  Resolved through the CANONICAL FK (`Ticket.extra_work_request`) and
 *  nothing else, which is the same definition the invoice run uses.
 *  `ticket_no` is null only for a ticket whose number has not been
 *  stamped yet. Mirrors `extra_work/serializers.py
 *  ::_serialize_spawned_tickets`. */
export interface ExtraWorkSpawnedTicket {
  id: number;
  ticket_no: string | null;
  status: TicketStatus;
  /** W12 §2 — the ticket's OWN scheduled start, echoed read-only so the
   *  Extra Work screen can show when a ticket kept a date of its own
   *  instead of the one the plan set. The ticket still owns it. */
  scheduled_start_at: string | null;
  /** RESCHEDULED means a person moved this ticket by hand, which is
   *  exactly the case `apply_planned_date_to_tickets` refuses to
   *  overwrite. */
  schedule_status: "UNSCHEDULED" | "SCHEDULED" | "RESCHEDULED";
}

// List shape (lean — no description / notes / line items).
export interface ExtraWorkRequestList {
  /** Sprint 173 §4 / Sprint 174 §1 — the deadline, the planned window's
   *  end, and the two facts DERIVED from them server-side so the list,
   *  the detail page and the Work Plan cannot disagree about what
   *  "late" or "started early" means. */
  deadline: string | null;
  planned_end_date: string | null;
  preferred_date: string | null;
  is_overdue: boolean;
  started_before_plan: boolean;
  id: number;
  company: number;
  company_name: string;
  building: number;
  building_name: string;
  customer: number;
  customer_name: string;
  // Sprint 127 — per-customer Extra Work labels. `*_name` is null for an
  // untagged row. Visible to every viewer (a label is not sensitive).
  department: number | null;
  department_name: string | null;
  work_type: number | null;
  work_type_name: string | null;
  // Sprint 144 §1 — the classifier the operator actually chose. At most
  // one is set; a pre-144 request has neither and only the `category`
  // enum below. Both surfaces render whichever is present and fall back
  // to the enum label, so the two shapes coexist.
  service_category: number | null;
  service_category_name: string | null;
  price_folder: number | null;
  price_folder_name: string | null;
  title: string;
  category: ExtraWorkCategory;
  urgency: ExtraWorkUrgency;
  status: ExtraWorkStatus;
  display_phase: ExtraWorkDisplayPhase;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
  // Sprint 188 — has anyone priced this yet? Zero is a legal price, so
  // the three columns above cannot answer that on their own. Optional:
  // an older cached payload omits it, and `isPriced()` reads absent as
  // "priced" so a stale client never blanks out a real amount.
  is_priced?: boolean;
  // RF-13 (#106) — final (actual-hours) amounts on the list shape so
  // the invoices overview can apply the final-with-quoted-fallback
  // rule without a per-row detail fetch. Present for every audience
  // (parity with the detail serializer).
  final_subtotal_amount: string | null;
  final_vat_amount: string | null;
  final_total_amount: string | null;
  created_by: number;
  created_by_email: string;
  requested_at: string;
  updated_at: string;
  pricing_proposed_at: string | null;
  customer_decided_at: string | null;
  // Sprint 28 Batch 15.4 — backend now emits routing_decision on
  // every list row so the EW list can render an at-a-glance
  // Instant/Proposal badge per row without a per-row detail fetch.
  routing_decision: RoutingDecision;
  // Sprint 180 §1/§2 — which TRACK this row is on, and the operational
  // ticket(s) it produced.
  //
  // `has_operational_ticket` is the ONE question the two list tracks
  // split on: has a ticket been born from this extra work? It is
  // answered server-side by the canonical FK alone (the same definition
  // the invoice run uses), so the list cannot drift from the money.
  // Present for every audience — a customer is entitled to know their
  // extra work turned into scheduled work.
  has_operational_ticket: boolean;
  spawned_tickets: ExtraWorkSpawnedTicket[];
  // W5-B — the day-by-day series this row belongs to, or NULL for an
  // ordinary standalone work. Null is by far the common case and is
  // what keeps a normal row rendering exactly as it did before series
  // existed: the list reads a null group as "not a series" and changes
  // nothing about the row.
  group: ExtraWorkGroupSummary | null;
  // Sprint 180 §3 — which invoice this work lands on. Not provider-only:
  // the customer picks it on their own create form. NULL — the state
  // nearly every row is in — means "follow the customer's setting", and
  // is a different answer from BUILDING, not a missing one.
  billed_to: ExtraWorkBilledTo | null;
  // M4 — billing month / invoice run. Provider-only (the backend redacts
  // these for CUSTOMER_USER), hence optional.
  invoice_date?: string | null;
  is_invoiced?: boolean;
  invoiced_at?: string | null;
}

// Provider-side pricing line item — full shape with internal note.
// Customer-side reads come back with internal_cost_note omitted.
// Backend per-line pricing-source taxonomy emitted by every line-shape
// serializer under extra_work (cart line, proposal line, ad-hoc pricing
// line). Source of truth:
// backend/extra_work/serializers.py — PRICE_SOURCE_* constants + the
// `_classify_proposal_line_source()` helper + each get_price_source().
//
// Per-line-kind runtime narrowing (the backend never returns values
// outside the listed sets for a given line kind):
//   * ExtraWorkRequestItem (cart line)        -> "CONTRACT" | "NEEDS_PROPOSAL"
//   * ProposalLine (proposal line, persisted) -> "CONTRACT" | "CUSTOM"
//   * ExtraWorkPricingLineItem (free-form)    -> "CUSTOM" only
//
// The union type below carries all three values; the InvoiceLineRow
// component enforces the per-kind subset via its lineKind prop.
export type PriceSource = "CONTRACT" | "CUSTOM" | "NEEDS_PROPOSAL";

export interface ExtraWorkPricingLineItem {
  id: number;
  description: string;
  unit_type: ExtraWorkUnitType;
  quantity: string;
  unit_price: string;
  vat_rate: string;
  subtotal: string;
  vat_amount: string;
  total: string;
  customer_visible_note: string;
  internal_cost_note?: string;
  // Backend serializer emits these on every line shape. For free-form
  // pricing lines (no service FK by construction) `price_source` is
  // always "CUSTOM" and the contract fields are always null. Quoted by
  // backend/extra_work/serializers.py — get_price_source / get_contract_*
  // return PRICE_SOURCE_CUSTOM / None / None unconditionally.
  price_source: PriceSource;
  contract_unit_price: string | null;
  contract_vat_pct: string | null;
  created_at: string;
  updated_at: string;
}

// Sprint 28 Batch 6 — routing decision returned alongside an
// Extra Work create response. `"INSTANT"` means every cart line
// resolved to an active CustomerServicePrice — the proposal phase
// was skipped and operational tickets will be spawned (Batch 7).
// `"PROPOSAL"` means at least one line had no agreed price, so
// the request needs provider review before tickets are created.
export type RoutingDecision = "INSTANT" | "PROPOSAL";

// Sprint 28 Batch 6 — cart line item on an Extra Work request.
// One row per service in the customer's submitted cart.
// `service` is nullable only for legacy backfilled rows from the
// pre-Batch-6 single-line shape; new requests always have a non-
// null service FK. `unit_type` is denormalised from the Service
// at create time so the line stays renderable even if the catalog
// row is later deleted.
export interface ExtraWorkRequestItem {
  id: number;
  service: number | null;
  service_name: string;
  // Sprint 137 item 6 — the CustomerCustomPrice this line was ordered
  // from, or null. Non-null identifies a custom-price line: no catalog
  // service, but a name/unit/amount already agreed with the customer.
  custom_price: number | null;
  // Free-text label for any service-less line. Set by the operator on a
  // free-text ad-hoc line, and stamped from the price row's
  // `custom_name` on a custom-price line — the only label those lines
  // have, since `service_name` is null for both.
  custom_description: string;
  // DRF serialises Decimal as a string to preserve precision.
  quantity: string;
  unit_type: ServiceUnitType;
  requested_date: string;
  customer_note: string;
  // Per-line pricing-source fields. Cart lines have no persisted
  // unit_price of their own; the backend live-resolves the customer's
  // contract row at READ time. Runtime value set for cart lines is
  // strictly {"CONTRACT", "NEEDS_PROPOSAL"} — see
  // backend/extra_work/serializers.py::ExtraWorkRequestItemSerializer
  // .get_price_source.
  price_source: PriceSource;
  contract_unit_price: string | null;
  contract_vat_pct: string | null;
  // Sprint 8A — actual hours worked on an hourly (`unit_type === "HOURS"`)
  // cart line. NULL until a provider enters it at finalize via
  // POST /api/extra-work/<id>/actual-hours/; drives the EW's `final_*`.
  actual_hours: string | null;
  created_at: string;
  updated_at: string;
}

// Mirrors backend `extra_work/serializers.py::ProposalLineAdminSerializer`
// field-list at L1041-1064 verbatim. Persisted line on a Proposal.
// `unit_price` + `vat_pct` are the operator-typed snapshot (NEVER mutated
// on serializer read; see backend module docblock on snapshot rule).
// `line_subtotal` / `line_vat` / `line_total` are backend-computed.
// `price_source` runtime set for proposal lines is strictly
// {"CONTRACT", "CUSTOM"}; classifier at L971-1020 returns those two
// values only.
export interface ProposalLine {
  id: number;
  proposal: number;
  service: number | null;
  service_name: string | null;
  description: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
  // #108 Part B — operator-supplied unit name for a line entered via
  // the composer's "Custom…" unit (unit_type is then OTHER). Blank on
  // every other line. Present on BOTH admin and customer reads.
  custom_unit_label: string;
  unit_price: string;
  vat_pct: string;
  customer_explanation: string;
  // Provider-only. Customer-side ProposalLine reads omit this field
  // (ProposalLineCustomerSerializer drops it). Optional here so a
  // single type works for both reads; consumers MUST NOT rely on
  // truthiness for the visibility decision — backend gating is the
  // source of truth.
  internal_note?: string;
  is_approved_for_spawn: boolean;
  line_subtotal: string;
  line_vat: string;
  line_total: string;
  price_source: PriceSource;
  contract_unit_price: string | null;
  contract_vat_pct: string | null;
  // Sprint 8A-fix — actual hours worked on an hourly proposal line.
  // Read-only; the ProposalLineAdminSerializer already emits it. NULL
  // until a provider enters it at finalize via the actual-hours
  // endpoint (which accepts proposal line ids for a proposal-routed EW).
  actual_hours: string | null;
  created_at: string;
  updated_at: string;
}

// Detail shape — role-aware. Provider-only fields (manager_note,
// internal_cost_note, override_*) are absent on customer responses.
export interface ExtraWorkRequestDetail extends ExtraWorkRequestList {
  description: string;
  category_other_text: string;
  preferred_date: string | null;
  customer_visible_note: string;
  pricing_note: string;
  // Sprint 31 — the customer's declared intent (drives intent-aware
  // workflow labels: an AUTO_START request is not "proposed" to the
  // customer). Serialized on the detail wire; optional for safety.
  request_intent?: ExtraWorkRequestIntent;
  // Provider-only fields — optional because the API strips them
  // for CUSTOMER_USER actors.
  manager_note?: string;
  internal_cost_note?: string;
  override_by?: number | null;
  override_reason?: string;
  override_at?: string | null;
  // M4 — billing month / invoice run (2a). Always emitted on the detail
  // wire for providers (redacted for CUSTOMER_USER); required here to
  // narrow the optional list-row variants inherited from the list type.
  invoice_date: string | null;
  is_invoiced: boolean;
  invoiced_at: string | null;
  pricing_line_items: ExtraWorkPricingLineItem[];
  // Sprint 28 Batch 6 — cart line items + routing decision.
  // `line_items` is always present on responses (empty array for
  // legacy single-line requests that pre-date the cart shape).
  // `routing_decision` is computed by the backend on every detail
  // read.
  line_items: ExtraWorkRequestItem[];
  routing_decision: RoutingDecision;
  // Sprint 8A — final billable amounts. NULL until actual hours are
  // entered on hourly lines (or frozen at customer approval). Recomputed
  // by POST /api/extra-work/<id>/actual-hours/ and visible to the
  // customer per SoT §5.12.
  final_subtotal_amount: string | null;
  final_vat_amount: string | null;
  final_total_amount: string | null;
  allowed_next_statuses: ExtraWorkStatus[];
  // Per-current-user, per-EW capability block — backend
  // `ExtraWorkRequestDetailSerializer.get_actions`. Optional so older
  // list responses don't break typing; treat absent as all-false.
  actions?: ExtraWorkActions;
  // Sprint 128 §0 — whether the labels are frozen by a live ISSUED invoice
  // (so the relabel UI renders read-only-with-reason). `labels_locked_invoice`
  // is the invoice NUMBER, or null (Sprint 129 §2b: an issued-but-unsent
  // invoice has no number yet — the frontend picks the wording, no prose on
  // the wire). Detail only — the list serializer omits it to avoid an N+1.
  labels_locked?: boolean;
  labels_locked_invoice?: string | null;

  // ---- W2-D planning layer, consumed by W3-F -------------------------
  // PROVIDER-ONLY on the wire: the backend strips all four for a
  // CUSTOMER_USER (`ExtraWorkRequestDetailSerializer._PROVIDER_ONLY_FIELDS`
  // — "a customer must never see the budget, who is doing what for how
  // long, or whether we are over our own estimate"). Optional here for
  // exactly that reason: absent is a real, expected shape, not a legacy
  // one, and the UI must key on the role check rather than on truthiness.
  /** Decimal string, e.g. "8.00". The planning number. NEVER a price. */
  budget_hours?: string | null;
  planned_hours?: ExtraWorkPlannedHoursRow[];
  /** Decimal string — the sum of `planned_hours`, computed server-side. */
  planned_hours_total?: string;
  /** Present and non-null ONLY when the distribution exceeds the budget.
   *  A warning the read surface carries so the manager approving the
   *  work sees the overrun on the screen they approve from. */
  planned_hours_overrun?: ExtraWorkHoursOverrun | null;
  /** The two completion requirements, set at plan time, both default
   *  off. NOT provider-only — they are a promise about the evidence the
   *  customer will get, not a number about our own people. */
  file_upload_required?: boolean;
  completion_notes_required?: boolean;
  /** W13 — the CUSTOMER's own asks, set when they raised the request.
   *  A second origin for the same requirement, deliberately kept apart
   *  from the provider pair above so neither side erases the other's.
   *  The completion gate requires whatever either side asked for. */
  customer_requires_photo?: boolean;
  customer_requires_note?: boolean;
  /** The window WE committed to. Separate stored values from the
   *  customer's `preferred_date` / `planned_end_date` / `deadline`, and
   *  the plan endpoint never touches those. */
  provider_planned_date?: string | null;
  provider_planned_end_date?: string | null;
}

/** W2-D — one person's share of the budget.
 *
 *  `is_assigned` false means the person was planned hours and has since
 *  been taken off the work. The row STAYS in the list and stays in the
 *  total, deliberately: the reference system builds its grid from the
 *  assignment list instead, so hours belonging to a removed worker
 *  vanish from the screen while still counting in every total, and the
 *  screen and the total disagree with nothing on screen to explain it. */
export interface ExtraWorkPlannedHoursRow {
  user_id: number;
  user_email: string;
  user_full_name: string;
  user_role: string;
  /** W6-H — the day these hours are planned for, or NULL for "planned,
   *  day not decided". NULL is a supported state, not a missing value:
   *  every row written before W6-H has it, and a job whose window is
   *  not set yet still plans hours. Render it as its own state, never
   *  as a blank cell that reads like a gap. */
  date: string | null;
  /** W7 — WHICH KIND OF HOUR, from the `timesheets.HourType` catalog the
   *  ACTUALS already use. NULL means ORDINARY hours: every row written
   *  before W7 has it, and it is the right answer for an operator who
   *  does not split the day. The name rides along so a grid can label
   *  the row without a second request; it is null exactly when the id
   *  is, and the CLIENT owns the wording for that case. */
  hour_type: number | null;
  hour_type_name: string | null;
  /** Decimal string, e.g. "4.00". Zero is legal and means "on the crew,
   *  no hours budgeted yet" — dropping the row to say so would lose the
   *  fact that they are on the job. */
  hours: string;
  is_assigned: boolean;
  set_at: string;
}

/** W2-D — the overrun body, from `planning.hours_overrun`. Every figure
 *  is a decimal STRING of HOURS. Nothing here is money and nothing here
 *  goes near `rowAmounts()`. */
export interface ExtraWorkHoursOverrun {
  code: string;
  budget_hours: string;
  distributed_hours: string;
  over_by: string;
}

/** The plan payload, for `POST /extra-work/<id>/plan/` and
 *  `POST /extra-work/bulk-plan/`.
 *
 *  EVERY FIELD IS OPTIONAL AND ABSENCE MEANS "LEAVE IT ALONE" — the
 *  backend reads this payload by KEY PRESENCE, including the two
 *  booleans. That is why the client must OMIT a field it did not
 *  collect rather than send a default: sending `file_upload_required:
 *  false` because a dialog did not ask about it is precisely the
 *  reference system's defect, where 0 of 78 live records has either
 *  flag set because every write path silently discarded them.
 *
 *  BOTH ENDPOINTS ARE PINNED TO `JSONParser` AND ANSWER 415 TO FORM
 *  DATA, on purpose: DRF reads an absent boolean out of form input as
 *  `false`, which would wipe both flags on every work in a bulk plan.
 *  axios serialises a plain object as JSON, which is what these calls
 *  send. */
export interface ExtraWorkPlanPayload {
  budget_hours?: string | null;
  provider_planned_date?: string | null;
  provider_planned_end_date?: string | null;
  /** W6-H — one cell of the day grid. `date` omitted or null means
   *  "planned, day not decided", which is what every pre-W6-H client
   *  keeps sending and what the bulk table still sends. */
  planned_hours?: {
    user: number;
    date?: string | null;
    /** W7 — omitted or null means ORDINARY hours, which is what every
     *  pre-W7 client keeps sending. */
    hour_type?: number | null;
    hours: string;
  }[];
  file_upload_required?: boolean;
  completion_notes_required?: boolean;
  /** Absent means START — plan and start are one action. Send `false`
   *  to plan without starting. */
  start?: boolean;
}

/** What a plan write reports back, on the `plan` key of the detail
 *  response. `warnings` carries the hours overrun; a `started` of false
 *  with a `start_skipped` code is a NORMAL outcome (the work already has
 *  an operational ticket driving its status), not a failure. */
export interface ExtraWorkPlanResult {
  warnings: ExtraWorkHoursOverrun[];
  started: boolean;
  start_skipped: string | null;
  tickets_moved: number[];
  tickets_kept_own_date: number[];
}

/** W5-B — when a work happens relative to the handover ("oplevering").
 *
 *  NULL is a real value and means NOBODY WAS ASKED — which is the state
 *  of every ordinary ad-hoc work, and a different fact from "at
 *  handover". The reference system cannot express the difference: its
 *  server does `match($entry['condition'] ?? 'at')`, so an unanswered
 *  slot and an explicit one are the same five characters afterwards.
 *
 *  A REAL COLUMN here. Over there the value is never persisted at all —
 *  it is baked into the title string and every reader recovers it with
 *  a regex, which is why two incompatible suffix formats now coexist in
 *  their data and the parser understands only one of them. Never derive
 *  this from a title. */
export type ExtraWorkCondition =
  | "AT_HANDOVER"
  | "BEFORE_HANDOVER"
  | "AFTER_HANDOVER";

/** W5-B — one picked day/time/condition on the multi-date create form.
 *  `time` and `condition` are both optional and both meaningful when
 *  absent: no time is not midnight, no condition is not "at handover". */
export interface ExtraWorkSlot {
  /** ISO date, `YYYY-MM-DD`. */
  date: string;
  /** `HH:MM`, or omitted. */
  time?: string | null;
  condition?: ExtraWorkCondition | null;
}

/** W5-B — the series summary carried on every list row.
 *
 *  WHOLE-SERIES TRUTH, not page truth: `member_count` and
 *  `status_counts` describe every member, including ones on another
 *  page of results. That is what lets the list fold a series into one
 *  row without the server inventing a header record — the reference
 *  system marks `group_sequence == 1` as a header and branches its
 *  status filter on it, which is why its list totals and its own
 *  statistics endpoint disagree. */
export interface ExtraWorkGroupSummary {
  id: number;
  standard_title: string;
  member_count: number;
  status_counts: { status: ExtraWorkStatus; count: number }[];
}

/** W5-B — one member, as the group editor reads it. */
export interface ExtraWorkGroupMember {
  extra_work: number;
  title: string;
  status: ExtraWorkStatus;
  building_name: string;
  preferred_date: string | null;
  /** `HH:MM:SS` or null. Null is "no time given", not midnight. */
  scheduled_time: string | null;
  condition: ExtraWorkCondition | null;
  group_sequence: number | null;
  provider_planned_date: string | null;
  /** Decimal string, or null for "nobody has budgeted this". */
  budget_hours: string | null;
}

export interface ExtraWorkGroupDetail {
  group: ExtraWorkGroupSummary & { customer: number; building: number };
  members: ExtraWorkGroupMember[];
}

/** W5-B — one row of a group-editor save.
 *
 *  KEY PRESENCE, like the plan payload: absent leaves the value alone,
 *  present-and-null clears it. Only the three things that are neither a
 *  workflow transition nor a planning value live here — date, budget
 *  hours and assigned people go through `bulk-plan` and `bulk-assign`,
 *  which already take per-work values. There is no third planning
 *  path. */
export interface ExtraWorkGroupMemberEdit {
  extra_work: number;
  title?: string;
  scheduled_time?: string | null;
  condition?: ExtraWorkCondition | null;
  /** Recompose the title from this member's COLUMNS after the edits
   *  above land. One direction only; the old title is never read. */
  regenerate_title?: boolean;
}

/** W4-O — ONE work's own plan inside a bulk call.
 *
 *  A row is an `ExtraWorkPlanPayload` with an id bolted on and nothing
 *  else, mirroring the backend's `_BulkPlanItemSerializer`, which is
 *  `ExtraWorkPlanSerializer` plus `request`. Extending the payload type
 *  rather than restating its fields is what stops "what may a row set"
 *  from drifting away from "what may a plan set". */
export interface ExtraWorkBulkPlanItem extends ExtraWorkPlanPayload {
  request: number;
}

/** W4-O — the bulk-plan body, in either of its two spellings.
 *
 *  A UNION, not an object with two optional halves, because the server
 *  refuses a mixture outright: `items` beside a shared field would need
 *  a precedence rule ("does the row's budget beat the shared one?"),
 *  and a precedence rule is a thing an operator has to learn and a
 *  client can get wrong in silence. The union makes the mixture
 *  unspellable here rather than a 400 discovered at runtime.
 *
 *  The shared spelling is not a second endpoint: the server normalises
 *  it into the per-work list it is shorthand for. It stays because
 *  `bulk-dates` and `bulk-assign` speak it too, and because "the same
 *  window on all six" should be sayable once rather than copied six
 *  times — the fifth copy being subtly different is the data-entry
 *  failure the endpoint exists to prevent. */
export type ExtraWorkBulkPlanPayload =
  | ({ requests: number[] } & ExtraWorkPlanPayload)
  | { items: ExtraWorkBulkPlanItem[] };

/** W4-O — one person currently assigned to a work, as the bulk planning
 *  context reports them. Distinct from `ExtraWorkPlannedHoursRow`: this
 *  is who is ON the job, that is who has HOURS on it, and the two lists
 *  deliberately do not have to match (see `is_assigned` there). */
export interface ExtraWorkBulkPlanCrewMember {
  user_id: number;
  user_email: string;
  user_full_name: string;
  user_role: string;
  assignment_role: string;
}

/** W4-O — what one selected work plans RIGHT NOW.
 *
 *  A per-work table has to be seeded or every row opens blank and
 *  saving looks like it wiped what was there. The list payload carries
 *  none of these fields (they are provider-only detail fields) and none
 *  of the crew, so this is the read that fills the table — the whole
 *  selection in one request rather than one detail fetch per row. */
export interface ExtraWorkBulkPlanContextRow {
  extra_work: number;
  title: string;
  building_name: string;
  status: ExtraWorkStatus;
  /** Decimal string, or null for "nobody has budgeted this yet". Those
   *  are different facts from "0.00", and the dialog must not render
   *  them the same. */
  budget_hours: string | null;
  provider_planned_date: string | null;
  provider_planned_end_date: string | null;
  /** What the CUSTOMER asked for. Read-only context: a plan never
   *  writes these, and setting our window without seeing the deadline
   *  it is measured against is planning blind. */
  preferred_date: string | null;
  deadline: string | null;
  file_upload_required: boolean;
  completion_notes_required: boolean;
  crew: ExtraWorkBulkPlanCrewMember[];
  planned_hours: ExtraWorkPlannedHoursRow[];
  planned_hours_total: string;
  planned_hours_overrun: ExtraWorkHoursOverrun | null;
}

export interface ExtraWorkBulkPlanContext {
  works: ExtraWorkBulkPlanContextRow[];
}

/** The bulk-plan reply. One entry per work, in id order. */
export interface ExtraWorkBulkPlanResult {
  updated: number;
  results: {
    extra_work: number;
    warnings: ExtraWorkHoursOverrun[];
    started: boolean;
    start_skipped: string | null;
  }[];
  tickets_moved: number[];
  tickets_kept_own_date: number[];
}

// Mirrors backend `extra_work/serializers.py::ExtraWorkRequestDetailSerializer.get_actions`.
// `can_view_pricing` is the EW-level pricing-visibility key (Proposal
// uses the parallel `can_view_proposal_pricing` — different spelling
// because they're separate read concerns on different resources).
// `can_override_customer_decision` is tightened to current-record:
// True only when authority holds AND status == PRICING_PROPOSED.
export interface ExtraWorkActions {
  allowed_next_statuses: ExtraWorkStatus[];
  can_prepare_extra_work_proposal: boolean;
  can_override_customer_decision: boolean;
  // Sprint 31 — AUTO_START "Start work": provider may start a
  // PRICING_PROPOSED request created with AUTO_START_AFTER_PRICING
  // without customer approval or an override reason (pre-authorized).
  // Optional so older responses (pre-31) typecheck as absent/false.
  can_auto_start?: boolean;
  can_view_pricing: boolean;
  can_view_proposal_pdf: boolean;
  can_approve: boolean;
  can_reject: boolean;
  // M1 B6 — EW message thread posting flags (the composer offers only the
  // tiers the backend will accept). Optional so older responses typecheck.
  can_post_ew_public_reply?: boolean;
  can_post_ew_internal_note?: boolean;
  can_post_ew_customer_internal?: boolean;
}

// M1 B6 — Extra Work message thread (mirrors TicketMessageType MINUS the two
// staff tiers; EW has no staff dimension).
export type EwMessageType =
  | "PUBLIC_REPLY"
  | "INTERNAL_NOTE"
  | "CUSTOMER_INTERNAL";

export type EwMessageVisibility = "NORMAL" | "RESTRICTED";

export interface EwMessage {
  id: number;
  extra_work: number;
  author: number | null;
  author_email: string;
  message: string;
  message_type: EwMessageType;
  directed_to: number[];
  directed_to_detail: { id: number; full_name: string }[];
  visibility_mode: EwMessageVisibility;
  created_at: string;
}

// M1 B6 — a valid directed_to target for the EW composer picker, from
// GET /api/extra-work/<id>/message-recipients/. Side-aware by caller; no
// email (EW has no staff side, so `side` is provider | customer).
export interface EwMessageRecipient {
  id: number;
  full_name: string;
  side: "provider" | "customer";
}

// Sprint 28 Batch 6 — cart-shaped POST payload for /extra-work/.
// Replaces the single-line CreateExtraWorkPayload shape on the
// client side. The backend keeps the existing parent fields and
// adds `line_items` as the authoritative cart.
export interface ExtraWorkRequestCartCreatePayload {
  /** Sprint 174 §1 — the planned window's end and the deadline. Sprint
   *  173 added both fields and no form offered them, so every record
   *  was created with them empty. */
  planned_end_date?: string | null;
  deadline?: string | null;
  title: string;
  description: string;
  building: number;
  customer: number;
  // Sprint 144 §1 — `category` (the fixed `ExtraWorkCategory` enum) is
  // now OPTIONAL on the wire and the create form no longer sends it: the
  // column keeps its server-side `default=OTHER`. It stays on the type
  // for API back-compat and for any caller that still classifies with
  // the enum. `category_other_text` follows it.
  category?: string;
  category_other_text?: string;
  // Sprint 144 §1 — what the form actually sends now: AT MOST ONE. A
  // company `ServiceCategory`, or this customer's `CustomerPriceFolder`.
  service_category?: number | null;
  price_folder?: number | null;
  // Sprint 128 — optional per-customer labels the customer may set at
  // create (both optional; the backend enforces they belong to `customer`).
  department?: number | null;
  work_type?: number | null;
  urgency: string;
  preferred_date?: string | null;
  // Sprint 5 (frontend) — the create page now sends the customer's
  // chosen INTENT (driven by the preview endpoint's `allowed_intents`
  // / `default_intent`). Optional: the backend derives a safe default
  // (`derive_default_intent`) when omitted, so older callers and the
  // graceful-degradation path (preview unavailable) stay valid.
  request_intent?: ExtraWorkRequestIntent;
  // Sprint 180 §3 — which invoice this work lands on. Omitted and null
  // mean the same thing to the server (Sprint 182 §6 removed the
  // BUILDING default outright): follow the customer's setting.
  billed_to?: ExtraWorkBilledTo | null;
  // Each line is either a catalog service (`service`) OR a free-text
  // custom line (`custom_description`) — XOR, the create form guarantees
  // exactly one is set. A custom line carries no `service`; the backend
  // treats it as needs-provider-pricing and routes the request to a
  // proposal. Mirrors the cart-create line serializer + the preview
  // line serializer (both accept service XOR custom_description).
  line_items: Array<{
    service?: number;
    custom_description?: string;
    // Sprint 137 item 6 — a per-customer CustomerCustomPrice ordered
    // as a cart line. Third mutually-exclusive alternative alongside
    // `service` and `custom_description`; the backend snapshots the
    // row's name / unit / amount onto the line and classifies it
    // AD_HOC (so routing is unchanged).
    custom_price?: number;
    // Decimal as string per DRF convention.
    quantity: string;
    // W-EW1 §2 — REMOVED from the wire on purpose. The server stamps
    // every line's `requested_date` from the request-level
    // `preferred_date`, and a line that still carries one is refused
    // with `line_requested_date_not_accepted`. The column and the READ
    // type (`ExtraWorkRequestItem.requested_date`) are unchanged.
    customer_note?: string;
  }>;
}

// ---------------------------------------------------------------------------
// Sprint 127/128 — per-customer Extra Work label lists. Department and
// WorkType are identical in shape (one backend abstract base); mounted at
// /api/customers/<id>/departments/ and /work-types/. Pure labels — no
// state machine, no permissions of their own.
// ---------------------------------------------------------------------------
export interface CustomerLabel {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
}
export type Department = CustomerLabel;
export type WorkType = CustomerLabel;

// ---------------------------------------------------------------------------
// Sprint 5 (frontend) — Extra Work create INTENT layer + non-mutating
// cart preview (POST /extra-work/preview/). Mirrors
// backend/extra_work/{models,classification,serializers,views}.py. The
// frontend MUST NOT re-derive intent eligibility — the preview's
// backend-gated `allowed_intents` / `default_intent` is the authority
// (SoT §11.4).
// ---------------------------------------------------------------------------

// The customer/provider's declared intent for a cart at create time.
// Distinct from the per-line price source and the parent's
// `routing_decision`. Wire values mirror backend `ExtraWorkRequestIntent`.
export type ExtraWorkRequestIntent =
  | "DIRECT_AGREED_PRICE_ORDER"
  | "AUTO_START_AFTER_PRICING"
  | "REQUEST_QUOTE";

// Per-line price classification returned by the PREVIEW endpoint. This
// is a DIFFERENT vocabulary from the persisted-line `PriceSource`
// (CONTRACT / CUSTOM / NEEDS_PROPOSAL): preview speaks the
// `ExtraWorkLinePriceSource` enum.
//   * AGREED_CUSTOMER_PRICE  — resolved to the customer's OWN contract
//     price; `agreed_unit_price` + `agreed_vat_pct` are populated.
//   * NEEDS_PROVIDER_PRICING — catalog service with no agreed price.
//   * AD_HOC                 — free-text line (no service FK).
// Provider DEFAULT prices are NEVER returned — only the customer's own
// agreed price, and only on AGREED_CUSTOMER_PRICE lines.
export type ExtraWorkPreviewPriceSource =
  | "AGREED_CUSTOMER_PRICE"
  | "NEEDS_PROVIDER_PRICING"
  | "AD_HOC";

// Coarse actor classification echoed by the preview endpoint. Surfaced
// for completeness; intent eligibility comes from `allowed_intents`,
// never re-derived from this.
export type ExtraWorkPreviewActorKind =
  | "PROVIDER"
  | "STAFF"
  | "CUSTOMER_USER"
  | "CUSTOMER_LOCATION_MANAGER"
  | "CUSTOMER_COMPANY_ADMIN";

// Stable intent-rejection codes from the backend intent validator
// (backend/extra_work/classification.py). The PREVIEW endpoint returns
// these reliably in `requested_intent_error.code`. (On the CREATE
// endpoint the same rejection arrives as a `request_intent` field
// error whose stable code is NOT serialized on the wire — DRF drops
// `ErrorDetail.code` — so the preview surface is the reliable code
// source.)
export type ExtraWorkIntentErrorCode =
  | "intent_requires_all_agreed"
  | "intent_requires_non_agreed_line"
  | "intent_forbidden_for_role"
  | "intent_forbidden_for_provider"
  | "intent_required";

// One draft cart line sent to the preview endpoint. `service` XOR
// `custom_description` (mirrors `ExtraWorkPreviewLineSerializer`).
export interface ExtraWorkPreviewLinePayload {
  service?: number | null;
  custom_description?: string;
  // Sprint 137 item 6 — order a per-customer CustomerCustomPrice. A
  // line carries exactly ONE of service / custom_description /
  // custom_price; sending more than one is a 400 with code
  // `line_requires_service_or_description`.
  custom_price?: number | null;
  // Decimal as string per DRF convention.
  quantity: string;
  // W-EW1 §2 — optional. The preview takes the cart's one date from
  // the payload-level `preferred_date` and applies it to every line,
  // so the previewed amount is priced on the same day create stores.
  requested_date?: string;
  customer_note?: string;
}

// Request body for POST /extra-work/preview/.
export interface ExtraWorkPreviewPayload {
  building: number;
  customer: number;
  // Optional candidate intent. When present the response carries
  // `requested_intent_allowed` (+ `requested_intent_error` on rejection).
  request_intent?: ExtraWorkRequestIntent | null;
  // W-EW1 §2 — the cart's one date, mirroring the create payload.
  preferred_date?: string | null;
  line_items: ExtraWorkPreviewLinePayload[];
}

// One classified line in the preview response. Decimal-as-string per
// DRF convention; `agreed_*` are null on non-agreed lines.
export interface ExtraWorkPreviewLine {
  index: number;
  service: number | null;
  custom_description: string;
  requested_date: string;
  quantity: string;
  price_source: ExtraWorkPreviewPriceSource;
  service_name: string;
  service_category_name: string;
  agreed_unit_price: string | null;
  agreed_vat_pct: string | null;
  // Sprint 137 item 6 — set only on a line ordered from a
  // CustomerCustomPrice. The line's `price_source` stays AD_HOC (a
  // custom price is not a contract price and never routes INSTANT),
  // but its amount IS known, so it is returned instead of leaving the
  // row as "to be priced by the provider".
  custom_price: number | null;
  custom_price_unit_price: string | null;
  custom_price_vat_pct: string | null;
}

// Cart-level classification booleans.
export interface ExtraWorkPreviewCart {
  all_agreed: boolean;
  has_non_agreed: boolean;
  has_ad_hoc: boolean;
}

// Response body for POST /extra-work/preview/. The `requested_intent*`
// fields are present only when the request carried `request_intent`.
export interface ExtraWorkPreviewResponse {
  customer: number;
  building: number;
  actor_kind: ExtraWorkPreviewActorKind;
  lines: ExtraWorkPreviewLine[];
  cart: ExtraWorkPreviewCart;
  allowed_intents: ExtraWorkRequestIntent[];
  default_intent: ExtraWorkRequestIntent;
  requested_intent?: ExtraWorkRequestIntent;
  requested_intent_allowed?: boolean;
  requested_intent_error?: {
    code: ExtraWorkIntentErrorCode | string;
    detail: string;
  };
}

// Sprint 28 Batch 15.4 — minimal frontend shape for a Proposal row.
// Mirrors `extra_work.serializers.ProposalListSerializer`. The full
// admin-facing builder UI (line items, transitions, timeline) is a
// future deliverable; the detail page only needs enough shape to
// pick the active proposal for the PDF-download button.
// Source of truth: backend/extra_work/models.py::ProposalStatus.
// Backend uses CUSTOMER_APPROVED / CUSTOMER_REJECTED (not the shorter
// ACCEPTED / REJECTED that earlier drafts of this file carried).
export type ProposalStatus =
  | "DRAFT"
  | "SENT"
  | "CUSTOMER_APPROVED"
  | "CUSTOMER_REJECTED"
  | "CANCELLED";

export interface Proposal {
  id: number;
  extra_work_request: number;
  status: ProposalStatus;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
  sent_at: string | null;
  customer_decided_at: string | null;
  created_at: string;
  // Per-current-user, per-proposal capability block — backend
  // `ProposalDetailSerializer.get_actions`. Optional because the list
  // serializer omits it; detail responses always carry it.
  actions?: ProposalActions;
}

// Detail shape — extends the lean `Proposal` (which mirrors the LIST
// serializer) with the nested `lines` array surfaced by
// `extra_work.serializers.ProposalDetailSerializer.get_lines`. The
// detail response is role-aware: provider operators receive
// ProposalLineAdminSerializer rows (carry `internal_note`), customers
// receive ProposalLineCustomerSerializer rows (omit `internal_note`).
// The optional `internal_note` on ProposalLine reflects this — its
// presence on the typed object is the role discriminator, not a
// truthiness check on the value.
//
// Other detail-only fields (override_by/override_reason/override_at,
// allowed_next_statuses, created_by/_email) are present on the wire
// but not consumed by the frontend yet; left out so the type honestly
// reflects what we use.
export interface ProposalDetail extends Proposal {
  lines: ProposalLine[];
  /** Sprint 187 §2a — non-empty ONLY on the create response, and only
   *  when the parent Extra Work was still REQUESTED and this actor was
   *  not permitted to move it to UNDER_REVIEW. The proposal was still
   *  created; this is the reason Send will refuse it, so the builder can
   *  say so instead of hiding the button. Absent on every read. */
  parent_advance_blocked?: string;
}

// Mirrors backend `extra_work/serializers.py::ProposalDetailSerializer.get_actions`.
// `can_view_proposal_pricing` (and the parallel `can_view_proposal_pdf`)
// remain TRUE for an assigned BM whose
// `osius.building_manager.prepare_extra_work_proposal` is revoked —
// only mutation actions flip False.
export interface ProposalActions {
  allowed_next_statuses: ProposalStatus[];
  can_view_proposal_pricing: boolean;
  can_view_proposal_pdf: boolean;
  can_edit_lines: boolean;
  can_send: boolean;
  can_cancel: boolean;
  can_approve: boolean;
  can_reject: boolean;
  // Direct-publish (DRAFT proposal → SENT → CUSTOMER_APPROVED).
  //
  // Sprint 187 §3 — now mirrors ALL FOUR of the endpoint's gates, not
  // two. The two it was missing are the reason this button used to fail
  // by default rather than as an edge case:
  //   * the DEDICATED dangerous grant `provider.extra_work.
  //     quote_override_start`, which is OFF by default and which the
  //     generic B6 override key does NOT satisfy (H-11);
  //   * `request_intent == REQUEST_QUOTE`, since the other two intents
  //     have no customer-decision step to bypass.
  // See backend/extra_work/views_proposals.py — the endpoint's own
  // checks remain the authority; this flag only reports them.
  can_direct_publish: boolean;
}

export interface ExtraWorkStatusHistoryEntry {
  id: number;
  old_status: ExtraWorkStatus;
  new_status: ExtraWorkStatus;
  changed_by_email: string | null;
  note: string;
  is_override: boolean;
  created_at: string;
}

export interface CompanyAdminMembership {
  id: number;
  company: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  // Sprint 154 §K — `User.phone`; see UserAdmin.phone.
  user_phone: string;
  user_role: Role;
  created_at: string;
}

export interface BuildingManagerMembership {
  id: number;
  building: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  user_role: Role;
  assigned_at: string;
  // B6 — per-(BM, building) override map for the two BM-revocable
  // osius.* keys (`osius.building_manager.override_customer_decision`,
  // `osius.building_manager.prepare_extra_work_proposal`). Absent key
  // = backend default (True for BM in scope); explicit `false` narrows
  // the default for this building. Source of truth: backend
  // `buildings/serializers_memberships.py`
  // (BuildingManagerAssignmentSerializer.fields).
  permission_overrides: Record<string, boolean>;
}

// Sprint 31 — frontend mirror of backend
// `accounts.permissions_v2.BM_REVOCABLE_PERMISSION_KEYS`. The PATCH
// surface
// (`buildings/serializers_memberships.py::BuildingManagerAssignmentUpdateSerializer`)
// rejects any other key with a 400 to prevent scope-bleed via the
// override map, so this list is the closed set the UI may toggle.
// Keep in lockstep with the backend frozenset; adding a key here
// without updating the backend will simply 400.
export const BM_REVOCABLE_PERMISSION_KEYS = [
  "osius.building_manager.prepare_extra_work_proposal",
  "osius.building_manager.override_customer_decision",
] as const;
export type BmRevocablePermissionKey =
  (typeof BM_REVOCABLE_PERMISSION_KEYS)[number];

export interface CustomerUserMembership {
  id: number;
  customer: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  // Sprint 154 §K — `User.phone`; see UserAdmin.phone.
  user_phone: string;
  user_role: Role;
  // SoT Addendum A.1 — company-wide Customer Company Admin flag. A
  // membership with `is_company_admin: true` is CCA across ALL of the
  // customer's buildings (no per-building access rows). READ-ONLY on
  // the wire; toggle it via `setCustomerCompanyAdmin`
  // (POST/DELETE `.../users/<uid>/company-admin/`). Gating the make/
  // remove control on `actions.can_manage_customer_company_admins`.
  is_company_admin: boolean;
  created_at: string;
  // Per-row capability block — same shape as `Customer.actions`,
  // computed against `request.user` + this membership's parent
  // customer. Surfacing it per-row keeps the existing paginated
  // {count, next, previous, results} envelope unchanged.
  actions?: CustomerActions;
}

// Sprint 28 Batch 4 — Contact phone-book entries.
//
// A Contact is a communication-only person attached to a Customer
// (optionally narrowed to a single Building). It is NOT a User:
//   - no password, no login
//   - no UserRole enum
//   - no scope memberships or permission overrides
//   - no last_login / is_active fields
// See `docs/product/requirements-meeting-2026-05-15.md` §1
// (Contacts vs Users are distinct entities). Promoting a Contact into a
// User is an explicit, separate flow — `promoteCustomerContact`
// (POST .../promote-to-user/), which the backend resolves to INVITE or
// LINK mode. A plain create/edit NEVER sets `user`.
//
// Backend serializer: `customers/serializers_contacts.py` (ContactSerializer).
// Backend permission: SUPER_ADMIN or COMPANY_ADMIN for the customer's provider.
export type ContactPromotionStatus = "none" | "invited" | "linked";

export interface Contact {
  id: number;
  customer: number;
  building: number | null;
  full_name: string;
  email: string;
  phone: string;
  role_label: string;
  notes: string;
  // Sprint 12B — contact taxonomy + the promote-to-user bridge.
  contact_type: string;
  /** Sprint 185 §2 — send this person the invoice. Separate from
   *  `contact_type === "BILLING"`: that says what they do, this says
   *  what they receive. */
  receives_invoices: boolean;
  is_primary: boolean;
  // `user` is the read-only FK set ONLY by the promote/link flow (null
  // until promoted). `promotion_status` is server-computed:
  //   "none"    — phone-book only, not yet a user (show the promote CTA)
  //   "invited" — a pending invitation exists for this contact
  //   "linked"  — a User exists and is linked (Contact.user is set)
  // `linked_building_ids` is the contact's current building-link set,
  // used to pre-fill the promote modal's building selection.
  user: number | null;
  linked_building_ids: number[];
  promotion_status: ContactPromotionStatus;
  created_at: string;
  updated_at: string;
}

export interface ContactCreatePayload {
  building?: number | null;
  // Write-only multi-building set (replaces the ContactBuildingLink set on
  // the backend). Sending [] clears all links; preferred over the legacy
  // single `building` FK. Read back via Contact.linked_building_ids.
  building_ids?: number[];
  full_name: string;
  email?: string;
  phone?: string;
  role_label?: string;
  notes?: string;
  /** Sprint 185 §2 — mark this contact as an invoice recipient. */
  receives_invoices?: boolean;
}

// PATCH semantics — every field optional.
export type ContactUpdatePayload = Partial<ContactCreatePayload>;

// Sprint 12B — promote a Contact to a customer User. All fields optional;
// the BACKEND decides INVITE vs LINK by whether a User already exists for
// the contact's email. A valid NL phone is REQUIRED (body.phone, else the
// contact's stored phone).
export interface PromoteContactPayload {
  access_role?: CustomerAccessRole;
  building_ids?: number[];
  phone?: string;
}

export interface PromoteContactResponse {
  // Mode is BACKEND-decided (the client never chooses):
  //   "invited" — no matching User -> 201, carries `invitation_id`.
  //   "linked"  — matching active CUSTOMER_USER -> 200, carries `user_id`.
  mode: "invited" | "linked";
  invitation_id?: number;
  user_id?: number;
  detail?: string; // e.g. "already_invited" on a re-promote
  contact: Contact;
}

// ---------------------------------------------------------------------------
// Sprint 28 Batch 5 — Service catalog (per provider company since Sprint 142)
// + per-customer pricing
// ---------------------------------------------------------------------------
//
// A `ServiceCategory` groups related `Service` rows (e.g. "Deep cleaning",
// "Window cleaning"). A `Service` is the catalog entry the provider offers,
// with a *reference* default price/VAT used for display only. The instant-
// ticket gate consults `CustomerServicePrice` rows exclusively — the
// `default_unit_price` on Service is NOT the resolver fallback.
//
// Pricing resolver order (decided by the master plan, frontend just renders):
//   1. Active CustomerServicePrice for (customer, service) → use it.
//   2. Otherwise → no agreed price; proposal phase required.
//
// Backend serializers live under `backend/services/serializers*.py` and
// `backend/customers/serializers_pricing.py`. Permission gate on every
// catalog + pricing endpoint: SUPER_ADMIN or COMPANY_ADMIN of the customer's
// provider company. CUSTOMER_USER, STAFF, BUILDING_MANAGER never reach them.

// Unit type vocabulary mirrors the backend `ExtraWorkPricingUnitType`
// enum already used by Extra Work proposal line items. The 2026-05-15
// meeting (§5) uses the labels HOURLY / PER_SQM / FIXED / PER_ITEM —
// those map onto the storage values HOURS / SQUARE_METERS / FIXED / ITEM.
// OTHER is the historical catch-all and is kept for parity with
// `ExtraWorkUnitType`.
export type ServiceUnitType =
  | "HOURS"
  | "SQUARE_METERS"
  | "FIXED"
  | "ITEM"
  | "OTHER";

export interface ServiceCategory {
  id: number;
  // Sprint 142 — categories are per provider company, like the services
  // under them. Optional on the wire on CREATE (a COMPANY_ADMIN's
  // frontend omits it and the backend defaults to their own company),
  // read-only on UPDATE — re-pinning would strand every Service inside
  // it in a category their own company cannot see.
  company: number;
  company_name: string;
  name: string;
  description: string;
  is_active: boolean;
  // Sprint 138 §2 — how many services this category holds, so the UI
  // can decide which actions to OFFER instead of offering all of them
  // and letting the operator discover which ones 400. `Service.category`
  // is PROTECT and NOT nullable, so a category holding ANY service is
  // permanently undeletable: Delete is offered only at service_count 0.
  // `active_service_count` is what the cascade-archive confirmation
  // counts. Both are scoped to the catalog the actor can see.
  service_count: number;
  active_service_count: number;
  created_at: string;
  updated_at: string;
}

// Sprint 138 §2a — result of POST /services/categories/<id>/archive/
// (or /unarchive/). Named for what ACTUALLY happened: an unarchive
// deactivates nothing and reports how many services stayed archived.
export interface ServiceCategoryArchiveResult {
  category: ServiceCategory;
  deactivated_service_count: number;
  // Sprint 142 removed `affected_company_count`. It existed because a
  // GLOBAL category could hold several providers' services, so archiving
  // one reached all of them. A category belongs to one company now and
  // its services must belong to that same company, so the number could
  // only ever be 0 or 1 — a "this touched N providers" warning that can
  // never fire. Do not re-add it, and do not reintroduce the warning
  // branch that read it.
  still_archived_service_count: number;
}

export interface ServiceCategoryCreatePayload {
  name: string;
  description?: string;
  is_active?: boolean;
  // Sprint 142 — only a SUPER_ADMIN needs to send this (and MUST, when
  // more than one provider Company exists). A COMPANY_ADMIN omits it and
  // the backend resolves their own company.
  company?: number;
}

export type ServiceCategoryUpdatePayload = Partial<ServiceCategoryCreatePayload>;

// Sprint 123 — a provider-company-scoped managed unit for unit_type=OTHER
// pricing lines, replacing ad-hoc free-text retyping. `company` is
// optional on the wire on CREATE (a COMPANY_ADMIN's frontend omits it;
// the backend defaults to their own company), read-only on UPDATE.
export interface ManagedUnit {
  id: number;
  company: number;
  company_name: string;
  label: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ManagedUnitCreatePayload {
  company?: number;
  label: string;
  is_active?: boolean;
}

export type ManagedUnitUpdatePayload = Partial<ManagedUnitCreatePayload>;

export interface Service {
  id: number;
  // Sprint 3B — the owning provider company. Always present on reads
  // (the model column is NOT NULL); write-once on CREATE, read-only on
  // UPDATE. Added to this type in Sprint 139 §4, when the company
  // selector started filtering the list client-side as well as server-
  // side — the field was always on the wire, just not declared here.
  company: number;
  company_name: string;
  category: number;
  category_name: string;
  name: string;
  description: string;
  unit_type: ServiceUnitType;
  // RF-2 (mirror) — operator-supplied unit name; only meaningful for
  // unit_type === "OTHER" (blank otherwise, enforced server-side). Kept
  // in sync with managed_unit's current label whenever one is linked
  // (Sprint 123) — still the single value every renderer (PDF, exports,
  // lists) reads, whether or not the row has adopted the catalog.
  custom_unit_label: string;
  // Sprint 123 — optional managed-unit catalog link (only meaningful for
  // unit_type === "OTHER"). Null for a legacy / not-yet-adopted row.
  managed_unit: number | null;
  managed_unit_label: string | null;
  // DRF serializes Decimal as a string to preserve precision; the form
  // converts to/from number locally and re-emits as a string on submit.
  default_unit_price: string;
  default_vat_pct: string;
  is_active: boolean;
  // Sprint 138 §1 — does ANY CustomerServicePrice row reference this
  // service, ACTIVE OR ARCHIVED? `CustomerServicePrice.service` is
  // PROTECT and "deleting" a price only archives it (Sprint 137 item 2),
  // so true here means the service is permanently undeletable and the
  // UI must offer Deactiveren rather than Delete.
  has_price_rows: boolean;
  created_at: string;
  updated_at: string;
}

export interface ServiceCreatePayload {
  category: number;
  // Sprint 135 — write-once on CREATE only (read-only on UPDATE, mirrors
  // ManagedUnitCreatePayload.company). Omit unless the actor is a
  // SUPER_ADMIN disambiguating across 2+ provider companies — a
  // COMPANY_ADMIN's own company is defaulted server-side either way.
  company?: number;
  name: string;
  description?: string;
  unit_type: ServiceUnitType;
  // RF-2 (mirror) — sent for unit_type === "OTHER"; the backend forces it
  // blank for concrete unit types and requires it for OTHER, UNLESS
  // managed_unit is also sent, in which case the backend derives it from
  // the unit's label and this value is ignored.
  custom_unit_label?: string;
  // Sprint 123 — when set, the backend overwrites custom_unit_label with
  // this unit's current label (it must belong to the same company).
  managed_unit?: number | null;
  default_unit_price: string;
  default_vat_pct: string;
  is_active?: boolean;
}

export type ServiceUpdatePayload = Partial<ServiceCreatePayload>;

// M5 C — bulk-raise the catalog default_unit_price of a set of Services
// by a percentage or fixed amount, IN PLACE. Updates the quoting
// baseline only; never touches any CustomerServicePrice (billing).
export interface ServiceBulkRaisePayload {
  services: number[];
  mode: "percent" | "fixed";
  amount: string;
  // #108 Part C — omitted means "raise" (pre-#108 wire shape).
  direction?: "raise" | "lower";
}

export interface ServiceBulkRaiseResultRow {
  service: number;
  old_default_unit_price: string;
  new_default_unit_price: string;
}

export interface ServiceBulkRaiseResult {
  updated_count: number;
  results: ServiceBulkRaiseResultRow[];
}

// Per-customer contract price. Only an active row triggers the instant-
// ticket path (Batch 7); absence means the request must go through the
// proposal phase. `valid_to` null means open-ended.
// Sprint 143 §3 — a folder that belongs to ONE CUSTOMER and groups that
// customer's price rows. NOT a `ServiceCategory`: that is the PROVIDER's
// catalog grouping, shared across the company's customers. A folder is
// the customer's own arrangement of the prices agreed with them, and a
// folder copied from a category keeps no link back to it.
export interface CustomerPriceFolder {
  id: number;
  customer: number;
  name: string;
  is_active: boolean;
  // Contract + custom rows inside, from one annotation on the list
  // queryset. Drives the index card and the delete confirmation's count.
  price_count: number;
  created_at: string;
  updated_at: string;
}

export interface CustomerPriceFolderCreatePayload {
  name: string;
  is_active?: boolean;
}

export type CustomerPriceFolderUpdatePayload =
  Partial<CustomerPriceFolderCreatePayload>;

// Result of DELETE .../price-folders/<id>/?with_contents=…. Named for
// what ACTUALLY happened: a folder-only delete archives nothing.
export interface CustomerPriceFolderDeleteResult {
  archived_price_count: number;
  with_contents: boolean;
}

export interface CustomerServicePrice {
  id: number;
  customer: number;
  // Sprint 143 §3 — null when the row sits outside every folder. Legal
  // and permanent: every pre-143 row is folderless, and "delete the
  // folder, keep the prices" produces more of them.
  folder: number | null;
  service: number;
  service_name: string;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerServicePriceCreatePayload {
  service: number;
  folder?: number | null;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to?: string | null;
  is_active?: boolean;
}

export type CustomerServicePriceUpdatePayload =
  Partial<CustomerServicePriceCreatePayload>;

// M5 A — per-customer ad-hoc / custom price line for a non-catalog
// service. Parallel to CustomerServicePrice but with no `service` FK:
// a free-text `custom_name` + its own `unit_type`. Provider-internal;
// never influences the instant-ticket resolver.
export interface CustomerCustomPrice {
  id: number;
  customer: number;
  // Sprint 143 §3 — see `CustomerServicePrice.folder`.
  folder: number | null;
  custom_name: string;
  unit_type: ServiceUnitType;
  unit_type_display: string;
  // RF-2 — the operator-supplied unit name, only meaningful when
  // `unit_type === "OTHER"` (e.g. "m3"). The backend forces it blank
  // for every concrete unit type, so it is always "" for those. Kept in
  // sync with managed_unit's current label whenever one is linked
  // (Sprint 123).
  custom_unit_label: string;
  // Sprint 123 — optional managed-unit catalog link (only meaningful for
  // unit_type === "OTHER"). Must belong to customer.company's provider.
  managed_unit: number | null;
  managed_unit_label: string | null;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerCustomPriceCreatePayload {
  folder?: number | null;
  custom_name: string;
  unit_type: ServiceUnitType;
  custom_unit_label?: string;
  // Sprint 123 — when set, the backend overwrites custom_unit_label with
  // this unit's current label (it must belong to the customer's company).
  managed_unit?: number | null;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to?: string | null;
  is_active?: boolean;
}

export type CustomerCustomPriceUpdatePayload =
  Partial<CustomerCustomPriceCreatePayload>;

// M5 C — bulk-raise a customer's active catalog (CustomerServicePrice)
// rows by a percentage or fixed amount. History-preserving: the backend
// writes new validity-window rows rather than mutating the sources.
export interface CustomerPriceBulkRaisePayload {
  prices: number[];
  mode: "percent" | "fixed";
  amount: string;
  // #108 Part C — omitted means "raise" (pre-#108 wire shape).
  direction?: "raise" | "lower";
  valid_from: string;
}

export interface CustomerPriceBulkRaiseResultRow {
  source_price: number;
  service: number;
  old_unit_price: string;
  new_unit_price: string;
  customer_service_price: number;
}

export interface CustomerPriceBulkRaiseResult {
  created_count: number;
  valid_from: string;
  results: CustomerPriceBulkRaiseResultRow[];
}

// Sprint 8B — copy provider-default prices to a customer.
// POST /api/customers/<id>/pricing/copy-from-default/. All-or-nothing
// validation (any invalid/inactive/cross-company service → 400, zero
// rows); per-service idempotency skips services already holding an
// active overlapping CustomerServicePrice row.
export interface CustomerPriceCopyFromDefaultPayload {
  services: number[];
  valid_from: string;
  valid_to: string | null;
  // Sprint 143 §3 — copy INTO a folder. Either an existing folder id or
  // a name to create one with (the "copy a company category, with its
  // services" flow). Mutually exclusive; both in the SAME request so a
  // failed copy cannot strand an empty folder.
  folder?: number | null;
  folder_name?: string;
}

export interface CustomerPriceCopyFromDefaultResultRow {
  service: number;
  status: "created" | "skipped_existing";
  customer_service_price?: number;
}

export interface CustomerPriceCopyFromDefaultResult {
  created_count: number;
  skipped_count: number;
  // Sprint 143 §3 — the folder the rows landed in, so the UI can drill
  // straight into the one it just created. Null when no folder was asked
  // for (the pre-143 flat copy).
  folder: CustomerPriceFolder | null;
  results: CustomerPriceCopyFromDefaultResultRow[];
}



// ---- RF-1 — message inbox ------------------------------------------------
export type InboxThreadKind = "ticket" | "extra_work";

export interface InboxAuthor {
  name: string | null;
  photo_url: string | null;
}

export interface InboxLastMessage {
  id: number;
  author: InboxAuthor;
  snippet: string;
  message_type: string;
  created_at: string;
}

export interface InboxRosterUser {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface InboxRow {
  kind: InboxThreadKind;
  id: number;
  title: string;
  customer: { id: number; name: string; logo_url: string | null } | null;
  building: { id: number; name: string } | null;
  last_message: InboxLastMessage | null;
  unread_count: number;
  // Present ONLY for provider-management viewers (SA / CA / BM). A
  // customer viewer never receives this key — they see only their own
  // unread_count.
  unread_by?: InboxRosterUser[];
}

export interface InboxResponse {
  count: number;
  offset: number;
  page_size: number;
  results: InboxRow[];
}

export interface InboxFilters {
  kind?: InboxThreadKind;
  date_from?: string;
  date_to?: string;
  q?: string;
  unread_only?: boolean;
  offset?: number;
  page_size?: number;
}

// ---------------------------------------------------------------------------
// Invoicing (Phase 4a REST surface — see backend/invoicing/serializers.py +
// backend/invoicing/views.py::InvoiceViewSet). All money/decimal fields are
// DRF decimal STRINGS; date/datetime are ISO strings. Consumed by the
// Facturen page + the invoice-detail page (Phase 4b).
// ---------------------------------------------------------------------------
export type InvoiceStatus = "DRAFT" | "ISSUED" | "SENT";
// Sprint 132 — PER_BUILDING_DEPARTMENT_WORK_TYPE groups one level finer
// than PER_BUILDING: Building + Department + Work Type. Untagged Extra
// Work (no department and/or no work type) gets its own invoice rather
// than being dropped or folded into a labelled one.
export type InvoiceGranularity =
  | "CUSTOMER"
  | "PER_BUILDING"
  | "PER_BUILDING_DEPARTMENT_WORK_TYPE";
export type InvoiceDayRule = "FIRST_OF_MONTH" | "LAST_OF_MONTH";

export interface InvoiceLine {
  id: number;
  ordering: number;
  description: string;
  // Source Extra Work id (NULL for a hand-added line).
  extra_work: number | null;
  quantity: string;
  unit_price: string;
  vat_pct: string;
  line_subtotal: string;
  line_vat: string;
  line_total: string;
  period_year: number | null;
  period_month: number | null;
  performed_on: string | null;
  created_at: string;
  updated_at: string;
}

export interface Invoice {
  id: number;
  status: InvoiceStatus;
  number: string | null;
  year: number | null;
  company: number;
  /** Sprint 187 §6a — the issuing provider company's name. Numbering is
   *  gapless per company per year, so the number alone does not identify
   *  an invoice. PROVIDER-SIDE ONLY: `CustomerInvoice` deliberately does
   *  not carry it. */
  company_name: string;
  customer: number;
  customer_name: string;
  building: number | null;
  building_name: string | null;
  // Sprint 132 — set only when generated at PER_BUILDING_DEPARTMENT_
  // WORK_TYPE granularity; null on every other invoice (mirrors building /
  // building_name's own null-when-unset shape). Compose the display label
  // with `formatInvoiceGroupLabel` (lib/intl) — never pre-joined here.
  department: number | null;
  department_name: string | null;
  work_type: number | null;
  work_type_name: string | null;
  period_year: number | null;
  period_month: number | null;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
  optional_fee_label: string;
  optional_fee_amount: string | null;
  summary_text: string;
  is_reversal: boolean;
  reverses: number | null;
  // Sprint 122 (Part B2) — the reversing credit note's number, if this
  // invoice has been credited (any status: provider sees unsent reversals
  // too). Null otherwise, and always null on a reversal itself.
  credited_by_number: string | null;
  issued_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  // Sprint 183 §3 / Sprint 184 §5 — who generated this invoice. The FK
  // is nullable and a NULL means the SYSTEM created it (the month-end
  // run), which is why the label is computed server-side rather than
  // joined here: the frontend must not have to decide what an absent
  // creator is called. Folded in from `FacturenPage.tsx`, which was
  // casting `inv as Invoice & { created_by_label?: string }` at the
  // render site because this file belonged to another agent that round.
  created_by: number | null;
  created_by_label: string;
  lines: InvoiceLine[];
}

// Phase 5 — the REDACTED customer read shape (GET /api/invoices/my/...).
// Mirrors backend CustomerInvoiceSerializer: no company/customer/year/reverses/
// timestamps, and lines carry no extra_work / id / ordering / timestamps.
export interface CustomerInvoiceLine {
  description: string;
  quantity: string;
  unit_price: string;
  vat_pct: string;
  line_subtotal: string;
  line_vat: string;
  line_total: string;
  period_year: number | null;
  period_month: number | null;
  performed_on: string | null;
}

export interface CustomerInvoice {
  id: number;
  number: string | null;
  status: InvoiceStatus; // always "SENT" in this scope
  customer_name: string;
  building_name: string | null;
  // Sprint 132 — see Invoice.department_name / work_type_name.
  department_name: string | null;
  work_type_name: string | null;
  period_year: number | null;
  period_month: number | null;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
  optional_fee_label: string;
  optional_fee_amount: string | null;
  summary_text: string;
  is_reversal: boolean;
  // Sprint 122 (Part B2) — the reversing credit note's number, ONLY once
  // that credit note is itself SENT (mirrors the customer scope's SENT-only
  // gate — never reveals an unsent reversal). Null otherwise.
  credited_by_number: string | null;
  issued_at: string | null;
  sent_at: string | null;
  lines: CustomerInvoiceLine[];
}

// One row of GET /api/invoices/due/ — informational "who's due" data
// (driven by Customer.invoice_day_rule; gates nothing).
/**
 * Sprint 183 §2 — why a due row has nothing to invoice, diagnosed by the
 * server so the Due panel and the preview say the same sentence.
 *
 * Sprint 184 §5 — folded in from `FacturenPage.tsx`, where it was
 * narrowed locally because `api/types.ts` belonged to another agent that
 * round. A shape described in the page that renders it is a shape the
 * next caller has to rediscover.
 */
export interface InvoiceNothingReason {
  reason:
    | "NO_EXTRA_WORK"
    | "NONE_FINISHED"
    | "ALL_INVOICED"
    | "NOT_IN_PERIOD"
    | "NOTHING_TO_EXPLAIN";
  unbilled_count: number;
  finished_count: number;
  invoiced_count: number;
}

export interface InvoiceDueRow {
  customer: number;
  customer_name: string;
  company: number;
  invoice_day_rule: InvoiceDayRule | "";
  invoice_day_of_month: number | null;
  invoice_granularity_default: InvoiceGranularity;
  period_year: number;
  period_month: number;
  unbilled_count: number;
  unbilled_total: string;
  is_due: boolean;
  // Sprint 182 §3 — the customer's SAVED billing pair, echoed on the row
  // so the generate dialog opens on what that customer is set to rather
  // than on a global default. Optional: a row from a server that predates
  // the split carries neither.
  invoice_billing_target?: InvoiceBillingTarget;
  invoice_split?: InvoiceSplit;
  // Sprint 183 §2 — present only when there is nothing to invoice.
  nothing_reason?: InvoiceNothingReason;
}
