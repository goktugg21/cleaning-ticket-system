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
