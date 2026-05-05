import { api } from "./client";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  CompanyAdmin,
  CompanyAdminMembership,
  CustomerAdmin,
  CustomerUserMembership,
  InvitationAdmin,
  PaginatedResponse,
  Role,
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
