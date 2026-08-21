/**
 * W-H §3 — ONE period control, on every list of dated work.
 *
 * A dropdown of four, and the two date boxes appear INSIDE the custom
 * option rather than beside it — the same spatial dependency
 * `BillingTargetFields` uses, and for the same reason: a sentence
 * saying "these apply when you pick Custom" is a sentence explaining a
 * control, which means the control is wrong.
 *
 * No prose, no helper line, no clear-button. The option names say what
 * they select, and switching back to This month is how you clear it.
 */
import { useTranslation } from "react-i18next";

import { PERIOD_KEYS, PERIOD_LABEL_KEY } from "../lib/period";
import type { PeriodKey, PeriodState } from "../lib/period";

export function PeriodFilter({
  value,
  onChange,
  idPrefix,
}: {
  value: PeriodState;
  onChange: (next: PeriodState) => void;
  /** Two lists can share a page; ids and the label pairing need to be
   *  distinct when they do. */
  idPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="period-filter" data-testid={`${idPrefix}-period`}>
      <label className="field">
        <span className="field-label">{t("period.label")}</span>
        <select
          className="field-select"
          id={`${idPrefix}-period-select`}
          value={value.key}
          onChange={(event) =>
            onChange({ ...value, key: event.target.value as PeriodKey })
          }
          data-testid={`${idPrefix}-period-select`}
        >
          {PERIOD_KEYS.map((key) => (
            <option key={key} value={key}>
              {t(PERIOD_LABEL_KEY[key])}
            </option>
          ))}
        </select>
      </label>

      {value.key === "custom" && (
        <div className="period-filter-range" data-testid={`${idPrefix}-period-range`}>
          <label className="field">
            <span className="field-label">{t("period.from")}</span>
            <input
              type="date"
              className="field-input"
              value={value.from}
              max={value.to || undefined}
              onChange={(event) =>
                onChange({ ...value, from: event.target.value })
              }
              data-testid={`${idPrefix}-period-from`}
            />
          </label>
          <label className="field">
            <span className="field-label">{t("period.to")}</span>
            <input
              type="date"
              className="field-input"
              value={value.to}
              min={value.from || undefined}
              onChange={(event) =>
                onChange({ ...value, to: event.target.value })
              }
              data-testid={`${idPrefix}-period-to`}
            />
          </label>
        </div>
      )}
    </div>
  );
}
