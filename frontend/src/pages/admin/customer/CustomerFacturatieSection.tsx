// The "Facturatie" section: the billing-schedule settings
// (invoice_day_rule + invoice_granularity_default). Provider-admin-gated in
// the UI (the backend enforces OSIUS-admin on write; the controls hide for
// non-admins). Self-contained so the host page only imports + mounts it.
//
// Sprint 153 §4.2 — this section mounts on the customer SETTINGS page, not
// the Overview. The file keeps its name and location; only the mount moved.
//
// Sprint 154 §C — the contract-PDF half is GONE from this UI: the upload
// input, the View / Replace / Remove buttons and the media imports. Sprint
// 153 had removed only the inline preview; the owner wants the whole thing
// off the screen.
//
// THIS IS A UI REMOVAL, NOT DATA LOSS. `CustomerContractPdfView`, the
// `Customer.contract_pdf` model field, the upload path and every stored
// file are untouched — `contract_pdf_url` is still on the serializer and
// still populated. Any PDF a customer already has is still on disk and
// still reachable through the API; there is simply no button for it here
// any more. Restoring the UI is a frontend change with no migration.
//
// What remains is the half that does something: the billing schedule.
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { updateCustomer } from "../../../api/admin";
import type {
  CustomerAdmin,
  InvoiceDayRule,
  InvoiceGranularity,
} from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { isProviderAdmin } from "../../../auth/permissions";
import { useToast } from "../../../components/ToastProvider";

// Billing-day picker value: "" (unset), "1".."28" (a specific day of month),
// or "last" (last of month). FIRST_OF_MONTH stays a valid enum but is shown as
// day 1 (they are equivalent). Days cap at 28 so the day exists in every month.
const DAY_OF_MONTH_OPTIONS = Array.from({ length: 28 }, (_, i) => i + 1);

function initialDaySelection(c: CustomerAdmin): string {
  if (c.invoice_day_of_month != null) return String(c.invoice_day_of_month);
  if (c.invoice_day_rule === "LAST_OF_MONTH") return "last";
  if (c.invoice_day_rule === "FIRST_OF_MONTH") return "1"; // first === day 1
  return "";
}

// One canonical representation per selection so a reload shows the same choice:
// a specific day stores invoice_day_of_month and clears the rule; last-of-month
// stores the rule and clears the day; unset clears both.
function daySelectionToPayload(sel: string): {
  invoice_day_rule: InvoiceDayRule | "";
  invoice_day_of_month: number | null;
} {
  if (sel === "last") {
    return { invoice_day_rule: "LAST_OF_MONTH", invoice_day_of_month: null };
  }
  if (sel === "") {
    return { invoice_day_rule: "", invoice_day_of_month: null };
  }
  return { invoice_day_rule: "", invoice_day_of_month: Number(sel) };
}

export function CustomerFacturatieSection({
  customer,
  onUpdated,
}: {
  customer: CustomerAdmin;
  onUpdated: (fresh: CustomerAdmin) => void;
}) {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const { push: pushToast } = useToast();
  const canManage = isProviderAdmin(me?.role);

  const [daySelection, setDaySelection] = useState<string>(() =>
    initialDaySelection(customer),
  );
  const [granularity, setGranularity] = useState<InvoiceGranularity>(
    customer.invoice_granularity_default ?? "CUSTOMER",
  );
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [error, setError] = useState("");

  async function handleSaveSchedule() {
    setSavingSchedule(true);
    setError("");
    try {
      const fresh = await updateCustomer(customer.id, {
        ...daySelectionToPayload(daySelection),
        invoice_granularity_default: granularity,
      });
      onUpdated(fresh);
      pushToast({ variant: "success", title: t("facturatie.schedule_saved") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSavingSchedule(false);
    }
  }

  return (
    <section
      className="card"
      data-testid="customer-facturatie-section"
      style={{ marginBottom: 18 }}
    >
      <div className="section-head">
        <div>
          <div className="section-head-title">
            {t("facturatie.section_title")}
          </div>
          <div className="section-head-sub">{t("facturatie.section_sub")}</div>
        </div>
      </div>

      <div style={{ padding: "14px 18px 18px" }}>
        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {/* Billing schedule. */}
        <div
          style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 16 }}
        >
          <label className="field" style={{ flex: "1 1 220px" }}>
            <span className="field-label">
              {t("facturatie.day_rule_label")}
            </span>
            <select
              className="field-select"
              value={daySelection}
              onChange={(e) => setDaySelection(e.target.value)}
              disabled={!canManage || savingSchedule}
              data-testid="facturatie-day-rule"
            >
              <option value="">{t("facturatie.day_unset")}</option>
              {DAY_OF_MONTH_OPTIONS.map((d) => (
                <option key={d} value={String(d)}>
                  {t("facturatie.day_of_month_option", { day: d })}
                </option>
              ))}
              <option value="last">{t("facturatie.day_last")}</option>
            </select>
            <span
              className="muted small"
              style={{ display: "block", marginTop: 4 }}
            >
              {t("facturatie.day_rule_helper")}
            </span>
          </label>
          <label className="field" style={{ flex: "1 1 220px" }}>
            <span className="field-label">
              {t("facturatie.granularity_label")}
            </span>
            <select
              className="field-select"
              value={granularity}
              onChange={(e) =>
                setGranularity(e.target.value as InvoiceGranularity)
              }
              disabled={!canManage || savingSchedule}
              data-testid="facturatie-granularity"
            >
              <option value="CUSTOMER">
                {t("facturatie.granularity_customer")}
              </option>
              <option value="PER_BUILDING">
                {t("facturatie.granularity_building")}
              </option>
              <option value="PER_BUILDING_DEPARTMENT_WORK_TYPE">
                {t("facturatie.granularity_department_work_type")}
              </option>
            </select>
            <span
              className="muted small"
              style={{ display: "block", marginTop: 4 }}
            >
              {t("facturatie.granularity_helper")}
            </span>
          </label>
        </div>
        {canManage && (
          <div className="form-actions" style={{ marginBottom: 20 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleSaveSchedule}
              disabled={savingSchedule}
              data-testid="facturatie-schedule-save"
            >
              {t("facturatie.schedule_save")}
            </button>
          </div>
        )}

      </div>
    </section>
  );
}
