// M2 P4 — drill-in editor for ONE staff credential (SoT Addendum A.3.1).
//
// Mirrors CustomerUserManageModal mechanics: the PARENT keys this modal
// by credential id (or "new"), so the prop-derived form state is seeded
// once via useState initializers and never resynced in an effect.
// ConfirmDialog guards the destructive actions, ToastProvider reports
// outcomes, X closes.
//
// EU_NATIONAL_ID is the compliance hard block (backend-enforced via
// clean()/save()/DB CheckConstraint): the UI never even OFFERS the
// visibility select or the photocopy toggle for that type — it renders
// a locked notice instead, and the save payload omits both fields.
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Download, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listCustomers } from "../../api/admin";
import type { CustomerAdmin } from "../../api/types";
import {
  CREDENTIAL_TYPES,
  CREDENTIAL_VISIBILITY_LEVELS,
  createCredential,
  createCredentialGrant,
  downloadCredentialDocument,
  isAcceptablePdf,
  listCredentialGrants,
  removeCredential,
  removeCredentialGrant,
  updateCredential,
} from "../../api/staffCredentials";
import type {
  CredentialCreatePayload,
  CredentialGrant,
  CredentialType,
  CredentialUpdatePayload,
  CredentialVisibilityLevel,
  StaffCredential,
} from "../../api/staffCredentials";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";
import { Toggle } from "../../components/Toggle";

export interface StaffCredentialModalProps {
  userId: number;
  /** null = create mode. The parent keys the modal by credential id
   *  ("new" for create) so this prop never resyncs in an effect. */
  credential: StaffCredential | null;
  canEdit: boolean;
  onClose: () => void;
  /** Called after any persisted change so the parent list refreshes. */
  onChanged: () => void;
}

export function StaffCredentialModal({
  userId,
  credential,
  canEdit,
  onClose,
  onChanged,
}: StaffCredentialModalProps) {
  const { t } = useTranslation("staff_credentials");
  const toast = useToast();
  const isCreate = credential === null;

  // Form state — seeded ONCE from the keyed prop (no effect resync).
  const [credentialType, setCredentialType] = useState<CredentialType>(
    credential?.credential_type ?? "VCA",
  );
  const [permitNumber, setPermitNumber] = useState(
    credential?.permit_number ?? "",
  );
  const [expiryDate, setExpiryDate] = useState(credential?.expiry_date ?? "");
  const [visibility, setVisibility] = useState<CredentialVisibilityLevel>(
    credential?.visibility_level ?? "PA_SA_ONLY",
  );
  const [photocopyVisible, setPhotocopyVisible] = useState(
    credential?.document_customer_visible ?? false,
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  // Grants (edit mode only — a credential must exist before it can be
  // shared). Seeded from the keyed prop, reloaded after mutations.
  const [grants, setGrants] = useState<CredentialGrant[]>(
    credential?.grants ?? [],
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

  const isEuId = credentialType === "EU_NATIONAL_ID";
  const isResidencePermit = credentialType === "RESIDENCE_PERMIT";
  // The SAVED ceiling gates the grant editor (the backend rejects a
  // grant create unless the persisted level is CUSTOMER_VISIBLE).
  const savedVisibility = credential?.visibility_level ?? null;
  const grantsEditable =
    !isCreate && savedVisibility === "CUSTOMER_VISIBLE" && !isEuId;

  // Customer options for the add-grant dropdown — loaded lazily, all
  // setState inside the async closure (never synchronously in the
  // effect body).
  useEffect(() => {
    if (isCreate || isEuId) return;
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
  }, [isCreate, isEuId]);

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
    setSaving(true);
    setError("");
    try {
      if (isCreate) {
        const payload: CredentialCreatePayload = {
          credential_type: credentialType,
          permit_number: permitNumber.trim(),
          expiry_date: expiryDate === "" ? null : expiryDate,
        };
        // EU national ID: visibility + photocopy are backend-locked —
        // the payload deliberately omits both so the UI can never even
        // attempt the change.
        if (!isEuId) {
          payload.visibility_level = visibility;
          if (isResidencePermit) {
            payload.document_customer_visible = photocopyVisible;
          }
        }
        if (selectedFile) payload.document = selectedFile;
        await createCredential(userId, payload);
        toast.push({
          variant: "success",
          title: t("toast.credential_created"),
        });
      } else {
        const payload: CredentialUpdatePayload = {
          permit_number: permitNumber.trim(),
          expiry_date: expiryDate === "" ? null : expiryDate,
        };
        if (!isEuId) {
          payload.visibility_level = visibility;
          if (isResidencePermit) {
            payload.document_customer_visible = photocopyVisible;
          }
        }
        if (selectedFile) payload.document = selectedFile;
        await updateCredential(userId, credential.id, payload);
        toast.push({ variant: "success", title: t("toast.credential_saved") });
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
    if (!credential) return;
    setDownloading(true);
    setError("");
    try {
      await downloadCredentialDocument(userId, credential);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setDownloading(false);
    }
  }

  async function reloadGrants() {
    if (!credential) return;
    try {
      setGrants(await listCredentialGrants(userId, credential.id));
    } catch (err) {
      setError(getApiError(err));
    }
  }

  async function handleAddGrant(event: FormEvent) {
    event.preventDefault();
    if (!credential || selectedCustomerId === "") return;
    setGrantBusy(true);
    setError("");
    try {
      await createCredentialGrant(
        userId,
        credential.id,
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
    if (!credential || !grantRemoveTarget) return;
    setGrantBusy(true);
    setError("");
    try {
      await removeCredentialGrant(
        userId,
        credential.id,
        grantRemoveTarget.id,
      );
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
    if (!credential) return;
    setDeleting(true);
    setError("");
    try {
      await removeCredential(userId, credential.id);
      deleteRef.current?.close();
      toast.push({
        variant: "success",
        title: t("toast.credential_deleted"),
      });
      onChanged();
      onClose();
    } catch (err) {
      setError(getApiError(err));
      deleteRef.current?.close();
    } finally {
      setDeleting(false);
    }
  }

  const typeLabel = (type: CredentialType) => t(`type.${type}`);
  const levelLabel = (level: CredentialVisibilityLevel) =>
    t(`visibility.${level}`);

  return (
    <div
      data-testid="staff-credential-modal"
      role="dialog"
      aria-modal="true"
      aria-label={
        isCreate ? t("modal.create_credential_title") : typeLabel(credentialType)
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
              {t("modal.credential_eyebrow")}
            </div>
            <h3 className="section-title" style={{ margin: 0 }}>
              {isCreate
                ? t("modal.create_credential_title")
                : typeLabel(credentialType)}
            </h3>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="staff-credential-modal-close"
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
            data-testid="staff-credential-modal-error"
            style={{ marginBottom: 12 }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {isCreate ? (
            <div className="field">
              <label className="field-label" htmlFor="credential-type">
                {t("field.credential_type")}
              </label>
              <select
                id="credential-type"
                className="field-select"
                value={credentialType}
                onChange={(event) =>
                  setCredentialType(event.target.value as CredentialType)
                }
                disabled={saving}
                data-testid="credential-type-select"
              >
                {CREDENTIAL_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {typeLabel(type)}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="field">
              <span className="field-label">{t("field.credential_type")}</span>
              <p className="muted small" style={{ margin: 0 }}>
                {typeLabel(credentialType)} — {t("field.type_immutable_hint")}
              </p>
            </div>
          )}

          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="credential-permit-number">
                {t("field.permit_number")}
              </label>
              <input
                id="credential-permit-number"
                className="field-input"
                type="text"
                value={permitNumber}
                onChange={(event) => setPermitNumber(event.target.value)}
                disabled={!canEdit || saving}
                data-testid="credential-permit-number-input"
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="credential-expiry">
                {t("field.expiry_date")}
              </label>
              <input
                id="credential-expiry"
                className="field-input"
                type="date"
                value={expiryDate ?? ""}
                onChange={(event) => setExpiryDate(event.target.value)}
                disabled={!canEdit || saving}
                data-testid="credential-expiry-input"
              />
            </div>
          </div>

          {isEuId ? (
            // The compliance hard block, mirrored in the UI: no
            // visibility select, no photocopy toggle — a locked notice
            // only. The backend enforces this regardless (clean/save/
            // DB CheckConstraint); the payload omits both fields.
            <div
              className="alert-info"
              role="note"
              data-testid="credential-eu-id-locked-notice"
              style={{ marginBottom: 12 }}
            >
              {t("eu_locked_notice")}
            </div>
          ) : (
            <div className="field">
              <label className="field-label" htmlFor="credential-visibility">
                {t("visibility.label")}
              </label>
              <select
                id="credential-visibility"
                className="field-select"
                value={visibility}
                onChange={(event) =>
                  setVisibility(
                    event.target.value as CredentialVisibilityLevel,
                  )
                }
                disabled={!canEdit || saving}
                data-testid="credential-visibility-select"
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
          )}

          {isResidencePermit && (
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: canEdit ? "pointer" : "default",
                }}
              >
                <Toggle
                  checked={photocopyVisible}
                  onChange={(event) =>
                    setPhotocopyVisible(event.target.checked)
                  }
                  disabled={!canEdit || saving}
                  data-testid="credential-photocopy-toggle"
                />
                <span>{t("field.photocopy_toggle")}</span>
              </label>
              <p className="muted small" style={{ marginTop: 4 }}>
                {t("field.photocopy_hint")}
              </p>
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor="credential-document">
              {t("field.document")}
            </label>
            {credential?.has_document && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                  flexWrap: "wrap",
                }}
                data-testid="credential-current-document"
              >
                <span className="muted small">
                  {credential.original_filename}
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={handleDownload}
                  disabled={downloading}
                  data-testid="credential-download-button"
                >
                  <Download size={14} strokeWidth={2} />
                  {downloading ? t("field.downloading") : t("field.download")}
                </button>
              </div>
            )}
            <input
              id="credential-document"
              className="field-input"
              type="file"
              accept="application/pdf"
              onChange={handleFileChange}
              disabled={!canEdit || saving}
              data-testid="credential-document-input"
            />
            <p className="muted small" style={{ marginTop: 4 }}>
              {credential?.has_document
                ? t("field.document_replace_hint")
                : t("field.document_hint")}
            </p>
          </div>

          <div className="form-actions">
            {!isCreate && canEdit && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ marginRight: "auto", color: "var(--red)" }}
                onClick={() => deleteRef.current?.open()}
                disabled={saving || deleting}
                data-testid="credential-delete-button"
              >
                {t("actions.delete_credential")}
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
              data-testid="credential-save-button"
            >
              {saving ? t("actions.saving") : t("actions.save")}
            </button>
          </div>
        </form>

        {/* ---------- Grants (edit mode) ---------- */}
        {!isCreate && !isEuId && (
          <section
            style={{
              borderTop: "1px solid var(--border)",
              marginTop: 16,
              paddingTop: 14,
            }}
            data-testid="credential-grants-section"
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
                    data-testid="credential-grants-inert-note"
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
                        data-testid={`credential-grant-chip-${grant.customer_id}`}
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
                            data-testid={`credential-grant-remove-${grant.customer_id}`}
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
                        htmlFor="credential-grant-add"
                      >
                        {t("grants.add_label")}
                      </label>
                      <select
                        id="credential-grant-add"
                        className="field-select"
                        value={
                          selectedCustomerId === ""
                            ? ""
                            : String(selectedCustomerId)
                        }
                        onChange={(event) => {
                          const value = event.target.value;
                          setSelectedCustomerId(
                            value === "" ? "" : Number(value),
                          );
                        }}
                        disabled={grantBusy || grantableCustomers.length === 0}
                        data-testid="credential-grant-add-select"
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
                      data-testid="credential-grant-add-button"
                    >
                      {grantBusy
                        ? t("grants.adding")
                        : t("grants.add_button")}
                    </button>
                  </form>
                )}
              </>
            ) : (
              <p
                className="muted small"
                data-testid="credential-grants-hint"
              >
                {t("grants.hint_not_customer_visible")}
              </p>
            )}
          </section>
        )}
        {/* ConfirmDialogs live INSIDE the stop-propagation card so a
            click in the dialog can never bubble to the overlay's
            close-on-click handler. */}
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
          title={t("delete_confirm_title", {
            type: typeLabel(credentialType),
          })}
          body={t("delete_confirm_body")}
          confirmLabel={t("actions.delete_credential")}
          onConfirm={handleConfirmDelete}
          onCancel={() => undefined}
          busy={deleting}
          destructive
        />
      </div>
    </div>
  );
}
