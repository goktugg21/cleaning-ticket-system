import { useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { LucideIcon } from "lucide-react";
import { FolderArchive, Ticket, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "../../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../../components/ConfirmDialog";
import type { PolicyDraft } from "./PolicyToggleGrid";
import { Toggle } from "../../../../components/Toggle";

/**
 * RF-8 (approved 2026-06-26) — the simple permission-bundle view.
 *
 * Two module cards (Meldingen / Extra werk), each a master on/off plus
 * the module's coarse toggles. Pure presentation over the SAME
 * `PolicyDraft` the detailed PolicyToggleGrid edits (behind Advanced):
 * master ON means "any of the module's flags is on" — a mixed module
 * renders the master as on with the toggles reflecting reality, never
 * a fake tri-state. Turning a master OFF flips every underlying flag
 * of that module to off in the draft (confirm-guarded — it strips
 * settings); turning it ON restores all flags to on (the default) and
 * re-enables the toggles. Saving stays with the page's StickySaveBar.
 *
 * NOTE — a "May send messages" toggle was in the approved design but
 * is intentionally ABSENT: no messaging-permission flag exists in the
 * backend (verified: CustomerCompanyPolicy fields + the 16
 * CUSTOMER_PERMISSION_KEYS carry no message/comment key; posting is
 * gated by role + scope only). Do not invent one here — it needs its
 * own backend sprint first.
 */

type PolicyField = keyof PolicyDraft;

interface ModuleSpec {
  key: "meldingen" | "extra_werk" | "documenten";
  icon: LucideIcon;
  titleKey: string;
  /** Sprint 157 §5 — one line saying what this module lets the
   *  customer's people DO.
   *
   *  The Documents card is `masterOnly`, so its toggle region renders
   *  nothing and the whole card read "Documents / Module enabled" — a
   *  title and a state, with no statement of what the module is. Its two
   *  siblings at least had descriptive sub-toggles to infer from.
   *
   *  Every card carries the line, not just Documents: a description that
   *  appears on one card and not the others reads as an exception rather
   *  than as information. */
  descriptionKey: string;
  toggles: ReadonlyArray<{ field: PolicyField; labelKey: string }>;
  // Sprint 126 — a single-key module (Documenten) is JUST a master toggle:
  // the master IS the one field, so the redundant sub-toggle row is hidden.
  masterOnly?: boolean;
}

const MODULES: ReadonlyArray<ModuleSpec> = [
  {
    key: "meldingen",
    icon: Ticket,
    titleKey: "customer_permissions.modules.meldingen.title",
    descriptionKey: "customer_permissions.modules.meldingen.description",
    toggles: [
      {
        field: "customer_users_can_create_tickets",
        labelKey: "customer_permissions.modules.meldingen.toggle_open",
      },
      {
        field: "customer_users_can_approve_ticket_completion",
        labelKey: "customer_permissions.modules.meldingen.toggle_approve",
      },
    ],
  },
  {
    key: "extra_werk",
    icon: Wrench,
    titleKey: "customer_permissions.modules.extra_werk.title",
    descriptionKey: "customer_permissions.modules.extra_werk.description",
    toggles: [
      {
        field: "customer_users_can_create_extra_work",
        labelKey: "customer_permissions.modules.extra_werk.toggle_request",
      },
      {
        field: "customer_users_can_approve_extra_work_pricing",
        labelKey:
          "customer_permissions.modules.extra_werk.toggle_approve_pricing",
      },
    ],
  },
  {
    key: "documenten",
    icon: FolderArchive,
    titleKey: "customer_permissions.modules.documenten.title",
    descriptionKey: "customer_permissions.modules.documenten.description",
    masterOnly: true,
    toggles: [
      {
        field: "customer_users_can_manage_documents",
        labelKey: "customer_permissions.modules.documenten.title",
      },
    ],
  },
];

export function ModuleBundleCards({
  draft,
  setDraft,
  disabled = false,
}: {
  draft: PolicyDraft;
  setDraft: Dispatch<SetStateAction<PolicyDraft>>;
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");
  const confirmRef = useRef<ConfirmDialogHandle>(null);
  const [pendingOff, setPendingOff] = useState<ModuleSpec | null>(null);

  const setModule = (module: ModuleSpec, value: boolean) =>
    setDraft((prev) => {
      const next = { ...prev };
      for (const toggle of module.toggles) next[toggle.field] = value;
      return next;
    });

  const requestMasterChange = (module: ModuleSpec, nextOn: boolean) => {
    if (nextOn) {
      setModule(module, true);
      return;
    }
    setPendingOff(module);
    confirmRef.current?.open();
  };

  return (
    <div className="module-bundle-grid" data-testid="module-bundle-grid">
      {MODULES.map((module) => {
        const masterOn = module.toggles.some((tg) => draft[tg.field]);
        const Icon = module.icon;
        return (
          <div
            key={module.key}
            className={
              masterOn
                ? "module-bundle-card"
                : "module-bundle-card module-bundle-card-off"
            }
            data-testid="module-bundle-card"
            data-module={module.key}
            data-module-on={masterOn ? "true" : "false"}
          >
            <div className="module-bundle-head">
              <span className="module-bundle-icon" aria-hidden="true">
                <Icon size={18} strokeWidth={1.9} />
              </span>
              <span className="module-bundle-title">{t(module.titleKey)}</span>
              <label className="module-bundle-master">
                <span>
                  {masterOn
                    ? t("customer_permissions.modules.master_on")
                    : t("customer_permissions.modules.master_off")}
                </span>
                <Toggle
                  data-testid="module-bundle-master"
                  data-module={module.key}
                  checked={masterOn}
                  disabled={disabled}
                  onChange={(event) =>
                    requestMasterChange(module, event.target.checked)
                  }
                />
              </label>
            </div>
            <p className="module-bundle-description">
              {t(module.descriptionKey)}
            </p>
            <div className="module-bundle-toggles">
              {!module.masterOnly &&
                module.toggles.map((toggle) => (
                <label
                  key={toggle.field}
                  className={
                    masterOn
                      ? "module-bundle-toggle"
                      : "module-bundle-toggle module-bundle-toggle-disabled"
                  }
                >
                  <Toggle
                    data-testid="module-bundle-toggle"
                    data-policy-field={toggle.field}
                    checked={draft[toggle.field]}
                    disabled={disabled || !masterOn}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        [toggle.field]: event.target.checked,
                      }))
                    }
                  />
                  <span>{t(toggle.labelKey)}</span>
                </label>
              ))}
              {!masterOn && (
                <p className="module-bundle-off-note">
                  {t("customer_permissions.modules.off_note")}
                </p>
              )}
            </div>
          </div>
        );
      })}

      <ConfirmDialog
        ref={confirmRef}
        title={t("customer_permissions.modules.master_off_title", {
          module: pendingOff ? t(pendingOff.titleKey) : "",
        })}
        body={t("customer_permissions.modules.master_off_body")}
        confirmLabel={t("customer_permissions.modules.master_off_confirm")}
        onConfirm={() => {
          if (pendingOff) setModule(pendingOff, false);
          confirmRef.current?.close();
          setPendingOff(null);
        }}
        onCancel={() => setPendingOff(null)}
        destructive
      />
    </div>
  );
}
