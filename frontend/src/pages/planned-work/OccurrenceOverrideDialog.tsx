// Per-occurrence override modal — "move this visit".
//
// Edits WHEN the visit sits within its day: its start time and its window
// label. Copy makes clear this changes the planned-work CALENDAR only — it
// does NOT reschedule an already-created ticket. Mount with a
// `key={occurrence.id}` so the state initializers re-read a fresh
// occurrence (no reset effect needed).
//
// W-PW1 — the three pricing fields this dialog used to edit
// (`pricing_mode`, `fixed_price`, `vat_pct`) are GONE from it. Per-visit
// pricing is not a thing the owner wants expressible: a recurring job is
// billed through its contract line as a membership, or it is a single job.
// The override PAYLOAD leaves all three fields out entirely (every field on
// `PlannedOccurrenceOverridePayload` is optional), so a visit's stored
// pricing is neither shown nor rewritten by a move — the columns and the
// endpoint are untouched, and nothing here can resurface CONTRACT_INCLUDED
// as a control.
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { overrideOccurrence } from "../../api/plannedWork";
import { extractAdminFieldErrors } from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import { getApiError } from "../../api/client";
import type {
  PlannedOccurrence,
  PlannedOccurrenceOverridePayload,
} from "../../api/plannedWork.types";

export function OccurrenceOverrideDialog({
  occurrence,
  onCancel,
  onSaved,
}: {
  occurrence: PlannedOccurrence;
  onCancel: () => void;
  onSaved: (updated: PlannedOccurrence) => void;
}) {
  const { t } = useTranslation(["planned_work", "common"]);

  const [preferredStartTime, setPreferredStartTime] = useState(
    occurrence.preferred_start_time?.slice(0, 5) ?? "",
  );
  const [timeWindowLabel, setTimeWindowLabel] = useState(
    occurrence.time_window_label,
  );

  const [saving, setSaving] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  async function handleSave() {
    setGeneralError("");
    setFieldErrors({});
    setSaving(true);
    try {
      // Only the two timing fields. Omitting the pricing keys leaves the
      // occurrence's stored values exactly as they were.
      const payload: PlannedOccurrenceOverridePayload = {
        preferred_start_time: preferredStartTime || null,
        time_window_label: timeWindowLabel.trim(),
      };
      const updated = await overrideOccurrence(occurrence.id, payload);
      onSaved(updated);
    } catch (err) {
      const fields = extractAdminFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
        if (fields.detail) setGeneralError(fields.detail);
      } else {
        setGeneralError(getApiError(err));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="reject-modal-backdrop"
      data-testid="occurrence-override-dialog"
      role="dialog"
      aria-modal="true"
    >
      <div className="reject-modal" style={{ maxWidth: 480 }}>
        <h3 className="reject-modal-title">{t("override.dialog_title")}</h3>
        <p className="reject-modal-desc">{t("override.dialog_desc")}</p>

        {generalError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {generalError}
          </div>
        )}

        <div className="form-2col">
          <div className="field">
            <label className="field-label" htmlFor="ov-time">
              {t("override.field_preferred_start_time")}
            </label>
            <input
              id="ov-time"
              className="field-input"
              type="time"
              value={preferredStartTime}
              onChange={(event) => setPreferredStartTime(event.target.value)}
            />
            {fieldErrors.preferred_start_time && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.preferred_start_time}
              </div>
            )}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ov-window">
              {t("override.field_time_window_label")}
            </label>
            <input
              id="ov-window"
              className="field-input"
              type="text"
              maxLength={64}
              value={timeWindowLabel}
              onChange={(event) => setTimeWindowLabel(event.target.value)}
            />
            {fieldErrors.time_window_label && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.time_window_label}
              </div>
            )}
          </div>
        </div>

        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={saving}
          >
            {t("form.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleSave}
            disabled={saving}
            data-testid="occurrence-override-save"
          >
            {saving ? t("override.saving") : t("override.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
