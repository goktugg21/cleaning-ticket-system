// M2 P4 — typed client for the P3 staff-credential / custom-property
// admin API under /api/users/<id>/credentials|properties/.
//
// Contract notes (backend/accounts/serializers_credentials.py):
//   - credential_type is IMMUTABLE after create (PATCH carrying it -> 400),
//     so the update payload type simply does not have the field.
//   - Document uploads are PDF-only and <=10MB; the metadata trio
//     (original_filename / mime_type / file_size) is server-derived and
//     read-only on the wire.
//   - EU_NATIONAL_ID is locked to PA_SA_ONLY with the photocopy flag
//     forced off; the UI never offers those controls, and the create
//     path omits both fields for that type.
//   - Grant POST is idempotent (200 on duplicate, 201 on create).
import { api } from "./client";

export type CredentialType = "RESIDENCE_PERMIT" | "EU_NATIONAL_ID" | "VCA";

export type CredentialVisibilityLevel =
  | "PA_SA_ONLY"
  | "PROVIDER_ONLY"
  | "CUSTOMER_VISIBLE";

export const CREDENTIAL_TYPES: CredentialType[] = [
  "RESIDENCE_PERMIT",
  "EU_NATIONAL_ID",
  "VCA",
];

export const CREDENTIAL_VISIBILITY_LEVELS: CredentialVisibilityLevel[] = [
  "PA_SA_ONLY",
  "PROVIDER_ONLY",
  "CUSTOMER_VISIBLE",
];

// Mirrors the backend MAX_DOCUMENT_SIZE (10 MB, same as ticket
// attachments). Client-side check is fast feedback only — the backend
// re-validates.
export const MAX_CREDENTIAL_DOCUMENT_BYTES = 10 * 1024 * 1024;

export interface CredentialGrant {
  id: number;
  customer_id: number;
  customer_name: string;
  created_at: string;
}

export interface StaffCredential {
  id: number;
  credential_type: CredentialType;
  permit_number: string;
  expiry_date: string | null;
  visibility_level: CredentialVisibilityLevel;
  document_customer_visible: boolean;
  has_document: boolean;
  original_filename: string;
  mime_type: string;
  file_size: number | null;
  document_url: string | null;
  grants: CredentialGrant[];
  created_at: string;
  updated_at: string;
}

export interface CustomProfileProperty {
  id: number;
  name: string;
  value: string;
  visibility_level: CredentialVisibilityLevel;
  has_document: boolean;
  original_filename: string;
  mime_type: string;
  file_size: number | null;
  document_url: string | null;
  grants: CredentialGrant[];
  created_at: string;
  updated_at: string;
}

export interface CredentialCreatePayload {
  credential_type: CredentialType;
  permit_number?: string;
  expiry_date?: string | null;
  visibility_level?: CredentialVisibilityLevel;
  document_customer_visible?: boolean;
  document?: File | null;
}

export interface CredentialUpdatePayload {
  permit_number?: string;
  expiry_date?: string | null;
  visibility_level?: CredentialVisibilityLevel;
  document_customer_visible?: boolean;
  document?: File | null;
}

export interface PropertyWritePayload {
  name?: string;
  value?: string;
  visibility_level?: CredentialVisibilityLevel;
  document?: File | null;
}

/** Returns true when `file` passes the fast client-side PDF rule
 *  (.pdf extension AND <=10MB). The backend re-validates both plus the
 *  declared MIME type. */
export function isAcceptablePdf(file: File): boolean {
  return (
    file.name.toLowerCase().endsWith(".pdf") &&
    file.size <= MAX_CREDENTIAL_DOCUMENT_BYTES
  );
}

type WireValue = string | boolean | null | undefined;

/** Build the request body: multipart only when a File rides along
 *  (mirrors the ticket-attachment upload pattern), plain JSON
 *  otherwise. Multipart skips null/undefined/empty-string values —
 *  "not sent" means "unchanged" on PATCH and "model default" on POST;
 *  explicit nulls (e.g. clearing expiry_date) work via the JSON path. */
function buildBody(
  fields: Record<string, WireValue>,
  document: File | null | undefined,
): { body: FormData | Record<string, WireValue>; multipart: boolean } {
  if (document instanceof File) {
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) {
      if (value === undefined || value === null || value === "") continue;
      form.append(key, typeof value === "boolean" ? String(value) : value);
    }
    form.append("document", document);
    return { body: form, multipart: true };
  }
  const json: Record<string, WireValue> = {};
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined) continue;
    json[key] = value;
  }
  return { body: json, multipart: false };
}

function postConfig(multipart: boolean) {
  return multipart
    ? { headers: { "Content-Type": "multipart/form-data" } }
    : undefined;
}

/** Shared blob-download trigger (TicketDetailPage downloadAttachment
 *  pattern: responseType blob + createObjectURL + synthetic click). */
async function downloadToFile(url: string, filename: string): Promise<void> {
  const response = await api.get(url, { responseType: "blob" });
  const blobUrl = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

/** M2 P5 — download from a backend-emitted `document_url`. The ticket
 *  payload carries Django reverse() paths beginning "/api/..." while
 *  the axios baseURL already ends in "/api" — strip the prefix so the
 *  request does not become /api/api/... . */
export async function downloadDocumentFromUrl(
  documentUrl: string,
  filename = "document.pdf",
): Promise<void> {
  const path = documentUrl.startsWith("/api/")
    ? documentUrl.slice("/api".length)
    : documentUrl;
  await downloadToFile(path, filename);
}

// ---------------------------------------------------------------------------
// Credentials (STAFF targets only)
// ---------------------------------------------------------------------------

export async function listCredentials(
  userId: number,
): Promise<StaffCredential[]> {
  const response = await api.get(`/users/${userId}/credentials/`);
  return response.data;
}

export async function createCredential(
  userId: number,
  payload: CredentialCreatePayload,
): Promise<StaffCredential> {
  const { document: file, ...fields } = payload;
  const { body, multipart } = buildBody(fields, file);
  const response = await api.post(
    `/users/${userId}/credentials/`,
    body,
    postConfig(multipart),
  );
  return response.data;
}

export async function updateCredential(
  userId: number,
  credentialId: number,
  payload: CredentialUpdatePayload,
): Promise<StaffCredential> {
  const { document: file, ...fields } = payload;
  const { body, multipart } = buildBody(fields, file);
  const response = await api.patch(
    `/users/${userId}/credentials/${credentialId}/`,
    body,
    postConfig(multipart),
  );
  return response.data;
}

export async function removeCredential(
  userId: number,
  credentialId: number,
): Promise<void> {
  await api.delete(`/users/${userId}/credentials/${credentialId}/`);
}

export async function listCredentialGrants(
  userId: number,
  credentialId: number,
): Promise<CredentialGrant[]> {
  const response = await api.get(
    `/users/${userId}/credentials/${credentialId}/grants/`,
  );
  return response.data;
}

export async function createCredentialGrant(
  userId: number,
  credentialId: number,
  customerId: number,
): Promise<CredentialGrant> {
  const response = await api.post(
    `/users/${userId}/credentials/${credentialId}/grants/`,
    { customer_id: customerId },
  );
  return response.data;
}

export async function removeCredentialGrant(
  userId: number,
  credentialId: number,
  grantId: number,
): Promise<void> {
  await api.delete(
    `/users/${userId}/credentials/${credentialId}/grants/${grantId}/`,
  );
}

export async function downloadCredentialDocument(
  userId: number,
  credential: StaffCredential,
): Promise<void> {
  await downloadToFile(
    `/users/${userId}/credentials/${credential.id}/download/`,
    credential.original_filename || "document.pdf",
  );
}

// ---------------------------------------------------------------------------
// Custom profile properties (any target user)
// ---------------------------------------------------------------------------

export async function listProperties(
  userId: number,
): Promise<CustomProfileProperty[]> {
  const response = await api.get(`/users/${userId}/properties/`);
  return response.data;
}

export async function createProperty(
  userId: number,
  payload: PropertyWritePayload,
): Promise<CustomProfileProperty> {
  const { document: file, ...fields } = payload;
  const { body, multipart } = buildBody(fields, file);
  const response = await api.post(
    `/users/${userId}/properties/`,
    body,
    postConfig(multipart),
  );
  return response.data;
}

export async function updateProperty(
  userId: number,
  propertyId: number,
  payload: PropertyWritePayload,
): Promise<CustomProfileProperty> {
  const { document: file, ...fields } = payload;
  const { body, multipart } = buildBody(fields, file);
  const response = await api.patch(
    `/users/${userId}/properties/${propertyId}/`,
    body,
    postConfig(multipart),
  );
  return response.data;
}

export async function removeProperty(
  userId: number,
  propertyId: number,
): Promise<void> {
  await api.delete(`/users/${userId}/properties/${propertyId}/`);
}

export async function listPropertyGrants(
  userId: number,
  propertyId: number,
): Promise<CredentialGrant[]> {
  const response = await api.get(
    `/users/${userId}/properties/${propertyId}/grants/`,
  );
  return response.data;
}

export async function createPropertyGrant(
  userId: number,
  propertyId: number,
  customerId: number,
): Promise<CredentialGrant> {
  const response = await api.post(
    `/users/${userId}/properties/${propertyId}/grants/`,
    { customer_id: customerId },
  );
  return response.data;
}

export async function removePropertyGrant(
  userId: number,
  propertyId: number,
  grantId: number,
): Promise<void> {
  await api.delete(
    `/users/${userId}/properties/${propertyId}/grants/${grantId}/`,
  );
}

export async function downloadPropertyDocument(
  userId: number,
  property: CustomProfileProperty,
): Promise<void> {
  await downloadToFile(
    `/users/${userId}/properties/${property.id}/download/`,
    property.original_filename || "document.pdf",
  );
}
