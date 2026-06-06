// SoT Addendum A.1 + A.2 — drill-in modal for a single customer User.
//
// "Click a row, edit, leave" — this modal REPLACES the old accordion on
// the Users page and is the drill-in target on the People page. It is a
// thin shell around the proven `ContactPermissionsPanel` (per-building
// access editor + add-building picker + reused PermissionEditorModal
// lifecycle + grantable-role gate) PLUS the SoT Addendum A.1
// company-wide Customer Company Admin (CCA) surface:
//
//   * When the membership carries `is_company_admin === true`, the user
//     is CCA across ALL buildings. We render ONE company-wide status
//     ("Company admin — all buildings") and HIDE the per-building access
//     editor + add-building control entirely (a company admin has no
//     per-building rows to manage).
//
//   * A "Make company admin" / "Remove company admin" action is shown
//     only when `actions.can_manage_customer_company_admins === true`
//     (data-driven; never a hardcoded role check). Demote goes through a
//     ConfirmDialog. The actor's OWN row disables the toggle + shows a
//     self-edit warning (the backend 403s regardless; this is the UI
//     mirror / defence in depth).
//
// The membership + per-customer `actions` block come from
// `listCustomerUsers` (each row carries its own `actions`). On a flag
// flip we call `setCustomerCompanyAdmin`, toast, and notify the parent
// (`onChanged`) so the underlying list refreshes.
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { listCustomerUsers, setCustomerCompanyAdmin } from "../../../api/admin";
import type { CustomerUserMembership } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { useToast } from "../../../components/ToastProvider";
import { accessRoleLabelKey } from "../../../lib/enumLabels";

import { ContactPermissionsPanel } from "../ContactPermissionsPanel";

export interface CustomerUserManageModalProps {
  customerId: number;
  /** The user (membership) being managed. The modal keys on this; the
   *  parent should remount (via React key) when a different user opens
   *  so the prop-derived membership sub-state never resyncs in an
   *  effect. */
  userId: number;
  /** A display name for the modal header (full name preferred, email
   *  fallback). */
  userLabel: string;
  onClose: () => void;
  /** Called after any change the parent list should reflect (company-
   *  admin flip). The access-editor mutations refresh themselves
   *  internally, but a CCA flip changes the row's collapsed status, so
   *  the parent re-fetches. */
  onChanged: () => void;
}

export function CustomerUserManageModal({
  customerId,
  userId,
  userLabel,
  onClose,
  onChanged,
}: CustomerUserManageModalProps) {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const toast = useToast();

  const [membership, setMembership] = useState<CustomerUserMembership | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ccaBusy, setCcaBusy] = useState(false);

  const demoteRef = useRef<ConfirmDialogHandle>(null);

  // Load the membership (incl. is_company_admin + per-(viewer, customer)
  // actions). All setState happens inside the async closure AFTER an
  // await, never synchronously in the effect body, so there is no
  // set-state-in-effect.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await listCustomerUsers(customerId);
        if (cancelled) return;
        setMembership(
          resp.results.find((m) => m.user_id === userId) ?? null,
        );
        setError("");
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(getApiError(err));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [customerId, userId]);

  async function reloadMembership() {
    try {
      const resp = await listCustomerUsers(customerId);
      setMembership(resp.results.find((m) => m.user_id === userId) ?? null);
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  const isCompanyAdmin = membership?.is_company_admin === true;
  // Data-driven gate — never a hardcoded role. True for SUPER_ADMIN, an
  // in-scope COMPANY_ADMIN when the provider policy allows, and false
  // for customer-side users.
  const canManageCompanyAdmins =
    membership?.actions?.can_manage_customer_company_admins === true;
  // Self-edit guard (UI mirror): an actor cannot change their OWN
  // company-admin status. The backend 403s regardless.
  const isSelf = me?.id === userId;

  async function applyCompanyAdmin(enabled: boolean) {
    setCcaBusy(true);
    setError("");
    try {
      await setCustomerCompanyAdmin(customerId, userId, enabled);
      await reloadMembership();
      toast.push({
        variant: "success",
        title: enabled
          ? t("customer_people.company_admin.toast_granted", {
              user: userLabel,
            })
          : t("customer_people.company_admin.toast_revoked", {
              user: userLabel,
            }),
      });
      onChanged();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setCcaBusy(false);
    }
  }

  function handleMakeCompanyAdmin() {
    void applyCompanyAdmin(true);
  }

  async function handleConfirmDemote() {
    demoteRef.current?.close();
    await applyCompanyAdmin(false);
  }

  return (
    <div
      data-testid="customer-user-manage-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("customer_people.manage_modal.title", { user: userLabel })}
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
          maxWidth: 680,
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
              {t("customer_people.manage_modal.eyebrow")}
            </div>
            <h3 className="section-title" style={{ margin: 0 }}>
              {userLabel}
            </h3>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="customer-user-manage-close"
            onClick={onClose}
            aria-label={t("customer_people.manage_modal.close")}
          >
            <X size={18} strokeWidth={2.2} />
          </button>
        </div>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="customer-user-manage-error"
            style={{ marginBottom: 12 }}
          >
            {error}
          </div>
        )}

        {loading ? (
          <p
            className="muted small"
            data-testid="customer-user-manage-loading"
          >
            {t("customer_people.manage_modal.loading")}
          </p>
        ) : membership === null ? (
          <p className="muted small" data-testid="customer-user-manage-empty">
            {t("customer_people.manage_modal.not_found")}
          </p>
        ) : (
          <>
            {/* Company-admin status + make/remove action. The status
                line is always shown; the action only when the viewer may
                manage company-admins. */}
            <section
              data-testid="customer-user-company-admin-section"
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "12px 14px",
                marginBottom: 14,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 10,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {t("customer_people.company_admin.section_title")}
                  </div>
                  {isCompanyAdmin ? (
                    <div
                      className="role-badge role-badge-customer role-badge-compact"
                      data-access-role="CUSTOMER_COMPANY_ADMIN"
                      data-testid="customer-user-company-admin-status"
                      style={{ marginTop: 6 }}
                    >
                      <span className="role-badge-dot" aria-hidden="true" />
                      <span className="role-badge-text">
                        <span className="role-badge-label">
                          {t(accessRoleLabelKey("CUSTOMER_COMPANY_ADMIN"))}
                        </span>
                      </span>
                    </div>
                  ) : (
                    <div
                      className="muted small"
                      data-testid="customer-user-company-admin-status"
                      style={{ marginTop: 6 }}
                    >
                      {t("customer_people.company_admin.status_not_admin")}
                    </div>
                  )}
                  {isCompanyAdmin && (
                    <div
                      className="muted small"
                      data-testid="customer-user-company-admin-caption"
                      style={{ marginTop: 4 }}
                    >
                      {t("customer_people.company_admin.all_buildings_caption")}
                    </div>
                  )}
                </div>

                {canManageCompanyAdmins && (
                  <div>
                    {isCompanyAdmin ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        data-testid="customer-user-remove-company-admin"
                        onClick={() => demoteRef.current?.open()}
                        disabled={ccaBusy || isSelf}
                      >
                        {t("customer_people.company_admin.remove_button")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        data-testid="customer-user-make-company-admin"
                        onClick={handleMakeCompanyAdmin}
                        disabled={ccaBusy || isSelf}
                      >
                        {t("customer_people.company_admin.make_button")}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {canManageCompanyAdmins && isSelf && (
                <div
                  className="alert-warn"
                  role="alert"
                  data-testid="customer-user-company-admin-self-warning"
                  style={{ marginTop: 10 }}
                >
                  {t("customer_people.company_admin.self_warning")}
                </div>
              )}
            </section>

            {/* Per-building access editor — ONLY for a non-company-admin
                user. A company admin spans all buildings, so there are no
                per-building rows to manage. */}
            {isCompanyAdmin ? (
              <p
                className="muted small"
                data-testid="customer-user-company-admin-access-note"
              >
                {t("customer_people.company_admin.access_note")}
              </p>
            ) : (
              <ContactPermissionsPanel
                key={userId}
                customerId={customerId}
                userId={userId}
              />
            )}
          </>
        )}

        <ConfirmDialog
          ref={demoteRef}
          title={t("customer_people.company_admin.demote_confirm_title", {
            user: userLabel,
          })}
          body={t("customer_people.company_admin.demote_confirm_body")}
          confirmLabel={t("customer_people.company_admin.remove_button")}
          onConfirm={handleConfirmDemote}
          busy={ccaBusy}
          destructive
        />
      </div>
    </div>
  );
}
