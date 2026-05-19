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
  type PermissionKeyRow,
} from "./permissionKeyLabels";

/**
 * Sprint 28 Batch 15.2 — Right-side drawer that replaces the inline
 * overrides section. Renders the 16 customer permission keys
 * grouped by domain (Tickets / Extra Work / Users) with a tri-state
 * Inherit/Allow/Deny radio set per key and an inline "Effective:
 * ..." hint computed by the display-only resolver.
 *
 * Locked testids preserved:
 *   - section-customer-overrides-editor (on the drawer wrapper)
 *   - customer-overrides-table
 *   - customer-overrides-row (one per key)
 *   - customer-overrides-radio (3 per row; value = inherit|allow|deny)
 *   - customer-overrides-close
 *   - customer-overrides-save
 *
 * Sprint 29 Batch 29.8.5 — the (key, group) table + per-group i18n
 * pointer moved to `./permissionKeyLabels` so the new inline
 * AccessPermissionsPanel can reuse the exact same shape without
 * duplicating the list.
 */

type KeyRow = PermissionKeyRow;

export type OverrideDraft = Record<CustomerPermissionKey, OverrideDraftValue>;

export interface OverrideDrawerProps {
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

export function OverrideDrawer({
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
}: OverrideDrawerProps) {
  const { t } = useTranslation("common");
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  // Stash the trigger element so focus returns there on close.
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Capture the focused element when the drawer opens; restore on close.
  useEffect(() => {
    if (open) {
      previousFocusRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      // Defer focus by one frame so the drawer is mounted before focus shifts.
      requestAnimationFrame(() => {
        closeButtonRef.current?.focus();
      });
    } else {
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    }
  }, [open]);

  // Escape closes the drawer.
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

  // Focus trap — keep Tab cycling inside the drawer.
  useEffect(() => {
    if (!open) return;
    function handleTab(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const root = drawerRef.current;
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
    const grouped: Record<KeyRow["group"], KeyRow[]> = {
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
    <>
      <div
        className="override-drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        ref={drawerRef}
        className="override-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="override-drawer-title"
        data-testid="section-customer-overrides-editor"
      >
        <header className="override-drawer-header">
          <div className="override-drawer-header-text">
            <h3
              id="override-drawer-title"
              className="override-drawer-title"
            >
              {t("customer_permissions.overrides_drawer.title")}
            </h3>
            <p className="override-drawer-subtitle">
              {t("customer_permissions.overrides_drawer.subtitle", {
                user: userName,
                building: access.building_name,
              })}
            </p>
            <p className="override-drawer-role-caption">
              {t("customer_permissions.overrides_drawer.role_caption", {
                role: t(accessRoleLabelKey(access.access_role)),
              })}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="override-drawer-close"
            data-testid="customer-overrides-close"
            onClick={onClose}
            aria-label={t("customer_permissions.overrides_drawer.close")}
          >
            <X size={18} strokeWidth={2.2} />
          </button>
        </header>

        <div className="override-drawer-body">
          {isSelf && (
            <div className="alert-warn override-drawer-warning" role="alert">
              {t("customer_permissions.overrides_drawer.self_warning")}
            </div>
          )}
          {access.is_active === false && (
            <div className="alert-warn override-drawer-warning" role="alert">
              {t("customer_permissions.overrides_drawer.inactive_warning")}
            </div>
          )}

          <table
            className="override-drawer-table"
            data-testid="customer-overrides-table"
          >
            <tbody>
              {(["tickets", "extra_work", "users"] as const).map((group) => (
                <OverrideGroup
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

        <footer className="override-drawer-footer">
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
      </aside>
    </>
  );
}

interface OverrideGroupProps {
  groupLabel: string;
  rows: KeyRow[];
  draft: OverrideDraft;
  policy: CustomerCompanyPolicyAdmin | null;
  access: CustomerUserBuildingAccess;
  saving: boolean;
  isSelf: boolean;
  onChange: (key: CustomerPermissionKey, value: OverrideDraftValue) => void;
}

function OverrideGroup({
  groupLabel,
  rows,
  draft,
  policy,
  access,
  saving,
  isSelf,
  onChange,
}: OverrideGroupProps) {
  const { t } = useTranslation("common");
  return (
    <>
      <tr className="override-drawer-group">
        <th colSpan={2}>
          <span className="override-drawer-group-title">{groupLabel}</span>
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
        const radioGroupName = `overrides-${access.user_id}-${access.building_id}-${row.key}`;
        return (
          <tr
            key={row.key}
            className="override-row"
            data-testid="customer-overrides-row"
            data-permission-key={row.key}
          >
            <td className="override-row-info">
              <div className="override-row-label">
                {t(
                  `customer_permissions.permission_keys.${row.key}.label`,
                )}
              </div>
              <div className="override-row-description">
                {t(
                  `customer_permissions.permission_keys.${row.key}.description`,
                )}
              </div>
              <div
                className={`override-row-effective effective-hint-${
                  effective.effective
                }`}
              >
                {t(effectiveLabelKey(effective))}
              </div>
            </td>
            <td className="override-row-radios">
              <fieldset
                className="override-row-radio-group"
                disabled={saving || isSelf}
              >
                <legend className="visually-hidden">
                  {t(
                    `customer_permissions.permission_keys.${row.key}.label`,
                  )}
                </legend>
                {(["inherit", "allow", "deny"] as const).map((opt) => (
                  <label
                    key={opt}
                    className={`override-radio-option${
                      draftValue === opt ? " override-radio-option-active" : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name={radioGroupName}
                      value={opt}
                      data-testid="customer-overrides-radio"
                      data-permission-key={row.key}
                      checked={draftValue === opt}
                      onChange={() => onChange(row.key, opt)}
                    />
                    <span>
                      {t(`customer_permissions.overrides_drawer.${opt}`)}
                    </span>
                  </label>
                ))}
              </fieldset>
            </td>
          </tr>
        );
      })}
    </>
  );
}

