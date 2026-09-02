/**
 * P-13 A (W1) — "Set a billing day", from the Invoices page.
 *
 * A customer without a billing day used to be INVISIBLE on the due
 * panel; now their row says so and offers this dialog, so the fix is
 * one press away from where the gap shows, instead of a walk to the
 * customer's settings page. Saves through the SAME endpoint and the
 * SAME value model as `CustomerFacturatieSection`
 * (`lib/billingDay.ts`) — one representation, two doors.
 *
 * A NON-NATIVE overlay, conditionally mounted, like `ChoiceDialog` /
 * `BulkAssignDialog` — the "render unconditionally, drive through the
 * ref" rule is about the native `<dialog>` element, which this is not.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { updateCustomerBillingSettings } from "../../api/invoices";
import {
  DAY_OF_MONTH_OPTIONS,
  daySelectionToPayload,
  initialDaySelection,
} from "../../lib/billingDay";
import type { BillingDayFacts } from "../../lib/billingDay";

export interface BillingDayDialogProps {
  customerId: number;
  customerName: string;
  current: BillingDayFacts;
  onCancel: () => void;
  /** The day was saved — the caller refreshes its rows. */
  onSaved: () => void;
}

export function BillingDayDialog({
  customerId,
  customerName,
  current,
  onCancel,
  onSaved,
}: BillingDayDialogProps) {
  const { t } = useTranslation("common");
  const [selection, setSelection] = useState(() =>
    initialDaySelection(current),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    selectRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      await updateCustomerBillingSettings(
        customerId,
        daySelectionToPayload(selection),
      );
      onSaved();
    } catch (err) {
      setError(getApiError(err));
      setSaving(false);
    }
  }

  return (
    <div
      data-testid="billing-day-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("facturatie.day_rule_label")}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div className="card" style={{ maxWidth: 460, width: "100%", padding: 24 }}>
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {t("facturen.set_day_title", { name: customerName })}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("facturen.set_day_body")}
        </p>

        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        <label
          className="detail-field-label"
          htmlFor="billing-day-select"
          style={{ display: "block", marginBottom: 4 }}
        >
          {t("facturatie.day_rule_label")}
        </label>
        <select
          id="billing-day-select"
          ref={selectRef}
          className="field-select"
          value={selection}
          onChange={(e) => setSelection(e.target.value)}
          data-testid="billing-day-select"
        >
          <option value="">{t("facturatie.day_unset")}</option>
          {DAY_OF_MONTH_OPTIONS.map((day) => (
            <option key={day} value={String(day)}>
              {t("facturatie.day_of_month_option", { day })}
            </option>
          ))}
          <option value="last">{t("facturatie.day_last")}</option>
        </select>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 20,
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={saving}
            data-testid="billing-day-cancel"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleSave}
            disabled={saving || selection === ""}
            data-testid="billing-day-save"
          >
            {t("facturen.set_day_save")}
          </button>
        </div>
      </div>
    </div>
  );
}
