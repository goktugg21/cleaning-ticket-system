// Sprint 5 — the sub-task / staff-slot admin shapes are co-located in
// `./admin` (alongside SlotStatus + TicketStaffAssignmentAdmin + their client
// fns). `TicketDetail` carries the nested read-only `sub_tasks`, so it
// re-uses that type. Type-only import — erased at build, no runtime cycle.
import type { SubTask } from "./admin";

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
  | "IN_PROGRESS"
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
  is_active: boolean;
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

export interface TicketList {
  id: number;
  ticket_no: string;
  title: string;
  type: string;
  priority: string;
  status: TicketStatus;
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
  changed_by: number;
  changed_by_email: string;
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
  | { anonymous: true; label_key: string };

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
export interface Notification {
  id: number;
  event_type: string;
  is_directed: boolean;
  summary: string;
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

export interface BuildingAdmin {
  id: number;
  company: number;
  name: string;
  address: string;
  city: string;
  country: string;
  postal_code: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerAdmin {
  id: number;
  company: number;
  // Sprint 14: legacy single-building anchor, now nullable. New
  // consolidated customers can be created with no anchor and linked
  // to multiple buildings via the M:N CustomerBuildingMembership.
  building: number | null;
  name: string;
  contact_email: string;
  phone: string;
  language: string;
  is_active: boolean;
  // Sprint 23B — assigned-staff contact-visibility policy. Defaults
  // True. The CustomerFormPage exposes these as three checkboxes
  // for OSIUS Admin / Company Admin only.
  show_assigned_staff_name: boolean;
  show_assigned_staff_email: boolean;
  show_assigned_staff_phone: boolean;
  // RF-1 — customer company logo URL (null when unset).
  logo_url?: string | null;
  created_at: string;
  updated_at: string;
  // Per-current-user, per-customer capability block from the
  // CustomerSerializer.actions field. Optional for older list payloads.
  actions?: CustomerActions;
}

// Sprint 14 — Customer ↔ Building (M:N) link.
export interface CustomerBuildingMembership {
  id: number;
  customer: number;
  building_id: number;
  building_name: string;
  building_address: string;
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

export interface UserAdmin {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  language: string;
  is_active: boolean;
  deleted_at: string | null;
  // Sprint 28 Batch 15.5 — added by the user-list serializer. The
  // field is required on the wire; if the backend ever returns a
  // payload without it the type-check here flags it at the call
  // site rather than silently rendering an empty chip.
  scope_summary: UserScopeSummary;
  // Sprint 2c — read-only single HIGHEST effective customer access role the
  // user holds (CUSTOMER_COMPANY_ADMIN > CUSTOMER_LOCATION_MANAGER >
  // CUSTOMER_USER), company-scoped to the viewer; null for provider-side
  // users / no in-scope active grant. Editing stays in the per-customer
  // permission matrix / the contact->user surface.
  customer_access_role: CustomerAccessRole | null;
}

export interface UserAdminDetail extends UserAdmin {
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
  role: Role;
  employment_type: EmploymentType | null;
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
  | "TICKET_UNASSIGNED";

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

// List shape (lean — no description / notes / line items).
export interface ExtraWorkRequestList {
  id: number;
  company: number;
  company_name: string;
  building: number;
  building_name: string;
  customer: number;
  customer_name: string;
  title: string;
  category: ExtraWorkCategory;
  urgency: ExtraWorkUrgency;
  status: ExtraWorkStatus;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
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
  title: string;
  description: string;
  building: number;
  customer: number;
  category: string;
  category_other_text?: string;
  urgency: string;
  preferred_date?: string | null;
  // Sprint 5 (frontend) — the create page now sends the customer's
  // chosen INTENT (driven by the preview endpoint's `allowed_intents`
  // / `default_intent`). Optional: the backend derives a safe default
  // (`derive_default_intent`) when omitted, so older callers and the
  // graceful-degradation path (preview unavailable) stay valid.
  request_intent?: ExtraWorkRequestIntent;
  // Each line is either a catalog service (`service`) OR a free-text
  // custom line (`custom_description`) — XOR, the create form guarantees
  // exactly one is set. A custom line carries no `service`; the backend
  // treats it as needs-provider-pricing and routes the request to a
  // proposal. Mirrors the cart-create line serializer + the preview
  // line serializer (both accept service XOR custom_description).
  line_items: Array<{
    service?: number;
    custom_description?: string;
    // Decimal as string per DRF convention.
    quantity: string;
    requested_date: string;
    customer_note?: string;
  }>;
}

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
  // Decimal as string per DRF convention.
  quantity: string;
  requested_date: string;
  customer_note?: string;
}

// Request body for POST /extra-work/preview/.
export interface ExtraWorkPreviewPayload {
  building: number;
  customer: number;
  // Optional candidate intent. When present the response carries
  // `requested_intent_allowed` (+ `requested_intent_error` on rejection).
  request_intent?: ExtraWorkRequestIntent | null;
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
  // Direct-publish (DRAFT proposal → SENT → CUSTOMER_APPROVED) is
  // tightened to include all cheap send preconditions PLUS, for BM,
  // the override key. See backend/extra_work/views_proposals.py.
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
// See `docs/product/meeting-2026-05-15-system-requirements.md` §1
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
// Sprint 28 Batch 5 — Service catalog (provider-wide) + per-customer pricing
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
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ServiceCategoryCreatePayload {
  name: string;
  description?: string;
  is_active?: boolean;
}

export type ServiceCategoryUpdatePayload = Partial<ServiceCategoryCreatePayload>;

export interface Service {
  id: number;
  category: number;
  category_name: string;
  name: string;
  description: string;
  unit_type: ServiceUnitType;
  // DRF serializes Decimal as a string to preserve precision; the form
  // converts to/from number locally and re-emits as a string on submit.
  default_unit_price: string;
  default_vat_pct: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ServiceCreatePayload {
  category: number;
  name: string;
  description?: string;
  unit_type: ServiceUnitType;
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
export interface CustomerServicePrice {
  id: number;
  customer: number;
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
  custom_name: string;
  unit_type: ServiceUnitType;
  unit_type_display: string;
  // RF-2 — the operator-supplied unit name, only meaningful when
  // `unit_type === "OTHER"` (e.g. "m3"). The backend forces it blank
  // for every concrete unit type, so it is always "" for those.
  custom_unit_label: string;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerCustomPriceCreatePayload {
  custom_name: string;
  unit_type: ServiceUnitType;
  custom_unit_label?: string;
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
}

export interface CustomerPriceCopyFromDefaultResultRow {
  service: number;
  status: "created" | "skipped_existing";
  customer_service_price?: number;
}

export interface CustomerPriceCopyFromDefaultResult {
  created_count: number;
  skipped_count: number;
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
