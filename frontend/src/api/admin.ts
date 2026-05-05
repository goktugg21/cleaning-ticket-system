import { api } from "./client";
import type {
  BuildingAdmin,
  CompanyAdmin,
  CustomerAdmin,
  PaginatedResponse,
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
