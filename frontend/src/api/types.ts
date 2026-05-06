export type Role =
  | "SUPER_ADMIN"
  | "COMPANY_ADMIN"
  | "BUILDING_MANAGER"
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
  building: number;
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
  building: number;
  name: string;
  contact_email: string;
  phone: string;
  language: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
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
