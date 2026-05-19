import type { Dispatch, SetStateAction } from "react";
import type { LucideIcon } from "lucide-react";
import { BadgeCheck, Ticket, Wallet, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CustomerCompanyPolicyAdmin } from "../../../../api/types";

/**
 * Sprint 28 Batch 15.2 — replaces the 4 stacked checkboxes that
 * were buried at the bottom of the legacy permissions page.
 *
 * Each card represents one policy boolean. When the toggle is OFF
 * the card carries a `policy-toggle-card-warning` modifier so the
 * operator can scan the grid and see at a glance where the
 * customer-company policy is currently narrowing what every user
 * at this customer can do. The keys-affected sub-line tells the
 * operator exactly which permission keys flip to deny when the
 * card is off — answering "what does this policy actually take
 * away" without making them open the override drawer.
 *
 * data-testid="customer-policy-toggle" + data-policy-field are
 * preserved as the locked attributes the existing Playwright spec
 * asserts on.
 */
export type PolicyDraft = Pick<
  CustomerCompanyPolicyAdmin,
  | "customer_users_can_create_tickets"
  | "customer_users_can_approve_ticket_completion"
  | "customer_users_can_create_extra_work"
  | "customer_users_can_approve_extra_work_pricing"
>;

type PolicyField = keyof PolicyDraft;

interface PolicyCardSpec {
  field: PolicyField;
  icon: LucideIcon;
  titleKey: string;
  helperKey: string;
  affectedKeys: ReadonlyArray<string>;
}

const CARDS: ReadonlyArray<PolicyCardSpec> = [
  {
    field: "customer_users_can_create_tickets",
    icon: Ticket,
    titleKey: "customer_form.policy_field_create_tickets",
    helperKey: "customer_permissions.policy_card.create_tickets.helper",
    affectedKeys: ["customer.ticket.create"],
  },
  {
    field: "customer_users_can_approve_ticket_completion",
    icon: BadgeCheck,
    titleKey: "customer_form.policy_field_approve_ticket_completion",
    helperKey:
      "customer_permissions.policy_card.approve_ticket_completion.helper",
    affectedKeys: [
      "customer.ticket.approve_own",
      "customer.ticket.approve_location",
    ],
  },
  {
    field: "customer_users_can_create_extra_work",
    icon: Wrench,
    titleKey: "customer_form.policy_field_create_extra_work",
    helperKey: "customer_permissions.policy_card.create_extra_work.helper",
    affectedKeys: ["customer.extra_work.create"],
  },
  {
    field: "customer_users_can_approve_extra_work_pricing",
    icon: Wallet,
    titleKey: "customer_form.policy_field_approve_extra_work_pricing",
    helperKey:
      "customer_permissions.policy_card.approve_extra_work_pricing.helper",
    affectedKeys: [
      "customer.extra_work.approve_own",
      "customer.extra_work.approve_location",
    ],
  },
];

export interface PolicyToggleGridProps {
  draft: PolicyDraft;
  setDraft: Dispatch<SetStateAction<PolicyDraft>>;
  disabled?: boolean;
}

export function PolicyToggleGrid({
  draft,
  setDraft,
  disabled = false,
}: PolicyToggleGridProps) {
  const { t } = useTranslation("common");

  return (
    <div className="policy-toggle-grid">
      {CARDS.map((card) => {
        const enabled = draft[card.field];
        const Icon = card.icon;
        return (
          <label
            key={card.field}
            className={`policy-toggle-card${
              enabled ? "" : " policy-toggle-card-warning"
            }`}
          >
            <span className="policy-toggle-card-icon" aria-hidden="true">
              <Icon size={18} strokeWidth={1.9} />
            </span>
            <span className="policy-toggle-card-body">
              <span className="policy-toggle-card-title">
                {t(card.titleKey)}
              </span>
              <span className="policy-toggle-card-helper">
                {t(card.helperKey)}
              </span>
              <span className="policy-toggle-card-affects">
                {t("customer_permissions.policy_card_affects", {
                  keys: card.affectedKeys.join(", "),
                })}
              </span>
              {!enabled && (
                <span className="policy-toggle-card-warning-text">
                  {t("customer_permissions.policy_warning_disabled")}
                </span>
              )}
            </span>
            <input
              type="checkbox"
              className="policy-toggle-card-switch"
              data-testid="customer-policy-toggle"
              data-policy-field={card.field}
              checked={enabled}
              disabled={disabled}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  [card.field]: event.target.checked,
                }))
              }
            />
          </label>
        );
      })}
    </div>
  );
}

