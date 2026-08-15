import { useTranslation } from "react-i18next";

/**
 * Sprint 183 §1 — the two billing controls, in ONE place.
 *
 * The owner opened Customer settings, read
 *
 *   Split invoices — One invoice
 *   "Splitting applies within a building. Set 'Invoice addressed to' to
 *    'The building' to use it."
 *
 * and said *"what is this now, I am confused."* He is the person the
 * control exists for, so the control was wrong. Two things were wrong
 * with it, and they need different fixes:
 *
 * 1. **It described a rule instead of showing what it does.** A reader
 *    had to hold two settings in their head to understand one control.
 *    The words that finally landed were an EXAMPLE, so the example is
 *    the copy now: B1 Amsterdam with general cleaning and window
 *    cleaning in one month is either one invoice with both on it, or
 *    two invoices.
 *
 * 2. **It described the dependency instead of showing it.** The split
 *    only means anything when invoices are per building — there is
 *    nothing to split inside a customer-level invoice. So the split
 *    controls are NESTED under the building option rather than sitting
 *    beside it with a sentence explaining when they apply. The
 *    dependency is now spatial: it is visibly part of that choice.
 *
 * The control is kept, not removed and not hidden — the owner asked for
 * it kept. It is out of sight only while the option it belongs to is
 * unselected, which is what nesting means.
 *
 * ## Why a shared component and not two matching blocks
 *
 * Customer settings and the Invoices page's generate dialog describe the
 * SAME decision. Before this sprint they described it in two different
 * vocabularies — settings had target + split (Sprint 182), the generate
 * dialog still had the old three-value granularity list, because 182
 * split the setting and never came back for the dialog.
 *
 * Two blocks worded "identically" drift the first time somebody edits
 * one. One component cannot.
 */

// Sprint 183 §1 — the types and the pair<->wire translation live in
// `api/invoices.ts`, not here. ESLint's `react-refresh/only-export-
// components` is right that a component file exporting functions breaks
// fast refresh, and the translation is a WIRE-FORMAT concern anyway, so
// the API module is its proper home.
import type {
  InvoiceBillingTarget,
  InvoiceSplit,
} from "../api/invoices";

export function BillingTargetFields({
  target,
  split,
  onTargetChange,
  onSplitChange,
  disabled = false,
  idPrefix,
}: {
  target: InvoiceBillingTarget;
  split: InvoiceSplit;
  onTargetChange: (value: InvoiceBillingTarget) => void;
  onSplitChange: (value: InvoiceSplit) => void;
  disabled?: boolean;
  /** Radio groups need distinct `name`s when two instances could ever
   *  share a page, and distinct ids for the label/input pairing. */
  idPrefix: string;
}) {
  const { t } = useTranslation(["invoices", "common"]);

  return (
    <fieldset
      className="field"
      style={{ border: 0, padding: 0, margin: 0 }}
      data-testid={`${idPrefix}-billing-fields`}
    >
      <span className="field-label">{t("billing.target_label")}</span>

      <label
        style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}
      >
        <input
          type="radio"
          name={`${idPrefix}-target`}
          checked={target === "CUSTOMER"}
          onChange={() => onTargetChange("CUSTOMER")}
          disabled={disabled}
          data-testid={`${idPrefix}-target-customer`}
        />
        <span>
          <strong>{t("billing.target_customer")}</strong>
          <span className="muted small" style={{ display: "block" }}>
            {t("billing.target_customer_help")}
          </span>
        </span>
      </label>

      <label
        style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}
      >
        <input
          type="radio"
          name={`${idPrefix}-target`}
          checked={target === "BUILDING"}
          onChange={() => onTargetChange("BUILDING")}
          disabled={disabled}
          data-testid={`${idPrefix}-target-building`}
        />
        <span>
          <strong>{t("billing.target_building")}</strong>
          <span className="muted small" style={{ display: "block" }}>
            {t("billing.target_building_help")}
          </span>
        </span>
      </label>

      {/* THE DEPENDENCY, SHOWN RATHER THAN DESCRIBED. The split lives
          inside the building choice because that is the only place it
          means anything — no sentence needed, and nothing to hold in
          your head. */}
      {target === "BUILDING" && (
        <div
          style={{
            marginTop: 10,
            marginLeft: 26,
            paddingLeft: 12,
            borderLeft: "2px solid var(--line, #e3e3e3)",
          }}
          data-testid={`${idPrefix}-split-block`}
        >
          <span className="field-label">{t("billing.split_label")}</span>

          <label
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              marginTop: 6,
            }}
          >
            <input
              type="radio"
              name={`${idPrefix}-split`}
              checked={split === "NONE"}
              onChange={() => onSplitChange("NONE")}
              disabled={disabled}
              data-testid={`${idPrefix}-split-none`}
            />
            <span>
              <strong>{t("billing.split_none")}</strong>
              {/* The example that landed with the owner. It beats any
                  restatement of the rule. */}
              <span className="muted small" style={{ display: "block" }}>
                {t("billing.split_none_example")}
              </span>
            </span>
          </label>

          <label
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              marginTop: 6,
            }}
          >
            <input
              type="radio"
              name={`${idPrefix}-split`}
              checked={split === "DEPARTMENT_WORK_TYPE"}
              onChange={() => onSplitChange("DEPARTMENT_WORK_TYPE")}
              disabled={disabled}
              data-testid={`${idPrefix}-split-department-work-type`}
            />
            <span>
              <strong>{t("billing.split_department_work_type")}</strong>
              <span className="muted small" style={{ display: "block" }}>
                {t("billing.split_department_work_type_example")}
              </span>
            </span>
          </label>
        </div>
      )}
    </fieldset>
  );
}
