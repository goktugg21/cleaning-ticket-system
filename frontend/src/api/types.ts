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
  created_at: string;
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
  allowed_next_statuses: ExtraWorkStatus[];
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
