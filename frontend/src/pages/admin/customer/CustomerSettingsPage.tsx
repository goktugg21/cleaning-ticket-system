import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  deactivateCustomer,
  getCustomer,
  reactivateCustomer,
  updateCustomer,
} from "../../../api/admin";
import type { CustomerAdmin } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { useSavedBanner } from "../../../hooks/useSavedBanner";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 28 Batch 13 (rework) — Customer Settings page (admin variant).
 *
 * Two cards stacked: Assigned-staff visibility (the three boolean
 * flags) and Lifecycle (deactivate / reactivate). Each carries its
 * own consequence copy so an operator does not need to consult the
 * RBAC matrix to predict what the button does.
 */
export function CustomerSettingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [savingError, setSavingError] = useState("");
  const [saving, setSaving] = useState(false);

  const [showAssignedStaffName, setShowAssignedStaffName] = useState(true);
  const [showAssignedStaffEmail, setShowAssignedStaffEmail] = useState(true);
  const [showAssignedStaffPhone, setShowAssignedStaffPhone] = useState(true);

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("customers.banner_saved"),
  });

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setLoadError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setLoadError("");
    getCustomer(numericId)
      .then((data) => {
        if (cancelled) return;
        setCustomer(data);
        setShowAssignedStaffName(data.show_assigned_staff_name ?? true);
        setShowAssignedStaffEmail(data.show_assigned_staff_email ?? true);
        setShowAssignedStaffPhone(data.show_assigned_staff_phone ?? true);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || !customer) return;
    setSaving(true);
    setSavingError("");
    try {
      // Re-send the basics fields to keep the PATCH payload congruent
      // with the existing API contract; only the visibility flags
      // change here, but a Patch with only the visibility booleans
      // also works on the backend.
      const updated = await updateCustomer(numericId, {
        name: customer.name,
        contact_email: customer.contact_email,
        phone: customer.phone,
        language: customer.language,
        show_assigned_staff_name: showAssignedStaffName,
        show_assigned_staff_email: showAssignedStaffEmail,
        show_assigned_staff_phone: showAssignedStaffPhone,
      });
      setCustomer(updated);
      setSavedBanner(t("customers.banner_saved"));
    } catch (err) {
      setSavingError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setSavingError("");
    try {
      await deactivateCustomer(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/customers?deactivated=ok", { replace: true });
    } catch (err) {
      setSavingError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setSavingError("");
    try {
      await reactivateCustomer(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/customers?reactivated=ok", { replace: true });
    } catch (err) {
      setSavingError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  return (
    <div data-testid="customer-settings-page">
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
      />

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {loadError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {loadError}
        </div>
      )}

      {savingError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {savingError}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          <p
            className="section-explainer"
            data-testid="customer-settings-explainer"
          >
            {t("customer_view.settings.explainer", { customer: customerName })}
          </p>

          <form
            className="card"
            data-testid="contact-visibility-section"
            style={{ padding: "20px 22px", marginBottom: 16 }}
            onSubmit={handleSubmit}
          >
            <div className="section-head" style={{ marginBottom: 12 }}>
              <div>
                <div className="section-head-title">
                  {t("customer_view.settings.contact_visibility_title")}
                </div>
                <div className="section-head-sub">
                  {t("customer_view.settings.visibility_helper")}
                </div>
              </div>
            </div>

            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffName}
                  onChange={(event) =>
                    setShowAssignedStaffName(event.target.checked)
                  }
                  data-testid="show-assigned-staff-name"
                  disabled={saving}
                />
                <span>{t("customer_form.show_assigned_staff_name")}</span>
              </label>
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffEmail}
                  onChange={(event) =>
                    setShowAssignedStaffEmail(event.target.checked)
                  }
                  data-testid="show-assigned-staff-email"
                  disabled={saving}
                />
                <span>{t("customer_form.show_assigned_staff_email")}</span>
              </label>
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffPhone}
                  onChange={(event) =>
                    setShowAssignedStaffPhone(event.target.checked)
                  }
                  data-testid="show-assigned-staff-phone"
                  disabled={saving}
                />
                <span>{t("customer_form.show_assigned_staff_phone")}</span>
              </label>
            </div>

            <div className="form-actions card-actions-cluster">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving}
              >
                {saving
                  ? t("admin_form.saving")
                  : t("admin_form.save_changes")}
              </button>
            </div>
          </form>

          <section
            className="card"
            data-testid="customer-lifecycle-section"
            style={{ padding: "20px 22px" }}
          >
            <div className="section-head" style={{ marginBottom: 12 }}>
              <div>
                <div className="section-head-title">
                  {t("customer_view.settings.lifecycle_title")}
                </div>
                <div className="section-head-sub">
                  {customer.is_active
                    ? t("customer_view.settings.deactivate_consequence")
                    : t("customer_view.settings.reactivate_consequence")}
                </div>
              </div>
            </div>
            <div className="form-actions card-actions-cluster">
              {customer.is_active ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  data-testid="deactivate-button"
                  onClick={() => deactivateDialogRef.current?.open()}
                  disabled={saving || actionBusy}
                >
                  {t("admin_form.deactivate")}
                </button>
              ) : isSuperAdmin ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  data-testid="reactivate-button"
                  onClick={() => reactivateDialogRef.current?.open()}
                  disabled={saving || actionBusy}
                >
                  {t("admin_form.reactivate")}
                </button>
              ) : null}
            </div>
          </section>

          <ConfirmDialog
            ref={deactivateDialogRef}
            title={t("customer_form.dialog_deactivate_title", {
              name: customerName,
            })}
            body={t("customer_form.dialog_deactivate_body")}
            confirmLabel={t("admin_form.deactivate")}
            onConfirm={handleConfirmDeactivate}
            busy={actionBusy}
          />
          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("customer_form.dialog_reactivate_title", {
              name: customerName,
            })}
            body={t("customer_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}
