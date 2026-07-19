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
