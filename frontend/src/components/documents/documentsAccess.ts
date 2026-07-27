// Sprint 126 — pure helpers for the Documents explorer: the two-sided
// editability rules (mirrors backend/documents/access.py), flat-list → tree,
// breadcrumb paths, and the upload/mutation error-code → i18n-key mapping.
import type { DocumentFile, DocumentFolder } from "../../api/types";

export type DocumentsSide = "provider" | "customer";

// --- editability (who may rename / move / delete a row) --------------------
// A customer may only touch rows they own (origin === "CUSTOMER") and never a
// system folder. A provider may touch any non-system folder (rename a system
// folder, but never move/delete it) and any file. Placement (create-in /
// upload-into / move-into) is allowed for anyone with access, system folders
// included, so it has no gate here.

export function canRenameFolder(
  side: DocumentsSide,
  folder: DocumentFolder,
): boolean {
  if (folder.is_system) return side === "provider";
  return side === "provider" || folder.origin === "CUSTOMER";
}

export function canMoveOrDeleteFolder(
  side: DocumentsSide,
  folder: DocumentFolder,
): boolean {
  if (folder.is_system) return false; // never moved/deleted by anyone
  return side === "provider" || folder.origin === "CUSTOMER";
}

export function canModifyFile(
  side: DocumentsSide,
  file: DocumentFile,
): boolean {
  return side === "provider" || file.origin === "CUSTOMER";
}

// --- tree shaping ----------------------------------------------------------

export interface FolderNode extends DocumentFolder {
  children: FolderNode[];
}

/** Build the folder forest from the flat `GET folders/` list. Roots first,
 *  each level sorted by the server order (name, id). System roots are hoisted
 *  to the front so the four defaults always lead. */
export function buildFolderTree(folders: DocumentFolder[]): FolderNode[] {
  const byId = new Map<number, FolderNode>();
  for (const f of folders) byId.set(f.id, { ...f, children: [] });
  const roots: FolderNode[] = [];
  for (const node of byId.values()) {
    if (node.parent !== null && byId.has(node.parent)) {
      byId.get(node.parent)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortLevel = (nodes: FolderNode[]) => {
    nodes.sort((a, b) => {
      if (a.is_system !== b.is_system) return a.is_system ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sortLevel(n.children);
  };
  sortLevel(roots);
  return roots;
}

/** Root → … → the folder with `folderId` (inclusive). Empty if not found. */
export function folderPath(
  folders: DocumentFolder[],
  folderId: number | null,
): DocumentFolder[] {
  if (folderId === null) return [];
  const byId = new Map<number, DocumentFolder>();
  for (const f of folders) byId.set(f.id, f);
  const chain: DocumentFolder[] = [];
  let current = byId.get(folderId) ?? null;
  let guard = 0;
  while (current && guard <= 32) {
    chain.unshift(current);
    current = current.parent !== null ? byId.get(current.parent) ?? null : null;
    guard += 1;
  }
  return chain;
}

/** ids of a folder and all its descendants — used to disable dropping a
 *  folder onto itself or one of its own descendants. */
export function folderAndDescendantIds(
  folders: DocumentFolder[],
  folderId: number,
): Set<number> {
  const childrenOf = new Map<number, number[]>();
  for (const f of folders) {
    if (f.parent !== null) {
      const list = childrenOf.get(f.parent) ?? [];
      list.push(f.id);
      childrenOf.set(f.parent, list);
    }
  }
  const out = new Set<number>();
  const stack = [folderId];
  let guard = 0;
  while (stack.length && guard <= 4096) {
    const id = stack.pop()!;
    if (out.has(id)) continue;
    out.add(id);
    for (const child of childrenOf.get(id) ?? []) stack.push(child);
    guard += 1;
  }
  return out;
}

// --- error code → i18n key -------------------------------------------------

const KNOWN_ERROR_CODES: ReadonlySet<string> = new Set([
  "document_too_large",
  "invalid_document_extension",
  "invalid_document_mime",
  "invalid_document_content",
  "invalid_ooxml_package",
  "invalid_text_encoding",
  "folder_name_conflict",
  "folder_depth_exceeded",
  "folder_cycle",
  "folder_not_empty",
  "system_folder_immovable",
  "system_folder_undeletable",
  "not_owner",
  "no_changes",
]);

/** i18n key for a documents error `code` (from `documentsErrorCode`), or the
 *  generic fallback for an unknown / missing code. */
export function documentErrorKey(code: string | null): string {
  if (code && KNOWN_ERROR_CODES.has(code)) {
    return `documents.errors.${code}`;
  }
  return "documents.errors.generic";
}

// --- drag payload (native HTML5 DnD) ---------------------------------------

export const DND_MIME = "application/x-osius-document";

export interface DndPayload {
  kind: "file" | "folder";
  id: string; // public_id for a file, String(id) for a folder
}
