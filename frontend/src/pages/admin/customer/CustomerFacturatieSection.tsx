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
import { updateCustomerBillingSettings } from "../../../api/invoices";
import type {
  CustomerBillingSettings,
  InvoiceBillingTarget,
  InvoiceSplit,
} from "../../../api/invoices";
// Sprint 183 §1 — the two controls live in ONE component now, shared
// with the Invoices page's generate dialog, so the two screens cannot
// describe the same decision in different words again.
import { BillingTargetFields } from "../../../components/BillingTargetFields";
import type { CustomerAdmin } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { isProviderAdmin } from "../../../auth/permissions";
import { useToast } from "../../../components/ToastProvider";
// P-13 A (W1) — the picker's value model moved to lib/billingDay.ts,
// shared with the Invoices page's "Set a billing day" dialog.
import {
  DAY_OF_MONTH_OPTIONS,
  daySelectionToPayload,
  initialDaySelection,
} from "../../../lib/billingDay";

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
  // Sprint 182 §3 — TWO controls, because these are two questions.
  //
  // The old single dropdown offered CUSTOMER / PER_BUILDING /
  // PER_BUILDING_DEPARTMENT_WORK_TYPE. The first two decide WHO THE
  // INVOICE IS ADDRESSED TO; the third is not a third addressee, it is
  // "per building, split further". Sitting in one list made a split look
  // like a target.
  //
  // `customer` is typed by `api/types.ts` (another agent's file this
  // sprint), so the two new fields are read through a local narrowing
  // rather than by widening that type. Falling back to the legacy value
  // means this renders correctly even against a server that has not been
  // migrated yet.
  const billing = customer as CustomerAdmin & Partial<CustomerBillingSettings>;
  const legacyGranularity = billing.invoice_granularity_default ?? "CUSTOMER";
  const [billingTarget, setBillingTarget] = useState<InvoiceBillingTarget>(
    billing.invoice_billing_target ??
      (legacyGranularity === "CUSTOMER" ? "CUSTOMER" : "BUILDING"),
  );
  const [split, setSplit] = useState<InvoiceSplit>(
    billing.invoice_split ??
      (legacyGranularity === "PER_BUILDING_DEPARTMENT_WORK_TYPE"
        ? "DEPARTMENT_WORK_TYPE"
        : "NONE"),
  );
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [error, setError] = useState("");

  // The split cuts WITHIN a building, so it is meaningless against a
  // customer-addressed invoice. Disabled rather than hidden: a control
  // that vanishes reads as a bug, while a disabled one with a reason
  // beside it teaches the rule.
  const splitApplies = billingTarget === "BUILDING";

  async function handleSaveSchedule() {
    setSavingSchedule(true);
    setError("");
    try {
      const fresh = await updateCustomerBillingSettings<CustomerAdmin>(
        customer.id,
        {
          ...daySelectionToPayload(daySelection),
          invoice_billing_target: billingTarget,
          // Never send a split the target cannot use — the server would
          // resolve it to "no split" anyway, and storing one that does
          // nothing is how a setting starts lying to the operator.
          invoice_split: splitApplies ? split : "NONE",
        },
      );
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
        </div>

        {/* Sprint 183 §1 — the two billing controls, from the shared
            component the Invoices page's generate dialog also uses.
            They were two side-by-side dropdowns with a sentence
            explaining when the second applied, and the owner's reaction
            to that sentence was "what is this now, I am confused". The
            dependency is shown by nesting now, and the copy is the
            example that landed with him rather than a restatement of
            the rule. */}
        <div style={{ marginBottom: 16 }}>
          <BillingTargetFields
            idPrefix="facturatie"
            target={billingTarget}
            split={split}
            onTargetChange={setBillingTarget}
            onSplitChange={setSplit}
            disabled={!canManage || savingSchedule}
          />
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
