// RF-1 — profile-photo / customer-logo / company-logo upload + remove.
//
// Uploads are multipart with a single `file` part; the backend returns
// the new absolute URL (with a fresh ?v= marker so the avatar cache
// refetches exactly once).
import { api } from "./client";

async function uploadImage(url: string, file: File): Promise<string | null> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<{ profile_photo_url?: string; logo_url?: string }>(
    url,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data.profile_photo_url ?? response.data.logo_url ?? null;
}

export function uploadProfilePhoto(userId: number, file: File) {
  return uploadImage(`/users/${userId}/photo/`, file);
}

export async function deleteProfilePhoto(userId: number): Promise<void> {
  await api.delete(`/users/${userId}/photo/`);
}

export function uploadCustomerLogo(customerId: number, file: File) {
  return uploadImage(`/customers/${customerId}/logo/`, file);
}

export async function deleteCustomerLogo(customerId: number): Promise<void> {
  await api.delete(`/customers/${customerId}/logo/`);
}

export function uploadCompanyLogo(companyId: number, file: File) {
  return uploadImage(`/companies/${companyId}/logo/`, file);
}

export async function deleteCompanyLogo(companyId: number): Promise<void> {
  await api.delete(`/companies/${companyId}/logo/`);
}

// Invoicing Phase 4b — the customer informational contract PDF (multipart
// `file`, application/pdf). Upload returns the new contract-PDF URL (with a
// fresh ?v= marker); mirrors the logo upload but with its own response key.
export async function uploadCustomerContractPdf(
  customerId: number,
  file: File,
): Promise<string | null> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<{ contract_pdf_url?: string }>(
    `/customers/${customerId}/contract-pdf/`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data.contract_pdf_url ?? null;
}

export async function deleteCustomerContractPdf(
  customerId: number,
): Promise<void> {
  await api.delete(`/customers/${customerId}/contract-pdf/`);
}
