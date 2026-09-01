/**
 * FE-4/FE-5, reshaped in P-9 C1 — the "iets anders" BOX. A box, not a
 * line: one text field and an Add button on the same row. A line
 * exists only once Add was pressed; it then shows under the box (and
 * in "This is what you are creating") with a remove x, and the box
 * clears and keeps focus. Nothing typed but not added is ever sent —
 * the page asks at submit (`UnaddedOtherLineNotice`). Shared by the
 * customer's guided flow and the provider's create page.
 */
import { useRef, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import type { OtherLineDraft } from "./cart";

export function OtherLinesEditor({
  others,
  draft,
  onDraftChange,
  onAdd,
  onRemove,
  helper,
  testIdPrefix,
}: {
  /** The lines already added. */
  others: OtherLineDraft[];
  /** The box's text — lifted, so the page can ask about it at submit. */
  draft: string;
  onDraftChange: (text: string) => void;
  /** Adds the box's text as a line and clears the box. */
  onAdd: () => void;
  onRemove: (key: string) => void;
  /** The one-line meaning under the label; defaults to the customer's. */
  helper?: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const canAdd = draft.trim() !== "";
  const add = () => {
    if (!canAdd) return;
    onAdd();
    // The box keeps focus: the next line is typed without a click.
    inputRef.current?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    // Enter adds the line; it must never submit the surrounding form.
    if (event.key === "Enter") {
      event.preventDefault();
      add();
    }
  };
  return (
    <div className="field" style={{ marginTop: 14 }} data-testid={`${testIdPrefix}-others`}>
      <div className="field-label">{t("meerwerk_flow.other_label")}</div>
      <p className="muted small" style={{ marginTop: 0 }}>
        {helper ?? t("meerwerk_flow.other_helper")}
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          ref={inputRef}
          className="field-input"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t("meerwerk_flow.other_placeholder")}
          aria-label={t("meerwerk_flow.other_label")}
          data-testid={`${testIdPrefix}-other`}
        />
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          style={{ flexShrink: 0 }}
          onClick={add}
          disabled={!canAdd}
          title={canAdd ? undefined : t("meerwerk_flow.other_add_why")}
          data-testid={`${testIdPrefix}-other-add`}
        >
          {t("meerwerk_flow.other_add")}
        </button>
      </div>
      {/* Rule 14 — a disabled control says why, under it. */}
      {!canAdd && (
        <span
          className="field-hint"
          style={{ marginTop: 4 }}
          data-testid={`${testIdPrefix}-other-add-why`}
        >
          {t("meerwerk_flow.other_add_why")}
        </span>
      )}
      {others.length > 0 && (
        <ul
          style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}
          data-testid={`${testIdPrefix}-other-added`}
        >
          {others.map((row, index) => (
            <li key={row.key} className="wp-undated-row" data-testid={`${testIdPrefix}-other-row`}>
              <div className="wp-undated-row-main" style={{ flex: 1 }}>
                <span>{row.text}</span>
              </div>
              <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className="phase-badge phase-badge-action">
                  {t("meerwerk_flow.price_follows")}
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onRemove(row.key)}
                  aria-label={t("meerwerk_flow.other_remove")}
                  title={t("meerwerk_flow.other_remove")}
                  data-testid={`${testIdPrefix}-other-remove-${index + 1}`}
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** P-9 C1 — the ask at submit when the box still holds text: one amber
 *  line, "You typed 'X' but did not add it", with Add it / Ignore.
 *  Either choice only settles the box; the submit is pressed again by
 *  the reader, never fired from here. */
export function UnaddedOtherLineNotice({
  text,
  onAddIt,
  onIgnore,
  testIdPrefix,
}: {
  text: string;
  onAddIt: () => void;
  onIgnore: () => void;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      className="alert-warning"
      role="status"
      style={{ marginTop: 16, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}
      data-testid={`${testIdPrefix}-other-unadded`}
    >
      <span style={{ flex: "1 1 240px" }}>
        {t("meerwerk_flow.other_unadded", { text })}
      </span>
      <span style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onAddIt}
          data-testid={`${testIdPrefix}-other-unadded-add`}
        >
          {t("meerwerk_flow.other_unadded_add")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onIgnore}
          data-testid={`${testIdPrefix}-other-unadded-ignore`}
        >
          {t("meerwerk_flow.other_unadded_ignore")}
        </button>
      </span>
    </div>
  );
}
