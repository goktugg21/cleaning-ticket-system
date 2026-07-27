// Sprint 126 — the small modals for the Documents explorer: a name prompt
// (create folder / rename folder or file) and a "Move to…" folder picker.
// Both clone the NoteEditorDialog pattern — a plain overlay mounted only
// while open (so `useState` re-seeds each open with no effect and there is no
// native-<dialog> unmount hazard). Busy/error are driven by the parent, which
// keeps the modal mounted across the async call so the input is preserved on
// a failed save.
import { useState } from "react";
import { useTranslation } from "react-i18next";

export interface MoveOption {
  id: number;
  label: string; // depth-indented folder name
}

export function DocumentNameDialog({
  title,
  initialValue,
  saveLabel,
  error,
  busy,
  onSave,
  onCancel,
}: {
  title: string;
  initialValue: string;
  saveLabel: string;
  error: string | null;
  busy: boolean;
  onSave: (value: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("common");
  const [value, setValue] = useState(initialValue);
  const trimmed = value.trim();

  return (
    <div
      className="reject-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="doc-name-dialog"
    >
      <div className="reject-modal">
        <h3 className="reject-modal-title">{title}</h3>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <input
          className="field-input"
          data-testid="doc-name-input"
          value={value}
          autoFocus
          disabled={busy}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && trimmed && !busy) onSave(trimmed);
          }}
        />
        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
          >
            {t("documents.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="doc-name-save"
            disabled={!trimmed || busy}
            onClick={() => onSave(trimmed)}
          >
            {saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function DocumentMoveDialog({
  title,
  options,
  initialFolderId,
  error,
  busy,
  onMove,
  onCancel,
}: {
  title: string;
  options: MoveOption[];
  initialFolderId: number | null;
  error: string | null;
  busy: boolean;
  onMove: (folderId: number) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("common");
  const [selected, setSelected] = useState<number | null>(
    initialFolderId ?? options[0]?.id ?? null,
  );

  return (
    <div
      className="reject-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="doc-move-dialog"
    >
      <div className="reject-modal">
        <h3 className="reject-modal-title">{title}</h3>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {options.length === 0 ? (
          <p className="muted">{t("documents.move_no_target")}</p>
        ) : (
          <select
            className="field-input"
            data-testid="doc-move-select"
            value={selected ?? ""}
            disabled={busy}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        )}
        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
          >
            {t("documents.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="doc-move-confirm"
            disabled={selected === null || busy}
            onClick={() => {
              if (selected !== null) onMove(selected);
            }}
          >
            {t("documents.move")}
          </button>
        </div>
      </div>
    </div>
  );
}
