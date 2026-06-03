// Sprint 12 frontend — per-occurrence override modal.
//
// Edits the five snapshotted pricing/window fields the backend override
// action accepts. Copy makes clear this changes the planned-work CALENDAR
// only — it does NOT reschedule an already-created ticket. Mount with a
// `key={occurrence.id}` so the state initializers re-read a fresh
// occurrence (no reset effect needed).
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { overrideOccurrence } from "../../api/plannedWork";
import { extractAdminFieldErrors } from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import { getApiError } from "../../api/client";
import type {
  PlannedOccurrence,
  PlannedOccurrenceOverridePayload,
  SelectablePricingMode,
} from "../../api/plannedWork.types";

const PRICING_MODES: SelectablePricingMode[] = ["CONTRACT_INCLUDED", "FIXED"];

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

  const [pricingMode, setPricingMode] = useState<SelectablePricingMode>(
    occurrence.pricing_mode === "FIXED" ? "FIXED" : "CONTRACT_INCLUDED",
  );
  const [fixedPrice, setFixedPrice] = useState(occurrence.fixed_price ?? "");
  const [vatPct, setVatPct] = useState(occurrence.vat_pct ?? "21");
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
      const payload: PlannedOccurrenceOverridePayload = {
        pricing_mode: pricingMode,
        fixed_price: pricingMode === "FIXED" ? fixedPrice.trim() : null,
        vat_pct: vatPct || "21",
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

        <div className="field">
          <label className="field-label" htmlFor="ov-pricing-mode">
            {t("override.field_pricing_mode")}
          </label>
          <select
            id="ov-pricing-mode"
            className="field-select"
            value={pricingMode}
            onChange={(event) =>
              setPricingMode(event.target.value as SelectablePricingMode)
            }
          >
            {PRICING_MODES.map((m) => (
              <option key={m} value={m}>
                {t(`pricing_mode.${m}`)}
              </option>
            ))}
          </select>
          {fieldErrors.pricing_mode && (
            <div className="alert-error login-error" role="alert">
              {fieldErrors.pricing_mode}
            </div>
          )}
        </div>

        {pricingMode === "FIXED" && (
          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="ov-fixed-price">
                {t("override.field_fixed_price")}
              </label>
              <input
                id="ov-fixed-price"
                className="field-input"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                value={fixedPrice}
                onChange={(event) => setFixedPrice(event.target.value)}
              />
              {fieldErrors.fixed_price && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.fixed_price}
                </div>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="ov-vat">
                {t("override.field_vat_pct")}
              </label>
              <input
                id="ov-vat"
                className="field-input"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                value={vatPct}
                onChange={(event) => setVatPct(event.target.value)}
              />
            </div>
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
