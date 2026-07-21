// Invoicing Phase 4b — the "Facturatie" section on the Customer Overview
// page: the informational contract PDF (upload / view / replace / remove) +
// the billing-schedule settings (invoice_day_rule + invoice_granularity_
// default). Provider-admin-gated in the UI (the backend enforces OSIUS-admin
// on write; the controls hide for non-admins). Self-contained so the overview
// page only imports + mounts it.
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { updateCustomer } from "../../../api/admin";
import {
  deleteCustomerContractPdf,
  fetchCustomerContractPdf,
  uploadCustomerContractPdf,
} from "../../../api/media";
import type {
  CustomerAdmin,
  InvoiceDayRule,
  InvoiceGranularity,
} from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { isProviderAdmin } from "../../../auth/permissions";
import { useToast } from "../../../components/ToastProvider";

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

  const fileRef = useRef<HTMLInputElement>(null);
  const [dayRule, setDayRule] = useState<InvoiceDayRule | "">(
    customer.invoice_day_rule ?? "",
  );
  const [granularity, setGranularity] = useState<InvoiceGranularity>(
    customer.invoice_granularity_default ?? "CUSTOMER",
  );
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [error, setError] = useState("");

  const hasContract = Boolean(customer.contract_pdf_url);

  async function handleSaveSchedule() {
    setSavingSchedule(true);
    setError("");
    try {
      const fresh = await updateCustomer(customer.id, {
        invoice_day_rule: dayRule,
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

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadBusy(true);
    setError("");
    try {
      const url = await uploadCustomerContractPdf(customer.id, file);
      onUpdated({ ...customer, contract_pdf_url: url });
      pushToast({ variant: "success", title: t("facturatie.contract_uploaded") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setUploadBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleRemove() {
    setUploadBusy(true);
    setError("");
    try {
      await deleteCustomerContractPdf(customer.id);
      onUpdated({ ...customer, contract_pdf_url: null });
      pushToast({ variant: "success", title: t("facturatie.contract_removed") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setUploadBusy(false);
    }
  }

  async function handleView() {
    setError("");
    try {
      const blob = await fetchCustomerContractPdf(customer.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(getApiError(err));
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
              value={dayRule}
              onChange={(e) => setDayRule(e.target.value as InvoiceDayRule | "")}
              disabled={!canManage || savingSchedule}
              data-testid="facturatie-day-rule"
            >
              <option value="">{t("facturatie.day_unset")}</option>
              <option value="FIRST_OF_MONTH">
                {t("facturatie.day_first")}
              </option>
              <option value="LAST_OF_MONTH">{t("facturatie.day_last")}</option>
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

        {/* Contract PDF. */}
        <div className="detail-field-label" style={{ marginBottom: 4 }}>
          {t("facturatie.contract_title")}
        </div>
        <p className="muted small" style={{ marginBottom: 8 }}>
          {t("facturatie.contract_hint")}
        </p>
        <div
          style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}
          data-testid="facturatie-contract-controls"
        >
          {hasContract ? (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleView}
              data-testid="facturatie-contract-view"
            >
              {t("facturatie.contract_view")}
            </button>
          ) : (
            <span className="muted small">{t("facturatie.contract_none")}</span>
          )}
          {canManage && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept="application/pdf"
                hidden
                onChange={handleFile}
                data-testid="facturatie-contract-input"
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => fileRef.current?.click()}
                disabled={uploadBusy}
                data-testid="facturatie-contract-upload"
              >
                {hasContract
                  ? t("facturatie.contract_replace")
                  : t("facturatie.contract_upload")}
              </button>
              {hasContract && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ color: "var(--red)" }}
                  onClick={handleRemove}
                  disabled={uploadBusy}
                  data-testid="facturatie-contract-remove"
                >
                  {t("facturatie.contract_remove")}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
