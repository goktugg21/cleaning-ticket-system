// Sprint 126 — the shared Documents explorer, used by BOTH the provider
// sub-tab and the customer page (the only difference is `side`, which drives
// which rows are editable — the whole two-sided ownership split lives in
// documentsAccess.ts, not in two forked screens). File-explorer layout: a
// folder tree, a bounded file pane, breadcrumbs, upload (button + drop),
// inline preview for PDFs/images, and rename/move/delete + drag-move. The
// server owns the hard rules (cycle, depth, ownership); the UI surfaces the
// coded errors and disables the obviously-invalid drop targets for feel.
import { useEffect, useMemo, useRef, useState } from "react";
import { FolderPlus, Pencil, FolderInput, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import "./documents.css";
import {
  createFolder,
  deleteFile,
  deleteFolder,
  documentsErrorCode,
  fileServeUrl,
  listFolders,
  updateFile,
  updateFolder,
  uploadFile,
} from "../../api/documents";
import type { DocumentFile, DocumentFolder } from "../../api/types";
import { ConfirmDialog } from "../ConfirmDialog";
import type { ConfirmDialogHandle } from "../ConfirmDialog";
import { PdfPreviewDialog } from "../PdfPreviewDialog";
import type { PdfPreviewDialogHandle } from "../PdfPreviewDialog";
import { DocumentsFilePane } from "./DocumentsFilePane";
import { DocumentsFolderTree } from "./DocumentsFolderTree";
import {
  DocumentMoveDialog,
  DocumentNameDialog,
  type MoveOption,
} from "./DocumentsDialogs";
import {
  buildFolderTree,
  canMoveOrDeleteFolder,
  canRenameFolder,
  documentErrorKey,
  folderAndDescendantIds,
  folderPath,
  type DndPayload,
  type DocumentsSide,
} from "./documentsAccess";

const PREVIEW_MIME = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/webp",
]);

type NameDialogState =
  | {
      mode: "createFolder" | "renameFolder" | "renameFile";
      folder?: DocumentFolder;
      file?: DocumentFile;
      parentId?: number | null;
      initial: string;
      error: string | null;
      busy: boolean;
    }
  | null;

type MoveDialogState =
  | {
      folder?: DocumentFolder;
      file?: DocumentFile;
      error: string | null;
      busy: boolean;
    }
  | null;

type DeleteTarget =
  | { kind: "folder"; folder: DocumentFolder }
  | { kind: "file"; file: DocumentFile }
  | null;

function firstFolderId(folders: DocumentFolder[]): number | null {
  const tree = buildFolderTree(folders);
  return tree[0]?.id ?? null;
}

/** depth-indented select options for the "Move to…" dialog. */
function moveOptions(
  folders: DocumentFolder[],
  excludeIds: Set<number>,
): MoveOption[] {
  const tree = buildFolderTree(folders);
  const out: MoveOption[] = [];
  const walk = (nodes: typeof tree, depth: number) => {
    for (const node of nodes) {
      if (!excludeIds.has(node.id)) {
        out.push({
          id: node.id,
          label: `${"– ".repeat(depth)}${node.name}`,
        });
      }
      walk(node.children, depth + 1);
    }
  };
  walk(tree, 0);
  return out;
}

export function DocumentsExplorer({
  customerId,
  side,
}: {
  customerId: number;
  side: DocumentsSide;
}) {
  const { t } = useTranslation("common");
  const [folders, setFolders] = useState<DocumentFolder[] | null>(null);
  const [foldersError, setFoldersError] = useState(false);
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [dragging, setDragging] = useState<DndPayload | null>(null);
  const [upload, setUpload] = useState<{ name: string; fraction: number } | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [nameDialog, setNameDialog] = useState<NameDialogState>(null);
  const [moveDialog, setMoveDialog] = useState<MoveDialogState>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null);

  const previewRef = useRef<PdfPreviewDialogHandle>(null);
  const confirmRef = useRef<ConfirmDialogHandle>(null);

  useEffect(() => {
    let cancelled = false;
    listFolders(customerId)
      .then((rows) => {
        if (cancelled) return;
        setFolders(rows);
        setSelectedFolderId((prev) =>
          prev !== null && rows.some((f) => f.id === prev)
            ? prev
            : firstFolderId(rows),
        );
      })
      .catch(() => {
        if (!cancelled) setFoldersError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);
  const describeError = (error: unknown) =>
    t(documentErrorKey(documentsErrorCode(error)));

  const tree = useMemo(
    () => (folders ? buildFolderTree(folders) : []),
    [folders],
  );
  const selectedFolder = useMemo(
    () => folders?.find((f) => f.id === selectedFolderId) ?? null,
    [folders, selectedFolderId],
  );
  const breadcrumbs = useMemo(
    () => folderPath(folders ?? [], selectedFolderId),
    [folders, selectedFolderId],
  );

  // --- folder toolbar actions --------------------------------------------

  const openCreateFolder = () =>
    setNameDialog({
      mode: "createFolder",
      parentId: selectedFolderId,
      initial: "",
      error: null,
      busy: false,
    });

  const openRenameFolder = (folder: DocumentFolder) =>
    setNameDialog({
      mode: "renameFolder",
      folder,
      initial: folder.name,
      error: null,
      busy: false,
    });

  const openRenameFile = (file: DocumentFile) =>
    setNameDialog({
      mode: "renameFile",
      file,
      initial: file.original_filename,
      error: null,
      busy: false,
    });

  const submitName = async (value: string) => {
    if (!nameDialog) return;
    setNameDialog({ ...nameDialog, busy: true, error: null });
    try {
      if (nameDialog.mode === "createFolder") {
        await createFolder(customerId, {
          name: value,
          parent: nameDialog.parentId ?? null,
        });
      } else if (nameDialog.mode === "renameFolder" && nameDialog.folder) {
        await updateFolder(customerId, nameDialog.folder.id, { name: value });
      } else if (nameDialog.mode === "renameFile" && nameDialog.file) {
        await updateFile(customerId, nameDialog.file.public_id, {
          original_filename: value,
        });
      }
      setNameDialog(null);
      reload();
    } catch (error) {
      setNameDialog((prev) =>
        prev ? { ...prev, busy: false, error: describeError(error) } : prev,
      );
    }
  };

  // --- move (dialog + drag/drop) -----------------------------------------

  const openMoveFolder = (folder: DocumentFolder) =>
    setMoveDialog({ folder, error: null, busy: false });
  const openMoveFile = (file: DocumentFile) =>
    setMoveDialog({ file, error: null, busy: false });

  const moveDialogOptions = useMemo<MoveOption[]>(() => {
    if (!moveDialog || !folders) return [];
    if (moveDialog.folder) {
      return moveOptions(
        folders,
        folderAndDescendantIds(folders, moveDialog.folder.id),
      );
    }
    return moveOptions(folders, new Set());
  }, [moveDialog, folders]);

  const submitMove = async (destinationId: number) => {
    if (!moveDialog) return;
    setMoveDialog({ ...moveDialog, busy: true, error: null });
    try {
      if (moveDialog.folder) {
        await updateFolder(customerId, moveDialog.folder.id, {
          parent: destinationId,
        });
      } else if (moveDialog.file) {
        await updateFile(customerId, moveDialog.file.public_id, {
          folder: destinationId,
        });
      }
      setMoveDialog(null);
      reload();
    } catch (error) {
      setMoveDialog((prev) =>
        prev ? { ...prev, busy: false, error: describeError(error) } : prev,
      );
    }
  };

  const handleDropOnFolder = async (
    targetFolderId: number,
    payload: DndPayload,
  ) => {
    setDragging(null);
    setActionError(null);
    try {
      if (payload.kind === "file") {
        await updateFile(customerId, payload.id, { folder: targetFolderId });
      } else {
        await updateFolder(customerId, Number(payload.id), {
          parent: targetFolderId,
        });
      }
      reload();
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  // --- delete -------------------------------------------------------------

  const requestDeleteFolder = (folder: DocumentFolder) => {
    setDeleteTarget({ kind: "folder", folder });
    confirmRef.current?.open();
  };
  const requestDeleteFile = (file: DocumentFile) => {
    setDeleteTarget({ kind: "file", file });
    confirmRef.current?.open();
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      if (deleteTarget.kind === "folder") {
        await deleteFolder(customerId, deleteTarget.folder.id);
        if (deleteTarget.folder.id === selectedFolderId) {
          setSelectedFolderId(deleteTarget.folder.parent);
        }
      } else {
        await deleteFile(customerId, deleteTarget.file.public_id);
      }
      confirmRef.current?.close();
      setDeleteTarget(null);
      reload();
    } catch (error) {
      confirmRef.current?.close();
      setDeleteTarget(null);
      setActionError(describeError(error));
    }
  };

  // --- upload + preview ---------------------------------------------------

  const handleUploadFiles = async (files: File[]) => {
    if (selectedFolderId === null) return;
    setActionError(null);
    try {
      for (const file of files) {
        setUpload({ name: file.name, fraction: 0 });
        await uploadFile(customerId, selectedFolderId, file, (fraction) =>
          setUpload({ name: file.name, fraction }),
        );
      }
      setUpload(null);
      reload();
    } catch (error) {
      setUpload(null);
      setActionError(describeError(error));
    }
  };

  const handlePreview = async (file: DocumentFile) => {
    const url = fileServeUrl(customerId, file.public_id);
    if (PREVIEW_MIME.has(file.mime_type)) {
      previewRef.current?.open({ url, filename: file.original_filename });
      return;
    }
    // Non-previewable: authenticated blob download.
    try {
      const response = await api.get(url, { responseType: "blob" });
      const objectUrl = URL.createObjectURL(response.data as Blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = file.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  // --- render -------------------------------------------------------------

  if (foldersError) {
    return (
      <p className="form-error" role="alert">
        {t("documents.errors.load_folders")}
      </p>
    );
  }
  if (folders === null) {
    return <p className="muted">{t("documents.loading")}</p>;
  }

  const canRename = selectedFolder && canRenameFolder(side, selectedFolder);
  const canMoveDelete =
    selectedFolder && canMoveOrDeleteFolder(side, selectedFolder);

  return (
    <div className="doc-explorer" data-testid="documents-explorer">
      {actionError && (
        <p className="form-error" role="alert" data-testid="doc-action-error">
          {actionError}
        </p>
      )}
      <div className="doc-explorer-body">
        <aside className="doc-explorer-tree">
          <div className="doc-tree-toolbar">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="doc-new-folder"
              onClick={openCreateFolder}
            >
              <FolderPlus size={15} strokeWidth={2} />
              {t("documents.new_folder")}
            </button>
          </div>
          <DocumentsFolderTree
            side={side}
            tree={tree}
            allFolders={folders}
            selectedFolderId={selectedFolderId}
            dragging={dragging}
            onSelect={setSelectedFolderId}
            onDragStart={setDragging}
            onDragEnd={() => setDragging(null)}
            onDropOnFolder={handleDropOnFolder}
          />
        </aside>

        <section className="doc-explorer-main">
          <div className="doc-breadcrumbs" data-testid="doc-breadcrumbs">
            {breadcrumbs.length === 0 ? (
              <span className="muted">{t("documents.no_selection")}</span>
            ) : (
              breadcrumbs.map((crumb, index) => (
                <span key={crumb.id} className="doc-crumb">
                  {index > 0 && <span className="doc-crumb-sep">/</span>}
                  <button
                    type="button"
                    className="doc-crumb-btn"
                    onClick={() => setSelectedFolderId(crumb.id)}
                  >
                    {crumb.name}
                  </button>
                </span>
              ))
            )}
            {selectedFolder && (
              <span className="doc-folder-actions">
                {canRename && (
                  <button
                    type="button"
                    className="icon-btn"
                    title={t("documents.rename")}
                    data-testid="doc-folder-rename"
                    onClick={() => openRenameFolder(selectedFolder)}
                  >
                    <Pencil size={15} strokeWidth={2} />
                  </button>
                )}
                {canMoveDelete && (
                  <button
                    type="button"
                    className="icon-btn"
                    title={t("documents.move")}
                    data-testid="doc-folder-move"
                    onClick={() => openMoveFolder(selectedFolder)}
                  >
                    <FolderInput size={15} strokeWidth={2} />
                  </button>
                )}
                {canMoveDelete && (
                  <button
                    type="button"
                    className="icon-btn icon-btn-danger"
                    title={t("documents.delete")}
                    data-testid="doc-folder-delete"
                    onClick={() => requestDeleteFolder(selectedFolder)}
                  >
                    <Trash2 size={15} strokeWidth={2} />
                  </button>
                )}
              </span>
            )}
          </div>

          {selectedFolderId === null ? (
            <p className="muted">{t("documents.no_folders")}</p>
          ) : (
            <DocumentsFilePane
              key={`${selectedFolderId}:${reloadKey}`}
              customerId={customerId}
              folderId={selectedFolderId}
              side={side}
              uploadName={upload?.name ?? null}
              uploadFraction={upload?.fraction ?? 0}
              onUploadFiles={handleUploadFiles}
              onPreview={handlePreview}
              onRename={openRenameFile}
              onMove={openMoveFile}
              onDelete={requestDeleteFile}
              onDragStart={setDragging}
              onDragEnd={() => setDragging(null)}
            />
          )}
        </section>
      </div>

      {nameDialog && (
        <DocumentNameDialog
          title={t(
            nameDialog.mode === "createFolder"
              ? "documents.new_folder_title"
              : nameDialog.mode === "renameFolder"
                ? "documents.rename_folder_title"
                : "documents.rename_file_title",
          )}
          initialValue={nameDialog.initial}
          saveLabel={t(
            nameDialog.mode === "createFolder"
              ? "documents.create"
              : "documents.save",
          )}
          error={nameDialog.error}
          busy={nameDialog.busy}
          onSave={submitName}
          onCancel={() => setNameDialog(null)}
        />
      )}

      {moveDialog && (
        <DocumentMoveDialog
          title={t(
            moveDialog.folder
              ? "documents.move_folder_title"
              : "documents.move_file_title",
          )}
          options={moveDialogOptions}
          initialFolderId={moveDialog.file?.folder ?? null}
          error={moveDialog.error}
          busy={moveDialog.busy}
          onMove={submitMove}
          onCancel={() => setMoveDialog(null)}
        />
      )}

      <ConfirmDialog
        ref={confirmRef}
        title={t(
          deleteTarget?.kind === "folder"
            ? "documents.delete_folder_title"
            : "documents.delete_file_title",
        )}
        body={
          deleteTarget?.kind === "folder"
            ? t("documents.delete_folder_body", {
                name: deleteTarget.folder.name,
              })
            : deleteTarget?.kind === "file"
              ? t("documents.delete_file_body", {
                  name: deleteTarget.file.original_filename,
                })
              : ""
        }
        confirmLabel={t("documents.delete")}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
        destructive
      />

      <PdfPreviewDialog ref={previewRef} />
    </div>
  );
}
