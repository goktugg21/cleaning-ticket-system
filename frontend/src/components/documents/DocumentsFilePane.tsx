// Sprint 126 — the file pane for the selected folder. Keyed by folder+reload
// at the parent, so it remounts fresh on folder change or after a mutation
// (its files come from a mount effect — no synchronous setState). Bounded in
// a BoundedList. Rows: thumbnail (reused DocumentThumb), name, size, uploader,
// date, and — only for rows the actor owns — rename/move/delete. The pane is
// an OS-file dropzone for upload; internal drags target folders in the tree.
import { useEffect, useRef, useState } from "react";
import {
  Download,
  File as FileIcon,
  FolderInput,
  Lock,
  Pencil,
  Trash2,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { BoundedList } from "../BoundedList";
import { DocumentThumb } from "../DocumentThumb";
import { fileServeUrl, listFiles } from "../../api/documents";
import { formatDate } from "../../lib/intl";
import type { DocumentFile } from "../../api/types";
import {
  DND_MIME,
  type DndPayload,
  type DocumentsSide,
  canModifyFile,
} from "./documentsAccess";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

interface FilePaneProps {
  customerId: number;
  folderId: number;
  side: DocumentsSide;
  uploadName: string | null;
  uploadFraction: number;
  onUploadFiles: (files: File[]) => void;
  onPreview: (file: DocumentFile) => void;
  onRename: (file: DocumentFile) => void;
  onMove: (file: DocumentFile) => void;
  onDelete: (file: DocumentFile) => void;
  onDragStart: (payload: DndPayload) => void;
  onDragEnd: () => void;
}

export function DocumentsFilePane({
  customerId,
  folderId,
  side,
  uploadName,
  uploadFraction,
  onUploadFiles,
  onPreview,
  onRename,
  onMove,
  onDelete,
  onDragStart,
  onDragEnd,
}: FilePaneProps) {
  const { t } = useTranslation("common");
  const [files, setFiles] = useState<DocumentFile[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    listFiles(customerId, folderId)
      .then((rows) => {
        if (!cancelled) setFiles(rows);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId, folderId]);

  const handleDropFiles = (dropped: FileList | null) => {
    if (!dropped || dropped.length === 0) return;
    onUploadFiles(Array.from(dropped));
  };

  return (
    <div
      className={dragOver ? "doc-pane doc-pane-dragover" : "doc-pane"}
      data-testid="doc-file-pane"
      onDragOver={(event) => {
        // Only react to OS file drags (upload); internal moves go to folders.
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragOver(true);
        }
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragOver(false);
          handleDropFiles(event.dataTransfer.files);
        }
      }}
    >
      <div className="doc-pane-toolbar">
        <button
          type="button"
          className="btn btn-primary"
          data-testid="doc-upload-button"
          onClick={() => inputRef.current?.click()}
        >
          <Upload size={15} strokeWidth={2} />
          {t("documents.upload")}
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          data-testid="doc-upload-input"
          onChange={(event) => {
            handleDropFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <span className="doc-pane-hint">{t("documents.drop_hint")}</span>
      </div>

      {files !== null && files.length > 0 && (
        // Sprint 135 — native HTML5 drag-and-drop (used both here, for a
        // file->folder move, and above, for an OS file upload) never fires
        // on touch, and every row's move icon is the only path a tablet
        // user has. The icon was already always-visible (not hover-gated —
        // see .doc-file-actions in documents.css), so the gap was framing,
        // not capability: a reader who tries the intuitive drag gesture and
        // sees nothing happen has no way to know a working alternative
        // exists right next to it. State both paths explicitly rather than
        // building a second, touch-specific drag implementation (a real
        // pointer-event-based drag would still need a mouse-free rename/
        // move confirmation step anyway — the icon already provides one).
        <p className="doc-pane-hint" data-testid="doc-move-hint">
          {t("documents.move_hint")}
        </p>
      )}

      {uploadName !== null && (
        <div className="doc-upload-progress" data-testid="doc-upload-progress">
          <span className="doc-upload-name">{uploadName}</span>
          <span className="doc-progress-track">
            <span
              className="doc-progress-bar"
              style={{ width: `${Math.round(uploadFraction * 100)}%` }}
            />
          </span>
          <span className="doc-upload-pct">
            {Math.round(uploadFraction * 100)}%
          </span>
        </div>
      )}

      {loadError ? (
        <p className="form-error" role="alert">
          {t("documents.errors.load_files")}
        </p>
      ) : files === null ? (
        <p className="muted">{t("documents.loading")}</p>
      ) : files.length === 0 ? (
        <p className="muted" data-testid="doc-empty-folder">
          {t("documents.empty_folder")}
        </p>
      ) : (
        <BoundedList
          size="lg"
          count={files.length}
          ariaLabel={t("documents.files_label")}
          testIdPrefix="doc-files"
        >
          <ul className="doc-file-list">
            {files.map((file) => {
              const mine = canModifyFile(side, file);
              return (
                <li
                  key={file.public_id}
                  className="doc-file-row"
                  data-testid="doc-file-row"
                  data-origin={file.origin}
                  draggable={mine}
                  onDragStart={(event) => {
                    const payload: DndPayload = {
                      kind: "file",
                      id: file.public_id,
                    };
                    event.dataTransfer.setData(
                      DND_MIME,
                      JSON.stringify(payload),
                    );
                    event.dataTransfer.effectAllowed = "move";
                    onDragStart(payload);
                  }}
                  onDragEnd={onDragEnd}
                >
                  <button
                    type="button"
                    className="doc-file-main"
                    onClick={() => onPreview(file)}
                    title={t("documents.open_file")}
                  >
                    <span className="doc-file-thumb">
                      <DocumentThumb
                        url={fileServeUrl(customerId, file.public_id)}
                        mimeType={file.mime_type}
                        fallback={
                          <span className="doc-file-thumb-fallback">
                            <FileIcon size={18} strokeWidth={1.8} />
                          </span>
                        }
                      />
                    </span>
                    <span className="doc-file-meta">
                      <span className="doc-file-name">
                        {file.original_filename}
                      </span>
                      <span className="doc-file-sub">
                        {formatBytes(file.file_size)}
                        {" · "}
                        {file.uploaded_by_email ?? t("documents.uploader_system")}
                        {" · "}
                        {formatDate(file.created_at)}
                      </span>
                    </span>
                  </button>
                  <div className="doc-file-actions">
                    {mine ? (
                      <>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("documents.rename")}
                          data-testid="doc-file-rename"
                          onClick={() => onRename(file)}
                        >
                          <Pencil size={15} strokeWidth={2} />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("documents.move")}
                          data-testid="doc-file-move"
                          onClick={() => onMove(file)}
                        >
                          <FolderInput size={15} strokeWidth={2} />
                        </button>
                        <button
                          type="button"
                          className="icon-btn icon-btn-danger"
                          title={t("documents.delete")}
                          data-testid="doc-file-delete"
                          onClick={() => onDelete(file)}
                        >
                          <Trash2 size={15} strokeWidth={2} />
                        </button>
                      </>
                    ) : (
                      <>
                        <span
                          className="doc-readonly-tag"
                          title={t("documents.provider_readonly")}
                        >
                          <Lock size={13} strokeWidth={2} />
                          {t("documents.provider_label")}
                        </span>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("documents.download")}
                          onClick={() => onPreview(file)}
                        >
                          <Download size={15} strokeWidth={2} />
                        </button>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </BoundedList>
      )}
    </div>
  );
}
