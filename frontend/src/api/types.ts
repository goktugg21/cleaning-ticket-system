export type Role =
  | "SUPER_ADMIN"
  | "COMPANY_ADMIN"
  | "BUILDING_MANAGER"
  // Sprint 23A — service-provider-side field staff. Added here so
  // the frontend Role union stays in sync with backend UserRole.
  | "STAFF"
  | "CUSTOMER_USER";

export type TicketStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "WAITING_CUSTOMER_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "CLOSED"
  | "REOPENED_BY_ADMIN";

export type TicketMessageType = "PUBLIC_REPLY" | "INTERNAL_NOTE";

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

// Sprint 23B — list of staff currently assigned to a ticket via
// TicketStaffAssignment. The backend serializer gates this list
// through Customer.show_assigned_staff_* flags before returning
// it to a CUSTOMER_USER; if every flag is off the payload
// collapses to a single anonymous-label entry the UI translates
// via the `label_key` i18n key.
export type AssignedStaffEntry =
  | {
      id: number;
      full_name?: string;
      email?: string;
      phone?: string;
      anonymous?: false;
    }
  | { anonymous: true; label_key: string };

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

export interface TicketMessage {
  id: number;
  ticket: number;
  author: number;
  author_email: string;
  message: string;
  message_type: TicketMessageType;
  is_hidden: boolean;
  created_at: string;
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
}

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
  created_at: string;
  updated_at: string;
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

export interface UserAdmin {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  language: string;
  is_active: boolean;
  deleted_at: string | null;
}

export interface UserAdminDetail extends UserAdmin {
  company_ids: number[];
  building_ids: number[];
  customer_ids: number[];
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

// Sprint 24A — admin read/write shape for a single BuildingStaffVisibility
// row keyed on (user, building). Editing happens via PATCH on the
// detail URL; the only editable field is `can_request_assignment`.
export interface BuildingStaffVisibilityAdmin {
  id: number;
  user_id: number;
  user_email: string;
  building_id: number;
  building_name: string;
  building_company_id: number;
  can_request_assignment: boolean;
  created_at: string;
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
}

// Provider-side pricing line item — full shape with internal note.
// Customer-side reads come back with internal_cost_note omitted.
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
  // Provider-only fields — optional because the API strips them
  // for CUSTOMER_USER actors.
  manager_note?: string;
  internal_cost_note?: string;
  override_by?: number | null;
  override_reason?: string;
  override_at?: string | null;
  pricing_line_items: ExtraWorkPricingLineItem[];
  // Sprint 28 Batch 6 — cart line items + routing decision.
  // `line_items` is always present on responses (empty array for
  // legacy single-line requests that pre-date the cart shape).
  // `routing_decision` is computed by the backend on every detail
  // read.
  line_items: ExtraWorkRequestItem[];
  routing_decision: RoutingDecision;
  allowed_next_statuses: ExtraWorkStatus[];
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
  line_items: Array<{
    service: number;
    // Decimal as string per DRF convention.
    quantity: string;
    requested_date: string;
    customer_note?: string;
  }>;
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
}

export interface CustomerUserMembership {
  id: number;
  customer: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  user_role: Role;
  created_at: string;
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
// (Contacts vs Users are distinct entities). Promoting a Contact
// into a User is an explicit, separate flow (parked).
//
// Backend serializer: `customers/serializers_contacts.py` (ContactSerializer).
// Backend permission: SUPER_ADMIN or COMPANY_ADMIN for the customer's provider.
export interface Contact {
  id: number;
  customer: number;
  building: number | null;
  full_name: string;
  email: string;
  phone: string;
  role_label: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ContactCreatePayload {
  building?: number | null;
  full_name: string;
  email?: string;
  phone?: string;
  role_label?: string;
  notes?: string;
}

// PATCH semantics — every field optional.
export type ContactUpdatePayload = Partial<ContactCreatePayload>;

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
