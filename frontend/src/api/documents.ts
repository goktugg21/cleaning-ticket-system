// Sprint 126 — typed client for the customer Documents API.
//
// Backend: backend/documents/views.py, mounted under
// /api/customers/<customerId>/documents/. Folders are addressed by their
// integer pk; files by their opaque public_id (never the row pk). Every
// error the UI needs to localize comes back as { detail, code } — use
// `documentsErrorCode` to read the stable `code`.
import axios from "axios";

import { api } from "./client";
import type { DocumentFile, DocumentFolder, PaginatedResponse } from "./types";

function base(customerId: number | string): string {
  return `/customers/${customerId}/documents`;
}

/** Relative GET path (under the api client's baseURL) that streams a file's
 *  bytes — feed it to DocumentThumb / PdfPreviewDialog. */
export function fileServeUrl(
  customerId: number | string,
  publicId: string,
): string {
  return `${base(customerId)}/files/${publicId}/`;
}

export async function listFolders(
  customerId: number | string,
): Promise<DocumentFolder[]> {
  const response = await api.get<DocumentFolder[]>(`${base(customerId)}/folders/`);
  return response.data;
}

export async function listFiles(
  customerId: number | string,
  folderId: number,
): Promise<DocumentFile[]> {
  // Sprint 134 — the backend now paginates this endpoint (it used to
  // return every row in one response); page exhaustively so a folder
  // with more than one page of files never silently truncates. Mirrors
  // api/extraWork.ts::listAllExtraWork's exhaustive-fetch template. The
  // return type stays a bare array, so DocumentsFilePane needs no change.
  const all: DocumentFile[] = [];
  let page = 1;
  for (let i = 0; i < 100; i++) {
    const response = await api.get<PaginatedResponse<DocumentFile>>(
      `${base(customerId)}/files/`,
      { params: { folder: folderId, page_size: 100, page } },
    );
    all.push(...response.data.results);
    if (!response.data.next) break;
    page += 1;
  }
  return all;
}

export async function createFolder(
  customerId: number | string,
  payload: { name: string; parent?: number | null },
): Promise<DocumentFolder> {
  const response = await api.post<DocumentFolder>(
    `${base(customerId)}/folders/`,
    payload,
  );
  return response.data;
}

export interface FolderUpdatePayload {
  name?: string;
  // Present (even as null) means MOVE; null moves to root. Omit to leave put.
  parent?: number | null;
}

export async function updateFolder(
  customerId: number | string,
  folderId: number,
  payload: FolderUpdatePayload,
): Promise<DocumentFolder> {
  const response = await api.patch<DocumentFolder>(
    `${base(customerId)}/folders/${folderId}/`,
    payload,
  );
  return response.data;
}

export async function deleteFolder(
  customerId: number | string,
  folderId: number,
): Promise<void> {
  await api.delete(`${base(customerId)}/folders/${folderId}/`);
}

export async function uploadFile(
  customerId: number | string,
  folderId: number,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<DocumentFile> {
  const form = new FormData();
  form.append("folder", String(folderId));
  form.append("file", file);
  const response = await api.post<DocumentFile>(
    `${base(customerId)}/files/`,
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(event.loaded / event.total);
        }
      },
    },
  );
  return response.data;
}

export interface FileUpdatePayload {
  original_filename?: string;
  // Present means MOVE to that folder.
  folder?: number;
}

export async function updateFile(
  customerId: number | string,
  publicId: string,
  payload: FileUpdatePayload,
): Promise<DocumentFile> {
  const response = await api.patch<DocumentFile>(
    `${base(customerId)}/files/${publicId}/`,
    payload,
  );
  return response.data;
}

export async function deleteFile(
  customerId: number | string,
  publicId: string,
): Promise<void> {
  await api.delete(`${base(customerId)}/files/${publicId}/`);
}

/** The stable `code` from a documents API error ({ detail, code }), or null
 *  when the error is not a coded documents response. */
export function documentsErrorCode(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (data && typeof data === "object" && "code" in data) {
      const code = (data as { code?: unknown }).code;
      if (typeof code === "string") return code;
    }
  }
  return null;
}
