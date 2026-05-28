import { useTranslation } from "react-i18next";

import type { CustomerPermissionKey } from "../../../../api/types";
import type { OverrideDraftValue } from "./effectiveResolver";

/**
 * Sprint 31 Phase 6 — tri-state optical-bubble radio.
 *
 * Three answer-sheet bubbles in a row: Inherit / Allow / Deny. The
 * selected option's bubble fills; the others stay outlined. Wraps
 * native `<input type="radio">` per option so screen-readers and
 * keyboard navigation behave naturally; the radios are
 * `.visually-hidden` and the bubble + label are the visible target.
 *
 * Locked testids preserved verbatim:
 *   - `customer-overrides-radio` on each <input>
 *   - `value="inherit|allow|deny"` so existing Playwright locators
 *     (e.g. `[data-testid="customer-overrides-radio"][value="allow"]`)
 *     keep resolving.
 */
const OPTIONS: ReadonlyArray<OverrideDraftValue> = [
  "inherit",
  "allow",
  "deny",
];

export interface TriStateBubbleRadioProps {
  name: string;
  permissionKey: CustomerPermissionKey;
  value: OverrideDraftValue;
  onChange: (next: OverrideDraftValue) => void;
  disabled?: boolean;
}

export function TriStateBubbleRadio({
  name,
  permissionKey,
  value,
  onChange,
  disabled = false,
}: TriStateBubbleRadioProps) {
  const { t } = useTranslation("common");
  return (
    <div className="tri-state-bubble-radio" role="radiogroup">
      {OPTIONS.map((opt) => {
        const selected = value === opt;
        return (
          <label
            key={opt}
            className={`tri-state-bubble-option tri-state-bubble-option-${opt}${
              selected ? " tri-state-bubble-option-selected" : ""
            }${disabled ? " tri-state-bubble-option-disabled" : ""}`}
          >
            <input
              type="radio"
              className="visually-hidden"
              name={name}
              value={opt}
              checked={selected}
              disabled={disabled}
              onChange={() => onChange(opt)}
              data-testid="customer-overrides-radio"
              data-permission-key={permissionKey}
            />
            <span
              className={`permission-bubble tri-state-bubble${
                selected ? " tri-state-bubble-selected" : " tri-state-bubble-empty"
              }`}
              aria-hidden="true"
            />
            <span className="tri-state-bubble-label">
              {t(`customer_permissions.overrides_drawer.${opt}`)}
            </span>
          </label>
        );
      })}
    </div>
  );
}
