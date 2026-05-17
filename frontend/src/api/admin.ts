import { api } from "./client";
import type {
  AuditLog,
  BuildingAdmin,
  BuildingManagerMembership,
  BuildingStaffVisibilityAdmin,
  CompanyAdmin,
  CompanyAdminMembership,
  Contact,
  ContactCreatePayload,
  ContactUpdatePayload,
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerServicePrice,
  CustomerServicePriceCreatePayload,
  CustomerServicePriceUpdatePayload,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
  InvitationAdmin,
  PaginatedResponse,
  Role,
  Service,
  ServiceCategory,
  ServiceCategoryCreatePayload,
  ServiceCategoryUpdatePayload,
  ServiceCreatePayload,
  ServiceUpdatePayload,
  StaffAssignmentRequest,
  StaffAssignmentRequestStatus,
  StaffProfileAdmin,
  UserAdmin,
  UserAdminDetail,
} from "./types";

/**
 * Pull DRF-style field errors out of an axios error response. Returns a
 * record keyed by field name (or "detail" for non-field errors). The admin
 * form pages render these next to each input. Mirrors the helper inside
 * AcceptInvitationPage so the two flows feel identical.
 */
export type AdminFieldErrors = Record<string, string>;

export function extractAdminFieldErrors(error: unknown): AdminFieldErrors {
  const result: AdminFieldErrors = {};
  if (typeof error !== "object" || error === null) return result;
  const data = (error as { response?: { data?: unknown } }).response?.data;
  if (!data || typeof data !== "object") return result;
  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      result[key] = String(value[0] ?? "");
    } else if (value !== null && value !== undefined) {
      result[key] = String(value);
    }
  }
  return result;
}

export interface AdminListParams {
  search?: string;
  is_active?: "true" | "false";
  page?: number;
  company?: number;
  building?: number;
  page_size?: number;
  role?: string;
}

function cleanParams(input: AdminListParams): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === "") continue;
    out[key] = value as string | number;
  }
  return out;
}

// ---- Companies --------------------------------------------------------

export interface CompanyWritePayload {
  name?: string;
  slug?: string;
  default_language?: string;
}

export async function listCompanies(
  params: AdminListParams = {},
): Promise<PaginatedResponse<CompanyAdmin>> {
  const response = await api.get<PaginatedResponse<CompanyAdmin>>("/companies/", {
    params: cleanParams(params),
  });
  return response.data;
}

export async function getCompany(id: number): Promise<CompanyAdmin> {
  const response = await api.get<CompanyAdmin>(`/companies/${id}/`);
  return response.data;
}

export async function createCompany(
  payload: CompanyWritePayload,
): Promise<CompanyAdmin> {
  const response = await api.post<CompanyAdmin>("/companies/", payload);
  return response.data;
}

export async function updateCompany(
  id: number,
  payload: CompanyWritePayload,
): Promise<CompanyAdmin> {
  const response = await api.patch<CompanyAdmin>(`/companies/${id}/`, payload);
  return response.data;
}

export async function deactivateCompany(id: number): Promise<void> {
  await api.delete(`/companies/${id}/`);
}

export async function reactivateCompany(id: number): Promise<CompanyAdmin> {
  const response = await api.post<CompanyAdmin>(`/companies/${id}/reactivate/`);
  return response.data;
}

// ---- Buildings --------------------------------------------------------

export interface BuildingWritePayload {
  company?: number;
  name?: string;
  address?: string;
  city?: string;
  country?: string;
  postal_code?: string;
}

export async function listBuildings(
  params: AdminListParams = {},
): Promise<PaginatedResponse<BuildingAdmin>> {
  const response = await api.get<PaginatedResponse<BuildingAdmin>>("/buildings/", {
    params: cleanParams(params),
  });
  return response.data;
}

export async function getBuilding(id: number): Promise<BuildingAdmin> {
  const response = await api.get<BuildingAdmin>(`/buildings/${id}/`);
  return response.data;
}

export async function createBuilding(
  payload: BuildingWritePayload,
): Promise<BuildingAdmin> {
  const response = await api.post<BuildingAdmin>("/buildings/", payload);
  return response.data;
}

export async function updateBuilding(
  id: number,
  payload: BuildingWritePayload,
): Promise<BuildingAdmin> {
  const response = await api.patch<BuildingAdmin>(`/buildings/${id}/`, payload);
  return response.data;
}

export async function deactivateBuilding(id: number): Promise<void> {
  await api.delete(`/buildings/${id}/`);
}

export async function reactivateBuilding(id: number): Promise<BuildingAdmin> {
  const response = await api.post<BuildingAdmin>(`/buildings/${id}/reactivate/`);
  return response.data;
}

// ---- Customers --------------------------------------------------------

export interface CustomerWritePayload {
  company?: number;
  building?: number;
  name?: string;
  contact_email?: string;
  phone?: string;
  language?: string;
  // Sprint 23B — assigned-staff contact-visibility flags. The
  // backend serializer accepts these on PATCH; the CustomerViewSet
  // permission gate is IsSuperAdminOrCompanyAdmin, so only
  // service-provider-side admins can flip them. Defaults stay
  // True (show everything) until explicitly turned off.
  show_assigned_staff_name?: boolean;
  show_assigned_staff_email?: boolean;
  show_assigned_staff_phone?: boolean;
}

export async function listCustomers(
  params: AdminListParams = {},
): Promise<PaginatedResponse<CustomerAdmin>> {
  const response = await api.get<PaginatedResponse<CustomerAdmin>>("/customers/", {
    params: cleanParams(params),
  });
  return response.data;
}

export async function getCustomer(id: number): Promise<CustomerAdmin> {
  const response = await api.get<CustomerAdmin>(`/customers/${id}/`);
  return response.data;
}

export async function createCustomer(
  payload: CustomerWritePayload,
): Promise<CustomerAdmin> {
  const response = await api.post<CustomerAdmin>("/customers/", payload);
  return response.data;
}

export async function updateCustomer(
  id: number,
  payload: CustomerWritePayload,
): Promise<CustomerAdmin> {
  const response = await api.patch<CustomerAdmin>(`/customers/${id}/`, payload);
  return response.data;
}

export async function deactivateCustomer(id: number): Promise<void> {
  await api.delete(`/customers/${id}/`);
}

export async function reactivateCustomer(id: number): Promise<CustomerAdmin> {
  const response = await api.post<CustomerAdmin>(`/customers/${id}/reactivate/`);
  return response.data;
}

// ---- Users ------------------------------------------------------------

export interface UserUpdatePayload {
  full_name?: string;
  language?: string;
  role?: Role;
  is_active?: boolean;
}

// NOTE: /api/users/ does not currently support ?search= server-side
// (UserViewSet only declares filters.OrderingFilter). The Users page does
// client-side filtering of the current page when the user types into the
// search box. Sending ?search= is harmless and would Just Work if a future
// backend change adds SearchFilter to that view.
export async function listUsers(
  params: AdminListParams = {},
): Promise<PaginatedResponse<UserAdmin>> {
  const response = await api.get<PaginatedResponse<UserAdmin>>("/users/", {
    params: cleanParams(params),
  });
  return response.data;
}

export async function getUser(id: number): Promise<UserAdminDetail> {
  const response = await api.get<UserAdminDetail>(`/users/${id}/`);
  return response.data;
}

export async function updateUser(
  id: number,
  payload: UserUpdatePayload,
): Promise<UserAdminDetail> {
  const response = await api.patch<UserAdminDetail>(`/users/${id}/`, payload);
  return response.data;
}

export async function deactivateUser(id: number): Promise<void> {
  await api.delete(`/users/${id}/`);
}

export async function reactivateUser(id: number): Promise<UserAdminDetail> {
  const response = await api.post<UserAdminDetail>(`/users/${id}/reactivate/`);
  return response.data;
}

// ---- Invitations ------------------------------------------------------

export interface InvitationCreatePayload {
  email: string;
  full_name?: string;
  role: Role;
  company_ids?: number[];
  building_ids?: number[];
  customer_ids?: number[];
}

// NOTE: /api/auth/invitations/ does not currently support a ?status= filter
// (InvitationListCreateView has no filterset_class). The Invitations page
// filters status client-side on the current page. Documenting here so future
// readers do not waste time chasing a missing query param.
export async function listInvitations(
  params: AdminListParams = {},
): Promise<PaginatedResponse<InvitationAdmin>> {
  const response = await api.get<PaginatedResponse<InvitationAdmin>>(
    "/auth/invitations/",
    { params: cleanParams(params) },
  );
  return response.data;
}

export async function createInvitation(
  payload: InvitationCreatePayload,
): Promise<InvitationAdmin> {
  const response = await api.post<InvitationAdmin>("/auth/invitations/", payload);
  return response.data;
}

export async function revokeInvitation(id: number): Promise<InvitationAdmin> {
  const response = await api.post<InvitationAdmin>(
    `/auth/invitations/${id}/revoke/`,
  );
  return response.data;
}

// ---- Memberships ------------------------------------------------------

// Membership endpoints are not paginated server-side; they return a plain
// array in `results` (DRF defaults). We type them as PaginatedResponse and
// callers read `.results`.

export async function listCompanyAdmins(
  companyId: number,
): Promise<PaginatedResponse<CompanyAdminMembership>> {
  const response = await api.get<PaginatedResponse<CompanyAdminMembership>>(
    `/companies/${companyId}/admins/`,
  );
  return response.data;
}

export async function addCompanyAdmin(
  companyId: number,
  userId: number,
): Promise<CompanyAdminMembership> {
  const response = await api.post<CompanyAdminMembership>(
    `/companies/${companyId}/admins/`,
    { user_id: userId },
  );
  return response.data;
}

export async function removeCompanyAdmin(
  companyId: number,
  userId: number,
): Promise<void> {
  await api.delete(`/companies/${companyId}/admins/${userId}/`);
}

export async function listBuildingManagers(
  buildingId: number,
): Promise<PaginatedResponse<BuildingManagerMembership>> {
  const response = await api.get<PaginatedResponse<BuildingManagerMembership>>(
    `/buildings/${buildingId}/managers/`,
  );
  return response.data;
}

export async function addBuildingManager(
  buildingId: number,
  userId: number,
): Promise<BuildingManagerMembership> {
  const response = await api.post<BuildingManagerMembership>(
    `/buildings/${buildingId}/managers/`,
    { user_id: userId },
  );
  return response.data;
}

export async function removeBuildingManager(
  buildingId: number,
  userId: number,
): Promise<void> {
  await api.delete(`/buildings/${buildingId}/managers/${userId}/`);
}

export async function listCustomerUsers(
  customerId: number,
): Promise<PaginatedResponse<CustomerUserMembership>> {
  const response = await api.get<PaginatedResponse<CustomerUserMembership>>(
    `/customers/${customerId}/users/`,
  );
  return response.data;
}

export async function addCustomerUser(
  customerId: number,
  userId: number,
): Promise<CustomerUserMembership> {
  const response = await api.post<CustomerUserMembership>(
    `/customers/${customerId}/users/`,
    { user_id: userId },
  );
  return response.data;
}

export async function removeCustomerUser(
  customerId: number,
  userId: number,
): Promise<void> {
  await api.delete(`/customers/${customerId}/users/${userId}/`);
}

// ---- Sprint 14: customer ↔ buildings (M:N) ----

export async function listCustomerBuildings(
  customerId: number,
): Promise<PaginatedResponse<CustomerBuildingMembership>> {
  const response = await api.get<PaginatedResponse<CustomerBuildingMembership>>(
    `/customers/${customerId}/buildings/`,
  );
  return response.data;
}

export async function addCustomerBuilding(
  customerId: number,
  buildingId: number,
): Promise<CustomerBuildingMembership> {
  const response = await api.post<CustomerBuildingMembership>(
    `/customers/${customerId}/buildings/`,
    { building_id: buildingId },
  );
  return response.data;
}

export async function removeCustomerBuilding(
  customerId: number,
  buildingId: number,
): Promise<void> {
  await api.delete(`/customers/${customerId}/buildings/${buildingId}/`);
}

// ---- Sprint 18: Audit logs (super-admin only) -------------------------

export interface AuditLogListParams {
  target_model?: string;
  target_id?: number;
  actor?: number;
  date_from?: string; // ISO 8601 datetime; backend is timezone-aware
  date_to?: string;
  page?: number;
}

export async function listAuditLogs(
  params: AuditLogListParams = {},
): Promise<PaginatedResponse<AuditLog>> {
  // The audit feed reuses the standard /api/ prefix; the resource
  // name is `audit-logs` (DRF DefaultRouter) and there is no detail
  // endpoint — the viewset deliberately omits RetrieveModelMixin so
  // a 404 is returned for /api/audit-logs/<id>/. See backend
  // audit/views.py for the rationale.
  const response = await api.get<PaginatedResponse<AuditLog>>(
    "/audit-logs/",
    {
      params: cleanParams(params as AdminListParams),
    },
  );
  return response.data;
}

// ---- Sprint 14: per-customer-user building access ----

export async function listCustomerUserAccess(
  customerId: number,
  userId: number,
): Promise<PaginatedResponse<CustomerUserBuildingAccess>> {
  const response = await api.get<PaginatedResponse<CustomerUserBuildingAccess>>(
    `/customers/${customerId}/users/${userId}/access/`,
  );
  return response.data;
}

export async function addCustomerUserAccess(
  customerId: number,
  userId: number,
  buildingId: number,
): Promise<CustomerUserBuildingAccess> {
  const response = await api.post<CustomerUserBuildingAccess>(
    `/customers/${customerId}/users/${userId}/access/`,
    { building_id: buildingId },
  );
  return response.data;
}

export async function removeCustomerUserAccess(
  customerId: number,
  userId: number,
  buildingId: number,
): Promise<void> {
  await api.delete(
    `/customers/${customerId}/users/${userId}/access/${buildingId}/`,
  );
}

// Sprint 23C — PATCH the access_role on a single
// CustomerUserBuildingAccess row. Backend gate is
// IsSuperAdminOrCompanyAdminForCompany; cross-company COMPANY_ADMIN
// attempts return 403 from the object-level check. The PATCH body
// accepts `access_role` only — `permission_overrides` and
// `is_active` editing are deferred until the matching UI lands.
export async function updateCustomerUserAccessRole(
  customerId: number,
  userId: number,
  buildingId: number,
  accessRole: CustomerAccessRole,
): Promise<CustomerUserBuildingAccess> {
  const response = await api.patch<CustomerUserBuildingAccess>(
    `/customers/${customerId}/users/${userId}/access/${buildingId}/`,
    { access_role: accessRole },
  );
  return response.data;
}

// Sprint 27E — generic write helper for the Sprint 27C-extended
// PATCH endpoint. Surfaces `permission_overrides` and `is_active`
// to the new override editor + active toggle UI.
//
// Backend contract reminders (locked by the Sprint 27C test suite):
//   - `permission_overrides` uses full-replacement semantics — the
//     dict in the PATCH body overwrites the previous one verbatim.
//   - Every override key must be in CUSTOMER_PERMISSION_KEYS;
//     provider `osius.*` keys are rejected with 400.
//   - Each override value must be a true boolean.
//   - Actor cannot edit their own access row (self-edit guard at
//     the view layer — 403 before the serializer runs).
//
// `partial` semantics: every field is independently optional; only
// keys the caller sends are PATCHed.
export interface CustomerUserAccessPatchPayload {
  access_role?: CustomerAccessRole;
  permission_overrides?: Record<string, boolean>;
  is_active?: boolean;
}

export async function updateCustomerUserAccess(
  customerId: number,
  userId: number,
  buildingId: number,
  payload: CustomerUserAccessPatchPayload,
): Promise<CustomerUserBuildingAccess> {
  const response = await api.patch<CustomerUserBuildingAccess>(
    `/customers/${customerId}/users/${userId}/access/${buildingId}/`,
    payload,
  );
  return response.data;
}

// Sprint 27E — CustomerCompanyPolicy read/write (closes G-F5).
//
// `/api/customers/<customer_id>/policy/` GET returns the policy row
// (auto-created on Customer creation by the Sprint 27C signal, so
// the call is always a plain GET — no first-write provisioning),
// PATCH accepts any subset of the seven boolean fields.
//
// Backend permissions: SUPER_ADMIN or COMPANY_ADMIN of the
// customer's provider company; CUSTOMER_USER never reaches the
// endpoint. Cross-provider COMPANY_ADMIN attempts return 403.

export async function getCustomerPolicy(
  customerId: number,
): Promise<CustomerCompanyPolicyAdmin> {
  const response = await api.get<CustomerCompanyPolicyAdmin>(
    `/customers/${customerId}/policy/`,
  );
  return response.data;
}

export type CustomerCompanyPolicyPatchPayload = Partial<
  Omit<CustomerCompanyPolicyAdmin, "customer_id">
>;

export async function updateCustomerPolicy(
  customerId: number,
  payload: CustomerCompanyPolicyPatchPayload,
): Promise<CustomerCompanyPolicyAdmin> {
  const response = await api.patch<CustomerCompanyPolicyAdmin>(
    `/customers/${customerId}/policy/`,
    payload,
  );
  return response.data;
}

// ---- Sprint 28 Batch 4 — Customer contacts (phone book) -------------
//
// `/api/customers/<customer_id>/contacts/` — list + create.
// `/api/customers/<customer_id>/contacts/<contact_id>/` — detail / update /
// delete.
//
// Backend permission gate (both URLs): SUPER_ADMIN or COMPANY_ADMIN of the
// customer's provider company. BUILDING_MANAGER / STAFF / CUSTOMER_USER are
// rejected before the view body runs. Cross-customer contact id smuggling
// is blocked by the detail view (404 on customer mismatch).
//
// Contacts are phone-book entries — they are NOT Users. The serializer
// deliberately omits password / role / scope / is_active fields. Promoting
// a Contact into a User is an explicit, separate flow (parked).

export async function listCustomerContacts(
  customerId: number,
): Promise<Contact[]> {
  // UnboundedPagination on the backend returns the standard
  // {count, next, previous, results} envelope. Callers want the flat
  // list — we unwrap it here so every page can treat the helper as a
  // plain `Contact[]`.
  const response = await api.get<PaginatedResponse<Contact>>(
    `/customers/${customerId}/contacts/`,
  );
  return response.data.results;
}

export async function createCustomerContact(
  customerId: number,
  payload: ContactCreatePayload,
): Promise<Contact> {
  const response = await api.post<Contact>(
    `/customers/${customerId}/contacts/`,
    payload,
  );
  return response.data;
}

export async function getCustomerContact(
  customerId: number,
  contactId: number,
): Promise<Contact> {
  const response = await api.get<Contact>(
    `/customers/${customerId}/contacts/${contactId}/`,
  );
  return response.data;
}

export async function updateCustomerContact(
  customerId: number,
  contactId: number,
  payload: ContactUpdatePayload,
): Promise<Contact> {
  const response = await api.patch<Contact>(
    `/customers/${customerId}/contacts/${contactId}/`,
    payload,
  );
  return response.data;
}

export async function deleteCustomerContact(
  customerId: number,
  contactId: number,
): Promise<void> {
  await api.delete(`/customers/${customerId}/contacts/${contactId}/`);
}

// ---- Sprint 24A — Staff profile + building visibility admin -----------

// `/api/users/<id>/staff-profile/` — GET returns the profile (auto-
// created on first read so the admin UI never needs a separate
// create call); PATCH accepts phone / internal_note /
// can_request_assignment / is_active. Permission gate:
// SUPER_ADMIN or COMPANY_ADMIN of the target staff user's company.

export interface StaffProfileUpdatePayload {
  phone?: string;
  internal_note?: string;
  can_request_assignment?: boolean;
  is_active?: boolean;
}

export async function getStaffProfile(
  userId: number,
): Promise<StaffProfileAdmin> {
  const response = await api.get<StaffProfileAdmin>(
    `/users/${userId}/staff-profile/`,
  );
  return response.data;
}

export async function updateStaffProfile(
  userId: number,
  payload: StaffProfileUpdatePayload,
): Promise<StaffProfileAdmin> {
  const response = await api.patch<StaffProfileAdmin>(
    `/users/${userId}/staff-profile/`,
    payload,
  );
  return response.data;
}

// `/api/users/<id>/staff-visibility/` — list / add building visibility
// rows for a STAFF user. POST {building_id} grants visibility on a
// building. COMPANY_ADMIN may only point at buildings of their own
// company; SUPER_ADMIN may point at any.

export async function listStaffVisibility(
  userId: number,
): Promise<PaginatedResponse<BuildingStaffVisibilityAdmin>> {
  const response = await api.get<
    PaginatedResponse<BuildingStaffVisibilityAdmin>
  >(`/users/${userId}/staff-visibility/`);
  return response.data;
}

export async function addStaffVisibility(
  userId: number,
  buildingId: number,
): Promise<BuildingStaffVisibilityAdmin> {
  const response = await api.post<BuildingStaffVisibilityAdmin>(
    `/users/${userId}/staff-visibility/`,
    { building_id: buildingId },
  );
  return response.data;
}

// Sprint 28 Batch 10 — `visibility_level` joins `can_request_assignment`
// as a writable field on the BSV PATCH endpoint. Both fields are
// optional on the payload so a caller can update one without
// resending the other; today's UI sends both for convenience.
export interface StaffVisibilityPatch {
  can_request_assignment?: boolean;
  visibility_level?: import("./types").StaffVisibilityLevel;
}

export async function updateStaffVisibility(
  userId: number,
  buildingId: number,
  patch: StaffVisibilityPatch,
): Promise<BuildingStaffVisibilityAdmin> {
  const response = await api.patch<BuildingStaffVisibilityAdmin>(
    `/users/${userId}/staff-visibility/${buildingId}/`,
    patch,
  );
  return response.data;
}

export async function removeStaffVisibility(
  userId: number,
  buildingId: number,
): Promise<void> {
  await api.delete(`/users/${userId}/staff-visibility/${buildingId}/`);
}

// ---- Sprint 23B — Staff assignment requests --------------------------

// `/api/staff-assignment-requests/` — the minimal Sprint 23A API:
//   GET    /                 — list (queryset filtered by role)
//   POST   /                 — create (STAFF only; backend gates)
//   POST   /:id/approve/    — manager/admin approves a pending request
//   POST   /:id/reject/     — manager/admin rejects a pending request
// The viewset returns an empty queryset for CUSTOMER_USER so the
// resource is invisible to the customer side.

export interface StaffAssignmentRequestListParams {
  page?: number;
  status?: StaffAssignmentRequestStatus;
  ticket?: number;
  staff?: number;
}

export async function listStaffAssignmentRequests(
  params: StaffAssignmentRequestListParams = {},
): Promise<PaginatedResponse<StaffAssignmentRequest>> {
  const response = await api.get<PaginatedResponse<StaffAssignmentRequest>>(
    "/staff-assignment-requests/",
    { params: cleanParams(params) },
  );
  return response.data;
}

export async function createStaffAssignmentRequest(
  ticketId: number,
): Promise<StaffAssignmentRequest> {
  const response = await api.post<StaffAssignmentRequest>(
    "/staff-assignment-requests/",
    { ticket: ticketId },
  );
  return response.data;
}

export async function approveStaffAssignmentRequest(
  id: number,
  reviewerNote: string = "",
): Promise<StaffAssignmentRequest> {
  const response = await api.post<StaffAssignmentRequest>(
    `/staff-assignment-requests/${id}/approve/`,
    { reviewer_note: reviewerNote },
  );
  return response.data;
}

export async function rejectStaffAssignmentRequest(
  id: number,
  reviewerNote: string = "",
): Promise<StaffAssignmentRequest> {
  const response = await api.post<StaffAssignmentRequest>(
    `/staff-assignment-requests/${id}/reject/`,
    { reviewer_note: reviewerNote },
  );
  return response.data;
}

// Sprint 24C — STAFF self-cancellation of their own PENDING request.
// Backend gates: STAFF role only, must be the request owner, status
// must be PENDING. Other roles get 403; admins should reject through
// the existing reviewer-note flow instead.
export async function cancelStaffAssignmentRequest(
  id: number,
): Promise<StaffAssignmentRequest> {
  const response = await api.post<StaffAssignmentRequest>(
    `/staff-assignment-requests/${id}/cancel/`,
  );
  return response.data;
}

// ---- Sprint 25A — admin/manager direct staff assignment -----------------
//
// Pilot-readiness audit found that the Sprint 23B approve-flow was the
// only path to populate `TicketStaffAssignment`. Sprint 25A adds the
// admin-driven inverse: an admin/manager picks an eligible STAFF user
// from `assignable-staff` and adds them with a single POST. Same
// backend gate as the approve flow (osius.ticket.assign_staff on the
// ticket's building). No staff-initiated request is required.

export interface AssignableStaff {
  id: number;
  email: string;
  full_name: string;
  role: "STAFF";
}

export interface TicketStaffAssignmentAdmin {
  id: number;
  ticket: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  assigned_by_id: number | null;
  assigned_by_email: string | null;
  assigned_at: string;
}

export async function listAssignableStaff(
  ticketId: number,
): Promise<AssignableStaff[]> {
  const response = await api.get<AssignableStaff[]>(
    `/tickets/${ticketId}/assignable-staff/`,
  );
  return response.data;
}

export async function listTicketStaffAssignments(
  ticketId: number,
): Promise<PaginatedResponse<TicketStaffAssignmentAdmin>> {
  const response = await api.get<PaginatedResponse<TicketStaffAssignmentAdmin>>(
    `/tickets/${ticketId}/staff-assignments/`,
  );
  return response.data;
}

export async function addTicketStaffAssignment(
  ticketId: number,
  userId: number,
): Promise<TicketStaffAssignmentAdmin> {
  const response = await api.post<TicketStaffAssignmentAdmin>(
    `/tickets/${ticketId}/staff-assignments/`,
    { user_id: userId },
  );
  return response.data;
}

export async function removeTicketStaffAssignment(
  ticketId: number,
  userId: number,
): Promise<void> {
  await api.delete(`/tickets/${ticketId}/staff-assignments/${userId}/`);
}

// ---- Sprint 28 Batch 5 — Service catalog (provider-wide) ----------------
//
// `/api/services/categories/` and `/api/services/` — list + create.
// `/api/services/categories/<id>/` and `/api/services/<id>/` — detail /
// update / delete.
//
// Backend permission gate: SUPER_ADMIN or COMPANY_ADMIN of ANY company.
// CUSTOMER_USER / BUILDING_MANAGER / STAFF never reach these views.
// List endpoints accept `?category=<id>` (services only) and
// `?is_active=true|false` filters. Lists return the standard
// {count, next, previous, results} envelope; we unwrap to a flat array
// for the consuming page (the catalog page renders the full list in
// one go — pagination is not a UX concern at this batch's row count).

export interface ServiceCategoryListParams {
  is_active?: boolean;
}

export async function listServiceCategories(
  params: ServiceCategoryListParams = {},
): Promise<ServiceCategory[]> {
  const query: Record<string, string> = {};
  if (params.is_active !== undefined) {
    query.is_active = params.is_active ? "true" : "false";
  }
  const response = await api.get<PaginatedResponse<ServiceCategory>>(
    "/services/categories/",
    { params: query },
  );
  return response.data.results;
}

export async function createServiceCategory(
  payload: ServiceCategoryCreatePayload,
): Promise<ServiceCategory> {
  const response = await api.post<ServiceCategory>(
    "/services/categories/",
    payload,
  );
  return response.data;
}

export async function getServiceCategory(id: number): Promise<ServiceCategory> {
  const response = await api.get<ServiceCategory>(`/services/categories/${id}/`);
  return response.data;
}

export async function updateServiceCategory(
  id: number,
  payload: ServiceCategoryUpdatePayload,
): Promise<ServiceCategory> {
  const response = await api.patch<ServiceCategory>(
    `/services/categories/${id}/`,
    payload,
  );
  return response.data;
}

export async function deleteServiceCategory(id: number): Promise<void> {
  await api.delete(`/services/categories/${id}/`);
}

export interface ServiceListParams {
  category?: number;
  is_active?: boolean;
}

export async function listServices(
  params: ServiceListParams = {},
): Promise<Service[]> {
  const query: Record<string, string | number> = {};
  if (params.category !== undefined) {
    query.category = params.category;
  }
  if (params.is_active !== undefined) {
    query.is_active = params.is_active ? "true" : "false";
  }
  const response = await api.get<PaginatedResponse<Service>>("/services/", {
    params: query,
  });
  return response.data.results;
}

export async function createService(
  payload: ServiceCreatePayload,
): Promise<Service> {
  const response = await api.post<Service>("/services/", payload);
  return response.data;
}

export async function getService(id: number): Promise<Service> {
  const response = await api.get<Service>(`/services/${id}/`);
  return response.data;
}

export async function updateService(
  id: number,
  payload: ServiceUpdatePayload,
): Promise<Service> {
  const response = await api.patch<Service>(`/services/${id}/`, payload);
  return response.data;
}

export async function deleteService(id: number): Promise<void> {
  await api.delete(`/services/${id}/`);
}

// ---- Sprint 28 Batch 5 — Per-customer pricing ---------------------------
//
// `/api/customers/<customer_id>/pricing/` — list + create.
// `/api/customers/<customer_id>/pricing/<price_id>/` — detail / update /
// delete.
//
// Backend permission gate: SUPER_ADMIN or COMPANY_ADMIN of the customer's
// provider company. Cross-provider COMPANY_ADMIN attempts return 403.
// Cross-customer price id smuggling is blocked by the detail view (404
// when the price's customer does not match the URL).
//
// List filter `?service=<id>` narrows the rows to one service. Default
// backend ordering is most-recent active row first, so a fresh PATCH
// floats to the top of the list without explicit re-sort.

export interface CustomerServicePriceListParams {
  service?: number;
}

export async function listCustomerPrices(
  customerId: number,
  params: CustomerServicePriceListParams = {},
): Promise<CustomerServicePrice[]> {
  const query: Record<string, string | number> = {};
  if (params.service !== undefined) {
    query.service = params.service;
  }
  const response = await api.get<PaginatedResponse<CustomerServicePrice>>(
    `/customers/${customerId}/pricing/`,
    { params: query },
  );
  return response.data.results;
}

export async function createCustomerPrice(
  customerId: number,
  payload: CustomerServicePriceCreatePayload,
): Promise<CustomerServicePrice> {
  const response = await api.post<CustomerServicePrice>(
    `/customers/${customerId}/pricing/`,
    payload,
  );
  return response.data;
}

export async function getCustomerPrice(
  customerId: number,
  priceId: number,
): Promise<CustomerServicePrice> {
  const response = await api.get<CustomerServicePrice>(
    `/customers/${customerId}/pricing/${priceId}/`,
  );
  return response.data;
}

export async function updateCustomerPrice(
  customerId: number,
  priceId: number,
  payload: CustomerServicePriceUpdatePayload,
): Promise<CustomerServicePrice> {
  const response = await api.patch<CustomerServicePrice>(
    `/customers/${customerId}/pricing/${priceId}/`,
    payload,
  );
  return response.data;
}

export async function deleteCustomerPrice(
  customerId: number,
  priceId: number,
): Promise<void> {
  await api.delete(`/customers/${customerId}/pricing/${priceId}/`);
}
