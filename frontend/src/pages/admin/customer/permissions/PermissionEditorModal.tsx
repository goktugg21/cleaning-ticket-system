import { useCallback, useEffect, useMemo, useRef } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  CustomerCompanyPolicyAdmin,
  CustomerPermissionKey,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../../api/types";
import { accessRoleLabelKey } from "../../../../lib/enumLabels";

import {
  effectiveLabelKey,
  resolveEffective,
  type OverrideDraftValue,
} from "./effectiveResolver";
import {
  PERMISSION_GROUP_LABEL_KEY,
  PERMISSION_KEY_ROWS,
  type PermissionGroup,
  type PermissionKeyRow,
} from "./permissionKeyLabels";
import { TriStateBubbleRadio } from "./TriStateBubbleRadio";

/**
 * Sprint 31 Phase 6 — REPLACES `OverrideDrawer` with a centered modal.
 *
 * Tri-state Inherit / Allow / Deny optical-bubble radios for the 16
 * customer.* permission keys, grouped by Tickets / Extra Work /
 * Users. Permission TRUTH stays in `effectiveResolver`:
 *   - the inline "Effective: …" hint comes from `resolveEffective` +
 *     `effectiveLabelKey`,
 *   - the policy-blocked decision comes from
 *     `resolveEffective(...).reason === "policy"`,
 *   - the save payload is built by the caller using the existing
 *     `buildOverridesPayload` helper against the unchanged PATCH
 *     `/api/customers/<id>/users/<uid>/access/<bid>/` endpoint.
 *
 * Policy-blocked semantics (mirrors the OverrideDrawer behaviour the
 * 27E spec locks): when the company policy currently denies a key's
 * family, the modal disables the row's tri-state and shows an
 * explicit "Blocked by customer company policy" hint. The DRAFT
 * value is still preserved in state — policy blocks effect, not
 * storage — so flipping the company policy back ON restores the
 * operator's intent without re-typing.
 *
 * Locked testids relocated from the drawer (Sprint 27E / 28 Batch
 * 15.2 specs assert these):
 *   - `section-customer-overrides-editor` (modal root)
 *   - `customer-overrides-table`
 *   - `customer-overrides-row` + `data-permission-key`
 *   - `customer-overrides-radio` + `value="inherit|allow|deny"`
 *     (rendered inside `TriStateBubbleRadio`)
 *   - `customer-overrides-close`
 *   - `customer-overrides-save`
 */

export type OverrideDraft = Record<CustomerPermissionKey, OverrideDraftValue>;

export interface PermissionEditorModalProps {
  open: boolean;
  membership: CustomerUserMembership | null;
  access: CustomerUserBuildingAccess | null;
  policy: CustomerCompanyPolicyAdmin | null;
  draft: OverrideDraft;
  setDraft: (next: OverrideDraft) => void;
  onClose: () => void;
  onSave: () => void;
  saving: boolean;
  /** True if the access row's user is the active user (cannot edit own access). */
  isSelf: boolean;
}

export function PermissionEditorModal({
  open,
  membership,
  access,
  policy,
  draft,
  setDraft,
  onClose,
  onSave,
  saving,
  isSelf,
}: PermissionEditorModalProps) {
  const { t } = useTranslation("common");
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  // Stash the trigger element so focus returns there on close.
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Capture the focused element when the modal opens; restore on close.
  useEffect(() => {
    if (open) {
      previousFocusRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      requestAnimationFrame(() => {
        closeButtonRef.current?.focus();
      });
    } else {
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    }
  }, [open]);

  // Escape closes.
  useEffect(() => {
    if (!open) return;
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Focus trap — keep Tab cycling inside the modal.
  useEffect(() => {
    if (!open) return;
    function handleTab(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const root = modalRef.current;
      if (!root) return;
      const focusables = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first) {
          event.preventDefault();
          last.focus();
        }
      } else {
        if (active === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleTab);
    return () => document.removeEventListener("keydown", handleTab);
  }, [open]);

  const groupedRows = useMemo(() => {
    const grouped: Record<PermissionGroup, PermissionKeyRow[]> = {
      tickets: [],
      extra_work: [],
      users: [],
    };
    for (const row of PERMISSION_KEY_ROWS) grouped[row.group].push(row);
    return grouped;
  }, []);

  const handleRadioChange = useCallback(
    (key: CustomerPermissionKey, value: OverrideDraftValue) => {
      setDraft({ ...draft, [key]: value });
    },
    [draft, setDraft],
  );

  if (!open || !membership || !access) {
    return null;
  }

  const userName = membership.user_full_name?.trim() || membership.user_email;

  return (
    <div
      className="permission-editor-modal-backdrop"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        className="permission-editor-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="permission-editor-modal-title"
        data-testid="section-customer-overrides-editor"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="permission-editor-modal-header">
          <div className="permission-editor-modal-header-text">
            <h3
              id="permission-editor-modal-title"
              className="permission-editor-modal-title"
            >
              {t("customer_permissions.overrides_drawer.title")}
            </h3>
            <p className="permission-editor-modal-subtitle">
              {t("customer_permissions.overrides_drawer.subtitle", {
                user: userName,
                building: access.building_name,
              })}
            </p>
            <p className="permission-editor-modal-role-caption">
              {t("customer_permissions.overrides_drawer.role_caption", {
                role: t(accessRoleLabelKey(access.access_role)),
              })}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="permission-editor-modal-close"
            data-testid="customer-overrides-close"
            onClick={onClose}
            aria-label={t("customer_permissions.overrides_drawer.close")}
          >
            <X size={18} strokeWidth={2.2} />
          </button>
        </header>

        <div className="permission-editor-modal-body">
          {isSelf && (
            <div className="alert-warn permission-editor-modal-warning" role="alert">
              {t("customer_permissions.overrides_drawer.self_warning")}
            </div>
          )}
          {access.is_active === false && (
            <div className="alert-warn permission-editor-modal-warning" role="alert">
              {t("customer_permissions.overrides_drawer.inactive_warning")}
            </div>
          )}

          <table
            className="permission-editor-modal-table"
            data-testid="customer-overrides-table"
          >
            <tbody>
              {(["tickets", "extra_work", "users"] as const).map((group) => (
                <ModalGroup
                  key={group}
                  groupLabel={t(PERMISSION_GROUP_LABEL_KEY[group])}
                  rows={groupedRows[group]}
                  draft={draft}
                  policy={policy}
                  access={access}
                  saving={saving}
                  isSelf={isSelf}
                  onChange={handleRadioChange}
                />
              ))}
            </tbody>
          </table>
        </div>

        <footer className="permission-editor-modal-footer">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            disabled={saving}
          >
            {t("customer_permissions.overrides_drawer.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="customer-overrides-save"
            onClick={onSave}
            disabled={saving || isSelf}
          >
            {t("customer_permissions.overrides_drawer.save")}
          </button>
        </footer>
      </div>
    </div>
  );
}

interface ModalGroupProps {
  groupLabel: string;
  rows: PermissionKeyRow[];
  draft: OverrideDraft;
  policy: CustomerCompanyPolicyAdmin | null;
  access: CustomerUserBuildingAccess;
  saving: boolean;
  isSelf: boolean;
  onChange: (key: CustomerPermissionKey, value: OverrideDraftValue) => void;
}

function ModalGroup({
  groupLabel,
  rows,
  draft,
  policy,
  access,
  saving,
  isSelf,
  onChange,
}: ModalGroupProps) {
  const { t } = useTranslation("common");
  return (
    <>
      <tr className="permission-editor-modal-group">
        <th colSpan={2}>
          <span className="permission-editor-modal-group-title">{groupLabel}</span>
        </th>
      </tr>
      {rows.map((row) => {
        const draftValue = draft[row.key] ?? "inherit";
        const effective = resolveEffective({
          key: row.key,
          draftValue,
          isActive: access.is_active !== false,
          policy,
          accessRole: access.access_role,
        });
        // Policy-blocked branch: the resolver returns reason === "policy"
        // when CustomerCompanyPolicy currently denies this key's family.
        // We disable the tri-state in this case AND show explicit copy,
        // but the underlying draft VALUE is preserved (storage is not
        // erased; policy only blocks effect — matches the resolver's
        // single source of truth).
        const policyBlocked =
          effective.effective === "deny" && effective.reason === "policy";
        const radioGroupName = `overrides-${access.user_id}-${access.building_id}-${row.key}`;
        const disabled = saving || isSelf || policyBlocked;
        return (
          <tr
            key={row.key}
            className={`permission-editor-modal-row${
              policyBlocked ? " permission-editor-modal-row-policy-blocked" : ""
            }`}
            data-testid="customer-overrides-row"
            data-permission-key={row.key}
          >
            <td className="permission-editor-modal-row-info">
              <div className="permission-editor-modal-row-label">
                {t(`customer_permissions.permission_keys.${row.key}.label`)}
              </div>
              <div className="permission-editor-modal-row-description">
                {t(`customer_permissions.permission_keys.${row.key}.description`)}
              </div>
              {policyBlocked ? (
                <div
                  className="permission-editor-modal-row-policy-text"
                  data-testid="permission-editor-row-policy-blocked"
                >
                  {t("customer_permissions.matrix.policy_blocked")}
                </div>
              ) : (
                <div
                  className={`permission-editor-modal-row-effective effective-hint-${effective.effective}`}
                >
                  {t(effectiveLabelKey(effective))}
                </div>
              )}
            </td>
            <td className="permission-editor-modal-row-radios">
              <TriStateBubbleRadio
                name={radioGroupName}
                permissionKey={row.key}
                value={draftValue}
                onChange={(next) => onChange(row.key, next)}
                disabled={disabled}
              />
            </td>
          </tr>
        );
      })}
    </>
  );
}
