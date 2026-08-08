/**
 * Sprint 154 §F/§G — the "assign M things to N things" dialog.
 *
 * Used from both directions and from both sides of the customer<->building
 * relation, plus the three other relations on the building detail page.
 * One component, because the interaction is identical every time: pick
 * targets, read a summary line that says exactly what is about to happen,
 * confirm.
 *
 * Deliberately a NON-NATIVE overlay, conditionally mounted. CLAUDE.md's
 * "render it unconditionally and drive it through the ref" rule is about
 * the native `<dialog>` element — a `<dialog>` behind `{cond && ...}` is
 * invisible and its trigger looks dead (Sprint 128), and unmounting an
 * open one can freeze the page (Sprint 118). A plain overlay div has
 * neither hazard, and Sprint 153 established this same split
 * (ConfirmDialog stays native + ref-driven; editing modals are overlays).
 *
 * The summary line is the point. "2 customers will be assigned to 3
 * buildings" is the difference between a confident click and a guess —
 * the operator is about to create six links from two lists they picked
 * on two different screens.
 */
import { useTranslation } from "react-i18next";

import { EntityPicker } from "./EntityPicker";
import type { EntityPickerOption } from "./EntityPicker";

export function BulkAssignDialog({
  title,
  summary,
  options,
  selectedIds,
  onChange,
  onCancel,
  onConfirm,
  confirmLabel,
  busy,
  error,
  emptyText,
  contextTitle,
  contextItems,
  testIdPrefix,
}: {
  title: string;
  /** The one-line "N x M" statement. Never omit it. */
  summary: string;
  options: EntityPickerOption[];
  selectedIds: number[];
  onChange: (next: number[]) => void;
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  busy?: boolean;
  error?: string;
  emptyText: string;
  /** Heading for the "what you already selected" list, e.g. the buildings. */
  contextTitle?: string;
  /** The already-selected other side, shown so the operator can check it
   *  without going back. Bounded by the caller. */
  contextItems?: string[];
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");

  return (
    <div
      data-testid={`${testIdPrefix}-modal`}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        className="card"
        style={{
          maxWidth: 620,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>{title}</h3>
        <p
          className="muted small"
          style={{ marginTop: 0, marginBottom: 16 }}
          data-testid={`${testIdPrefix}-summary`}
        >
          {summary}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid={`${testIdPrefix}-error`}
          >
            {error}
          </div>
        )}

        <EntityPicker
          options={options}
          selectedIds={selectedIds}
          onChange={onChange}
          disabled={busy}
          emptyText={emptyText}
          testIdPrefix={testIdPrefix}
        />

        {contextItems && contextItems.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div className="detail-field-label" style={{ marginBottom: 4 }}>
              {contextTitle}
            </div>
            <ul
              className="muted small"
              style={{ margin: 0, paddingLeft: 18 }}
              data-testid={`${testIdPrefix}-context`}
            >
              {contextItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 20,
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testIdPrefix}-cancel`}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onConfirm}
            disabled={busy || selectedIds.length === 0}
            data-testid={`${testIdPrefix}-confirm`}
          >
            {busy ? `${confirmLabel}…` : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
