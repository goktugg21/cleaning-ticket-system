// Sprint 2 (frontend) — in-place permission editor for a contact's
// linked user. Opens DOWNWARD under the contact's "Manage permissions"
// toggle (no navigation away). Reuses the matrix orchestration verbatim:
// the same PermissionEditorModal (tri-state inherit/allow/deny groups
// tickets -> extra_work -> users) + effectiveResolver helpers + the
// unchanged PATCH /customers/<id>/users/<uid>/access/<bid>/ save. The
// full matrix page stays the place to add/remove building access; this
// panel surfaces the per-building OVERRIDE editing in place.
//
// Its own testids (contact-permissions-*) are distinct from the matrix /
// modal locked testids (section-customer-overrides-editor,
// customer-overrides-*) so the matrix specs stay green — the modal's
// markup/testids are not forked.
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ExternalLink, Pencil } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  getCustomerPolicy,
  listCustomerUserAccess,
  listCustomerUsers,
  updateCustomerUserAccess,
} from "../../api/admin";
import type {
  CustomerCompanyPolicyAdmin,
  CustomerPermissionKey,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../api/types";
import { CUSTOMER_PERMISSION_KEYS } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { accessRoleLabelKey } from "../../lib/enumLabels";

import { PermissionEditorModal } from "./customer/permissions/PermissionEditorModal";
import type { OverrideDraft } from "./customer/permissions/PermissionEditorModal";
import {
  buildOverridesPayload,
  draftValueFromOverride,
} from "./customer/permissions/effectiveResolver";

export function ContactPermissionsPanel({
  customerId,
  userId,
}: {
  customerId: number;
  userId: number;
}) {
  const { t } = useTranslation("common");
  const { me } = useAuth();

  const [membership, setMembership] = useState<CustomerUserMembership | null>(
    null,
  );
  const [accessRows, setAccessRows] = useState<CustomerUserBuildingAccess[]>([]);
  const [policy, setPolicy] = useState<CustomerCompanyPolicyAdmin | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Override modal state — mirrors CustomerPermissionsPage exactly so the
  // reused PermissionEditorModal behaves identically here.
  const emptyOverrideDraft = useMemo<OverrideDraft>(() => {
    const d = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) d[key] = "inherit";
    return d;
  }, []);
  const [editingAccess, setEditingAccess] =
    useState<CustomerUserBuildingAccess | null>(null);
  const [overrideDraft, setOverrideDraft] =
    useState<OverrideDraft>(emptyOverrideDraft);
  const [overrideSaving, setOverrideSaving] = useState(false);

  // Load the membership (for the modal's user label + self gate), this
  // user's per-building access rows, and the company policy — once per
  // (customer, user). All setState happens inside the async closure
  // AFTER an await, never synchronously in the effect body, so there is
  // no set-state-in-effect.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [usersResp, accessResp, policyData] = await Promise.all([
          listCustomerUsers(customerId),
          listCustomerUserAccess(customerId, userId),
          getCustomerPolicy(customerId),
        ]);
        if (cancelled) return;
        setMembership(
          usersResp.results.find((m) => m.user_id === userId) ?? null,
        );
        setAccessRows(accessResp.results);
        setPolicy(policyData);
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

  async function reloadAccess() {
    try {
      const resp = await listCustomerUserAccess(customerId, userId);
      setAccessRows(resp.results);
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  function openEditor(access: CustomerUserBuildingAccess) {
    const draft = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) {
      draft[key as CustomerPermissionKey] = draftValueFromOverride(
        access.permission_overrides ?? {},
        key as CustomerPermissionKey,
      );
    }
    setOverrideDraft(draft);
    setEditingAccess(access);
  }

  function closeEditor() {
    setEditingAccess(null);
    setOverrideDraft(emptyOverrideDraft);
  }

  async function handleSaveOverrides() {
    if (!editingAccess) return;
    setOverrideSaving(true);
    setError("");
    try {
      await updateCustomerUserAccess(customerId, userId, editingAccess.building_id, {
        permission_overrides: buildOverridesPayload(overrideDraft),
      });
      await reloadAccess();
      closeEditor();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setOverrideSaving(false);
    }
  }

  const editingIsSelf = editingAccess ? me?.id === editingAccess.user_id : false;
  const matrixHref = `/admin/customers/${customerId}/permissions?focus_user=${userId}`;

  return (
    <div
      className="card"
      data-testid="contact-permissions-panel"
      style={{ marginTop: 12, padding: "14px 16px 16px" }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--text-faint)",
          marginBottom: 10,
        }}
      >
        {t("customer_contacts.permissions_panel_title")}
      </div>

      {error && (
        <div
          className="alert-error"
          role="alert"
          data-testid="contact-permissions-error"
          style={{ marginBottom: 10 }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <p className="muted small" data-testid="contact-permissions-loading">
          {t("customer_contacts.permissions_panel_loading")}
        </p>
      ) : accessRows.length === 0 ? (
        <div data-testid="contact-permissions-empty">
          <p className="muted small" style={{ margin: 0 }}>
            {t("customer_contacts.permissions_panel_empty")}
          </p>
          <p className="muted small" style={{ margin: "4px 0 0" }}>
            {t("customer_contacts.permissions_panel_empty_hint")}
          </p>
        </div>
      ) : (
        <ul
          data-testid="contact-permissions-building-list"
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {accessRows.map((access) => {
            const overrideCount = Object.keys(
              access.permission_overrides ?? {},
            ).length;
            return (
              <li
                key={access.building_id}
                data-testid="contact-permissions-building-row"
                data-building-id={access.building_id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "8px 10px",
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontWeight: 600 }}>{access.building_name}</span>
                  <span
                    className="muted small"
                    style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
                  >
                    <span>{t(accessRoleLabelKey(access.access_role))}</span>
                    {access.is_active === false && (
                      <span data-testid="contact-permissions-inactive">
                        · {t("customer_contacts.permissions_panel_inactive")}
                      </span>
                    )}
                    {overrideCount > 0 && (
                      <span
                        className="badge badge-waiting_customer_approval"
                        data-testid="contact-permissions-custom-badge"
                      >
                        {t("customer_contacts.permissions_panel_custom_badge")}
                      </span>
                    )}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  data-testid="contact-permissions-edit-button"
                  onClick={() => openEditor(access)}
                  disabled={membership === null}
                >
                  <Pencil size={13} strokeWidth={2} />
                  {t("customer_contacts.permissions_panel_edit_button")}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* Secondary link to the full matrix — building add/remove scoping
          stays there (the sanctioned ?focus_user= deep-link). */}
      <div style={{ marginTop: 12 }}>
        <Link
          to={matrixHref}
          className="btn btn-ghost btn-sm"
          data-testid="customer-contact-manage-permissions"
        >
          <ExternalLink size={13} strokeWidth={2} />
          {t("customer_contacts.permissions_panel_matrix_link")}
        </Link>
        <div className="muted small" style={{ marginTop: 6 }}>
          {t("customer_contacts.permissions_panel_matrix_hint")}
        </div>
      </div>

      {/* Reused matrix modal — verbatim, so its locked testids
          (section-customer-overrides-editor, customer-overrides-*) keep
          belonging to the matrix specs. */}
      <PermissionEditorModal
        open={editingAccess !== null}
        membership={membership}
        access={editingAccess}
        policy={policy}
        draft={overrideDraft}
        setDraft={setOverrideDraft}
        onClose={closeEditor}
        onSave={handleSaveOverrides}
        saving={overrideSaving}
        isSelf={editingIsSelf}
      />
    </div>
  );
}
