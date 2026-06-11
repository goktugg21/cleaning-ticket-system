// M2 P4 — drill-in editor for ONE custom profile property (SoT
// Addendum A.3.2). Same skeleton as StaffCredentialModal: parent keys
// the modal by property id ("new" for create) so prop-derived state is
// seeded once and never resynced in an effect; ConfirmDialog for
// deletes; ToastProvider for outcomes; X-close.
//
// Grants: per-customer share grants are only valid on STAFF-owned
// properties (the backend 400s otherwise), so the grants block renders
// only when the TARGET user is STAFF.
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Download, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listCustomers } from "../../api/admin";
import type { CustomerAdmin } from "../../api/types";
import {
  CREDENTIAL_VISIBILITY_LEVELS,
  createProperty,
  createPropertyGrant,
  downloadPropertyDocument,
  isAcceptablePdf,
  listPropertyGrants,
  removeProperty,
  removePropertyGrant,
  updateProperty,
} from "../../api/staffCredentials";
import type {
  CredentialGrant,
  CredentialVisibilityLevel,
  CustomProfileProperty,
  PropertyWritePayload,
} from "../../api/staffCredentials";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";

export interface UserPropertyModalProps {
  userId: number;
  /** null = create mode. Parent keys by property id ("new" for create). */
  property: CustomProfileProperty | null;
  /** Grants are staff-owned-only (backend rule) — hidden otherwise. */
  targetIsStaff: boolean;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export function UserPropertyModal({
  userId,
  property,
  targetIsStaff,
  canEdit,
  onClose,
  onChanged,
}: UserPropertyModalProps) {
  const { t } = useTranslation("staff_credentials");
  const toast = useToast();
  const isCreate = property === null;

  const [name, setName] = useState(property?.name ?? "");
  const [value, setValue] = useState(property?.value ?? "");
  const [visibility, setVisibility] = useState<CredentialVisibilityLevel>(
    property?.visibility_level ?? "PA_SA_ONLY",
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  const [grants, setGrants] = useState<CredentialGrant[]>(
    property?.grants ?? [],
  );
  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | "">(
    "",
  );
  const [grantBusy, setGrantBusy] = useState(false);
  const [grantRemoveTarget, setGrantRemoveTarget] =
    useState<CredentialGrant | null>(null);
  const grantRemoveRef = useRef<ConfirmDialogHandle>(null);
  const deleteRef = useRef<ConfirmDialogHandle>(null);
  const [deleting, setDeleting] = useState(false);

  const savedVisibility = property?.visibility_level ?? null;
  const grantsEditable =
    !isCreate && targetIsStaff && savedVisibility === "CUSTOMER_VISIBLE";

  useEffect(() => {
    if (isCreate || !targetIsStaff) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await listCustomers({ page_size: 200 });
        if (!cancelled) setCustomers(response.results);
      } catch {
        if (!cancelled) setCustomers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isCreate, targetIsStaff]);

  const grantedCustomerIds = useMemo(
    () => new Set(grants.map((g) => g.customer_id)),
    [grants],
  );
  const grantableCustomers = useMemo(
    () => customers.filter((c) => !grantedCustomerIds.has(c.id)),
    [customers, grantedCustomerIds],
  );

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file && !isAcceptablePdf(file)) {
      setSelectedFile(null);
      setError(
        file.name.toLowerCase().endsWith(".pdf")
          ? t("validation.too_large")
          : t("validation.pdf_only"),
      );
      event.target.value = "";
      return;
    }
    setError("");
    setSelectedFile(file);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canEdit || saving) return;
    if (!name.trim()) {
      setError(t("validation.name_required"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload: PropertyWritePayload = {
        name: name.trim(),
        value,
        visibility_level: visibility,
      };
      if (selectedFile) payload.document = selectedFile;
      if (isCreate) {
        await createProperty(userId, payload);
        toast.push({ variant: "success", title: t("toast.property_created") });
      } else {
        await updateProperty(userId, property.id, payload);
        toast.push({ variant: "success", title: t("toast.property_saved") });
      }
      onChanged();
      onClose();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDownload() {
    if (!property) return;
    setDownloading(true);
    setError("");
    try {
      await downloadPropertyDocument(userId, property);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setDownloading(false);
    }
  }

  async function reloadGrants() {
    if (!property) return;
    try {
      setGrants(await listPropertyGrants(userId, property.id));
    } catch (err) {
      setError(getApiError(err));
    }
  }

  async function handleAddGrant(event: FormEvent) {
    event.preventDefault();
    if (!property || selectedCustomerId === "") return;
    setGrantBusy(true);
    setError("");
    try {
      await createPropertyGrant(
        userId,
        property.id,
        Number(selectedCustomerId),
      );
      setSelectedCustomerId("");
      await reloadGrants();
      toast.push({ variant: "success", title: t("toast.grant_added") });
      onChanged();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setGrantBusy(false);
    }
  }

  function openGrantRemoveDialog(grant: CredentialGrant) {
    setGrantRemoveTarget(grant);
    grantRemoveRef.current?.open();
  }

  async function handleConfirmGrantRemove() {
    if (!property || !grantRemoveTarget) return;
    setGrantBusy(true);
    setError("");
    try {
      await removePropertyGrant(userId, property.id, grantRemoveTarget.id);
      grantRemoveRef.current?.close();
      setGrantRemoveTarget(null);
      await reloadGrants();
      toast.push({ variant: "success", title: t("toast.grant_removed") });
      onChanged();
    } catch (err) {
      setError(getApiError(err));
      grantRemoveRef.current?.close();
    } finally {
      setGrantBusy(false);
    }
  }

  async function handleConfirmDelete() {
    if (!property) return;
    setDeleting(true);
    setError("");
    try {
      await removeProperty(userId, property.id);
      deleteRef.current?.close();
      toast.push({ variant: "success", title: t("toast.property_deleted") });
      onChanged();
      onClose();
    } catch (err) {
      setError(getApiError(err));
      deleteRef.current?.close();
    } finally {
      setDeleting(false);
    }
  }

  const levelLabel = (level: CredentialVisibilityLevel) =>
    t(`visibility.${level}`);

  return (
    <div
      data-testid="user-property-modal"
      role="dialog"
      aria-modal="true"
      aria-label={
        isCreate ? t("modal.create_property_title") : property.name
      }
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        zIndex: 90,
        padding: 16,
        overflowY: "auto",
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          maxWidth: 620,
          width: "100%",
          padding: 24,
          marginTop: 32,
          marginBottom: 32,
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <div>
            <div className="eyebrow" style={{ marginBottom: 4 }}>
              {t("modal.property_eyebrow")}
            </div>
            <h3 className="section-title" style={{ margin: 0 }}>
              {isCreate ? t("modal.create_property_title") : property.name}
            </h3>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="user-property-modal-close"
            onClick={onClose}
            aria-label={t("modal.close")}
          >
            <X size={18} strokeWidth={2.2} />
          </button>
        </div>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="user-property-modal-error"
            style={{ marginBottom: 12 }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label className="field-label" htmlFor="property-name">
              {t("field.name")}
            </label>
            <input
              id="property-name"
              className="field-input"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={!canEdit || saving}
              data-testid="property-name-input"
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="property-value">
              {t("field.value")}
            </label>
            <textarea
              id="property-value"
              className="field-input"
              rows={3}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              disabled={!canEdit || saving}
              data-testid="property-value-input"
              style={{ resize: "vertical" }}
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="property-visibility">
              {t("visibility.label")}
            </label>
            <select
              id="property-visibility"
              className="field-select"
              value={visibility}
              onChange={(event) =>
                setVisibility(event.target.value as CredentialVisibilityLevel)
              }
              disabled={!canEdit || saving}
              data-testid="property-visibility-select"
            >
              {CREDENTIAL_VISIBILITY_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {levelLabel(level)}
                </option>
              ))}
            </select>
            <p className="muted small" style={{ marginTop: 4 }}>
              {t("visibility.ladder_hint")}
            </p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="property-document">
              {t("field.document")}
            </label>
            {property?.has_document && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                  flexWrap: "wrap",
                }}
                data-testid="property-current-document"
              >
                <span className="muted small">
                  {property.original_filename}
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={handleDownload}
                  disabled={downloading}
                  data-testid="property-download-button"
                >
                  <Download size={14} strokeWidth={2} />
                  {downloading ? t("field.downloading") : t("field.download")}
                </button>
              </div>
            )}
            <input
              id="property-document"
              className="field-input"
              type="file"
              accept="application/pdf"
              onChange={handleFileChange}
              disabled={!canEdit || saving}
              data-testid="property-document-input"
            />
            <p className="muted small" style={{ marginTop: 4 }}>
              {property?.has_document
                ? t("field.document_replace_hint")
                : t("field.document_hint")}
            </p>
          </div>

          <div className="form-actions">
            {!isCreate && canEdit && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ marginRight: "auto", color: "var(--red, #b42318)" }}
                onClick={() => deleteRef.current?.open()}
                disabled={saving || deleting}
                data-testid="property-delete-button"
              >
                {t("actions.delete_property")}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onClose}
              disabled={saving}
            >
              {t("actions.cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!canEdit || saving}
              data-testid="property-save-button"
            >
              {saving ? t("actions.saving") : t("actions.save")}
            </button>
          </div>
        </form>

        {/* ---------- Grants (edit mode, STAFF-owned only) ---------- */}
        {!isCreate && targetIsStaff && (
          <section
            style={{
              borderTop: "1px solid var(--border)",
              marginTop: 16,
              paddingTop: 14,
            }}
            data-testid="property-grants-section"
          >
            <h4 className="section-title" style={{ fontSize: 14 }}>
              {t("grants.title")}
            </h4>
            {grantsEditable ? (
              <>
                <p className="muted small" style={{ marginBottom: 8 }}>
                  {t("grants.desc")}
                </p>
                {visibility !== "CUSTOMER_VISIBLE" && grants.length > 0 && (
                  <div
                    className="alert-info"
                    role="note"
                    data-testid="property-grants-inert-note"
                    style={{ marginBottom: 8 }}
                  >
                    {t("grants.inert_note")}
                  </div>
                )}
                {grants.length === 0 ? (
                  <p className="muted small">{t("grants.empty")}</p>
                ) : (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 6,
                      marginBottom: 8,
                    }}
                  >
                    {grants.map((grant) => (
                      <span
                        key={grant.id}
                        className="cell-tag cell-tag-open"
                        data-testid={`property-grant-chip-${grant.customer_id}`}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        {grant.customer_name}
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => openGrantRemoveDialog(grant)}
                            disabled={grantBusy}
                            aria-label={t("grants.remove_aria", {
                              customer: grant.customer_name,
                            })}
                            data-testid={`property-grant-remove-${grant.customer_id}`}
                            style={{
                              background: "none",
                              border: "none",
                              padding: 0,
                              cursor: "pointer",
                              display: "inline-flex",
                              color: "inherit",
                            }}
                          >
                            <X size={12} strokeWidth={2.4} />
                          </button>
                        )}
                      </span>
                    ))}
                  </div>
                )}
                {canEdit && (
                  <form
                    onSubmit={handleAddGrant}
                    style={{
                      display: "flex",
                      gap: 8,
                      alignItems: "flex-end",
                      flexWrap: "wrap",
                    }}
                  >
                    <div
                      className="field"
                      style={{ flex: 1, marginBottom: 0, minWidth: 0 }}
                    >
                      <label
                        className="field-label"
                        htmlFor="property-grant-add"
                      >
                        {t("grants.add_label")}
                      </label>
                      <select
                        id="property-grant-add"
                        className="field-select"
                        value={
                          selectedCustomerId === ""
                            ? ""
                            : String(selectedCustomerId)
                        }
                        onChange={(event) => {
                          const v = event.target.value;
                          setSelectedCustomerId(v === "" ? "" : Number(v));
                        }}
                        disabled={grantBusy || grantableCustomers.length === 0}
                        data-testid="property-grant-add-select"
                      >
                        <option value="">
                          {grantableCustomers.length === 0
                            ? t("grants.no_more")
                            : t("grants.placeholder")}
                        </option>
                        {grantableCustomers.map((customer) => (
                          <option key={customer.id} value={customer.id}>
                            {customer.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button
                      type="submit"
                      className="btn btn-primary btn-sm"
                      disabled={grantBusy || selectedCustomerId === ""}
                      data-testid="property-grant-add-button"
                    >
                      {grantBusy
                        ? t("grants.adding")
                        : t("grants.add_button")}
                    </button>
                  </form>
                )}
              </>
            ) : (
              <p className="muted small" data-testid="property-grants-hint">
                {savedVisibility === "CUSTOMER_VISIBLE"
                  ? t("grants.hint_staff_only")
                  : t("grants.hint_not_customer_visible")}
              </p>
            )}
          </section>
        )}

        {/* ConfirmDialogs inside the stop-propagation card (see
            StaffCredentialModal note). */}
        <ConfirmDialog
          ref={grantRemoveRef}
          title={t("grants.remove_confirm_title", {
            customer: grantRemoveTarget?.customer_name ?? "",
          })}
          body={t("grants.remove_confirm_body")}
          confirmLabel={t("grants.remove_confirm_label")}
          onConfirm={handleConfirmGrantRemove}
          onCancel={() => setGrantRemoveTarget(null)}
          busy={grantBusy}
          destructive
        />
        <ConfirmDialog
          ref={deleteRef}
          title={t("delete_property_confirm_title", { name })}
          body={t("delete_property_confirm_body")}
          confirmLabel={t("actions.delete_property")}
          onConfirm={handleConfirmDelete}
          onCancel={() => undefined}
          busy={deleting}
          destructive
        />
      </div>
    </div>
  );
}
