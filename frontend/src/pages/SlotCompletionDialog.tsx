// Phase B Part C — staff slot completion dialog with photo-evidence.
//
// Photo linking is a TWO-STEP flow:
//   1. POST /tickets/<ticket_id>/attachments/ (multipart) with write-only
//      staff_assignment_id=<slot id> for each photo;
//   2. PATCH /tickets/<ticket_id>/staff-assignments/<slot id>/ with
//      slot_status=COMPLETED (+ completion_note).
// Backend error messages (completion_evidence_required,
// invalid_file_mime_pair, slot_not_owned, slot_ticket_mismatch) are
// surfaced verbatim if a request 400s.
//
// W3-G — WHAT this slot requires is no longer the same sentence for
// every job. It comes from the two flags a manager set when the work was
// planned (`file_upload_required`, `completion_notes_required` on the
// extra work), and a ticket that came from no extra work keeps the old
// note-OR-photo rule. So the dialog ASKS the server what is needed, says
// it in the header, and disables its own button until it is met.
//
// THE BROWSER IS NOT THE GATE, and this is the whole reason the sprint
// exists: in the system we are closing the gap against, both flags are
// checked in the browser only, in two screens that check different
// things, and no endpoint can even persist them. Here the same resolver
// answers this read AND the PATCH, so a stale answer, a failed fetch or
// a hand-made request changes nothing about what is written. When the
// read fails the dialog falls back to the old rule and lets the server
// decide, rather than blocking a worker on a request that is only
// advisory.
import type { ChangeEvent } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../api/client";
import { getSlotCompletionRequirements, updateStaffSlot } from "../api/admin";
import type { MySlot, SlotCompletionRequirements } from "../api/admin";

const ACCEPTED_PHOTO_TYPES = ".jpg,.jpeg,.png,.webp,.heic,.heif";
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

export function SlotCompletionDialog({
  slot,
  onCancel,
  onDone,
}: {
  // Sprint 179A — the two ids are the WHOLE dependency: the dialog
  // uploads against `ticket_id` and PATCHes `id`, and nothing else on a
  // slot row reaches it. Narrowing the prop to those two lets the Work
  // Plan (whose entries are a merged shape, not `MySlot` rows) reuse
  // this dialog without either side inventing a conversion.
  slot: Pick<MySlot, "id" | "ticket_id">;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // `null` means "not answered yet, or the read failed" — both resolve
  // to the legacy rule below, which is the safe reading: it is what
  // every job required before this sprint.
  const [requirements, setRequirements] =
    useState<SlotCompletionRequirements | null>(null);

  // No synchronous setState in the effect body (the house rule, and
  // `react-hooks/set-state-in-effect`). The dialog opens on the LEGACY
  // rule and adjusts when the answer lands — in either direction, so a
  // job that needs nothing is briefly asking for a note. That is the
  // right way round: for the fraction of a second before the server
  // answers, the dialog asks for MORE than it might need rather than
  // less, and the server is the one that decides either way.
  useEffect(() => {
    let cancelled = false;
    getSlotCompletionRequirements(slot.ticket_id, slot.id)
      .then((data) => {
        if (!cancelled) setRequirements(data);
      })
      .catch(() => {
        // Deliberately silent: this read is advisory. The submit below
        // still goes to a server that refuses on its own, and telling a
        // worker about a failed background fetch they cannot act on
        // would be noise in front of the job they are trying to close.
        if (!cancelled) setRequirements(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slot.ticket_id, slot.id]);

  const hasNote = note.trim().length > 0;
  const hasFile = files.length > 0;
  const noteRequired = requirements?.note_required ?? false;
  const fileRequired = requirements?.file_required ?? false;
  // No answer yet, or a plain ticket: the pre-W3-G rule.
  const eitherRequired = requirements?.either_required ?? true;

  const missing: string[] = [];
  if (noteRequired && !hasNote) missing.push("note");
  if (fileRequired && !hasFile) missing.push("file");
  if (eitherRequired && !hasNote && !hasFile) missing.push("either");
  const hasEvidence = missing.length === 0;

  /** One sentence saying what THIS job needs, before anything is typed.
   *  "Completing a slot requires a note or a photo" was true of every
   *  job until this sprint and is now true of some of them, which makes
   *  it the worst kind of instruction: right often enough to be
   *  believed. */
  const requirementText = eitherRequired
    ? // The pre-W3-G sentence, reused rather than re-typed: it already
      // says exactly "a note or at least one photo", and two strings
      // for one rule are two chances to phrase it differently.
      t("complete.evidence_required")
    : noteRequired && fileRequired
      ? t("complete.requires_both")
      : noteRequired
        ? t("complete.requires_note")
        : fileRequired
          ? t("complete.requires_file")
          : t("complete.requires_nothing");

  async function handleSubmit() {
    if (!hasEvidence) {
      setError(requirementText);
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
      await updateStaffSlot(slot.ticket_id, slot.id, {
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
        <p
          className="reject-modal-desc"
          data-testid="slot-complete-requirements"
        >
          <strong>{requirementText}</strong>
        </p>

        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="slot-complete-note">
            {t("complete.note_label")}
            {noteRequired && (
              <span className="required-mark" aria-hidden="true">
                {" *"}
              </span>
            )}
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
            {fileRequired && (
              <span className="required-mark" aria-hidden="true">
                {" *"}
              </span>
            )}
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
