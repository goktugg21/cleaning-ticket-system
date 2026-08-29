/**
 * FE-4/FE-5 — the "iets anders" lines: every custom line is a CART
 * LINE like the priced ones — a title, an optional note, and "prijs
 * volgt" where a price would stand. One empty row is always offered;
 * "Nog iets anders toevoegen" adds another. Shared by the customer's
 * guided flow and the provider's create page.
 */
import { useTranslation } from "react-i18next";

import type { OtherLineDraft } from "./cart";

export function OtherLinesEditor({
  others,
  onChange,
  onAdd,
  onRemove,
  helper,
  testIdPrefix,
}: {
  others: OtherLineDraft[];
  onChange: (key: string, patch: Partial<Pick<OtherLineDraft, "text" | "note">>) => void;
  onAdd: () => void;
  onRemove: (key: string) => void;
  /** The one-line meaning under the label; defaults to the customer's. */
  helper?: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="field" style={{ marginTop: 14 }} data-testid={`${testIdPrefix}-others`}>
      <div className="field-label">{t("meerwerk_flow.other_label")}</div>
      <p className="muted small" style={{ marginTop: 0 }}>
        {helper ?? t("meerwerk_flow.other_helper")}
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {others.map((row, index) => (
          <li key={row.key} className="wp-undated-row" data-testid={`${testIdPrefix}-other-row`}>
            <div className="wp-undated-row-main" style={{ flex: 1 }}>
              <input
                className="field-input"
                value={row.text}
                onChange={(event) => onChange(row.key, { text: event.target.value })}
                placeholder={t("meerwerk_flow.other_placeholder")}
                aria-label={t("meerwerk_flow.other_label")}
                data-testid={index === 0 ? `${testIdPrefix}-other` : `${testIdPrefix}-other-${index + 1}`}
              />
              <input
                className="field-input"
                value={row.note}
                onChange={(event) => onChange(row.key, { note: event.target.value })}
                placeholder={t("meerwerk_flow.other_note_placeholder")}
                aria-label={t("meerwerk_flow.other_note_label")}
                style={{ marginTop: 6 }}
                data-testid={`${testIdPrefix}-other-note-${index + 1}`}
              />
            </div>
            <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="phase-badge phase-badge-action">
                {t("meerwerk_flow.price_follows")}
              </span>
              {others.length > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onRemove(row.key)}
                  aria-label={t("meerwerk_flow.other_remove")}
                  data-testid={`${testIdPrefix}-other-remove-${index + 1}`}
                >
                  ×
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        style={{ marginTop: 8 }}
        onClick={onAdd}
        data-testid={`${testIdPrefix}-other-add`}
      >
        {t("meerwerk_flow.other_add")}
      </button>
    </div>
  );
}
