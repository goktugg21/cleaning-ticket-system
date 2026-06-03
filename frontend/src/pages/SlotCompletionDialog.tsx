// Phase B Part C — staff slot completion dialog with photo-evidence.
//
// Backend enforces evidence: slot_status=COMPLETED requires a non-empty
// completion_note OR >=1 linked PHOTO attachment (image MIME + image
// extension; PDF never counts). Photo linking is a TWO-STEP flow:
//   1. POST /tickets/<ticket_id>/attachments/ (multipart) with write-only
//      staff_assignment_id=<slot id> for each photo;
//   2. PATCH /tickets/<ticket_id>/staff-assignments/<my user id>/ with
//      slot_status=COMPLETED (+ completion_note).
// We pre-validate "note or photo" client-side for UX but ALSO surface the
// backend error messages (completion_evidence_required, invalid_file_mime_pair,
// slot_not_owned, slot_ticket_mismatch) if a request 400s.
import type { ChangeEvent } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../api/client";
import { updateStaffSlot } from "../api/admin";
import type { MySlot } from "../api/admin";

const ACCEPTED_PHOTO_TYPES = ".jpg,.jpeg,.png,.webp,.heic,.heif";
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

export function SlotCompletionDialog({
  slot,
  userId,
  onCancel,
  onDone,
}: {
  slot: MySlot;
  userId: number;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const hasEvidence = note.trim().length > 0 || files.length > 0;

  async function handleSubmit() {
    if (!hasEvidence) {
      setError(t("complete.evidence_required"));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      // Step 1 — upload each photo linked to this slot. Sequential so a
      // per-file backend error surfaces against the right file.
      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("staff_assignment_id", String(slot.id));
        await api.post(`/tickets/${slot.ticket_id}/attachments/`, formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      // Step 2 — mark the slot completed. The backend re-checks evidence.
      await updateStaffSlot(slot.ticket_id, userId, {
        slot_status: "COMPLETED",
        completion_note: note.trim(),
      });
      onDone();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    const tooBig = picked.find((f) => f.size > MAX_PHOTO_BYTES);
    if (tooBig) {
      setError(t("complete.photo_too_large"));
      return;
    }
    setError("");
    setFiles(picked);
  }

  return (
    <div
      className="reject-modal-backdrop"
      data-testid="slot-completion-dialog"
      role="dialog"
      aria-modal="true"
    >
      <div className="reject-modal" style={{ maxWidth: 460 }}>
        <h3 className="reject-modal-title">{t("complete.dialog_title")}</h3>
        <p className="reject-modal-desc">{t("complete.dialog_desc")}</p>

        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="slot-complete-note">
            {t("complete.note_label")}
          </label>
          <textarea
            id="slot-complete-note"
            className="field-textarea"
            data-testid="slot-complete-note"
            rows={3}
            placeholder={t("complete.note_placeholder")}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="slot-complete-photos">
            {t("complete.photo_label")}
          </label>
          <input
            id="slot-complete-photos"
            type="file"
            accept={ACCEPTED_PHOTO_TYPES}
            multiple
            onChange={onFileChange}
            data-testid="slot-complete-photos"
          />
          <div className="form-section-helper">{t("complete.photo_hint")}</div>
          {files.length > 0 && (
            <div className="muted small" style={{ marginTop: 4 }}>
              {t("complete.photo_count", { count: files.length })}
            </div>
          )}
        </div>

        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={submitting}
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleSubmit}
            disabled={submitting || !hasEvidence}
            data-testid="slot-complete-submit"
          >
            {submitting ? t("complete.submitting") : t("complete.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
