/**
 * Sprint 5 (frontend) — small textarea editor modal for the Extra Work
 * pricing-composer notes (customer-visible explanation + internal cost
 * note). Reuses the existing `.reject-modal*` modal pattern/CSS rather
 * than introducing a new modal library or CSS framework.
 *
 * Differences from `RejectReasonDialog` (why this is a separate
 * component instead of reusing it): the notes are OPTIONAL — an empty
 * save is allowed (clearing the note) — and the editor must SEED from
 * the current value so re-opening shows existing text. The parent
 * mounts this component only while open (`{open && <NoteEditorDialog/>}`)
 * so `useState(initialValue)` re-seeds on every open with no effect.
 *
 * Headless w.r.t. page state: the caller controls mounting and supplies
 * `onSave(value)` / `onCancel`.
 */
import { useState } from "react";

export interface NoteEditorDialogProps {
  title: string;
  initialValue: string;
  saveLabel: string;
  cancelLabel: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  description?: string;
  placeholder?: string;
  testId?: string;
}

export function NoteEditorDialog({
  title,
  initialValue,
  saveLabel,
  cancelLabel,
  onSave,
  onCancel,
  description,
  placeholder,
  testId = "note-editor-dialog",
}: NoteEditorDialogProps) {
  const [value, setValue] = useState(initialValue);

  return (
    <div
      className="reject-modal-backdrop"
      data-testid={testId}
      role="dialog"
      aria-modal="true"
    >
      <div className="reject-modal">
        <h3 className="reject-modal-title">{title}</h3>
        {description && <p className="reject-modal-desc">{description}</p>}
        <textarea
          data-testid="note-editor-textarea"
          className="field-textarea reject-modal-textarea"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          rows={4}
          autoFocus
        />
        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="note-editor-cancel"
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="note-editor-save"
            onClick={() => onSave(value)}
          >
            {saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
