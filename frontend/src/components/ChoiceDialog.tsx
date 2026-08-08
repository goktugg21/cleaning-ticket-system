/**
 * Sprint 155 §1b — "which of these did you mean?"
 *
 * The Extra Work list's create button used to go straight to the
 * direct-order form, which is only one of the three things an operator
 * might mean by "new extra work". The other two — a quote request and
 * recurring work — were reachable only from the sidebar, so choosing
 * between them meant knowing they existed and where they lived.
 *
 * Each option carries a one-line description, and that line is the point.
 * "Extra Work Request" and "Request a Quote" are not self-describing to
 * someone who has not used the system for a month; "you are ordering the
 * work now" versus "you are asking what it would cost" is.
 *
 * Deliberately a NON-NATIVE overlay, conditionally mounted, exactly like
 * `BulkAssignDialog`. CLAUDE.md's "render it unconditionally and drive it
 * through the ref" rule is about the native `<dialog>` element, which is
 * invisible behind `{cond && ...}` (Sprint 128) and can freeze the page if
 * unmounted while open (Sprint 118). A plain overlay div has neither
 * hazard. `ConfirmDialog` stays native and ref-driven where it is used;
 * this is a routing choice, not a confirmation.
 *
 * Keyboard: Escape closes, focus lands on the first option on open, and
 * the options are real buttons so Tab and Enter work without any custom
 * key handling.
 */
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

export interface DialogChoice {
  key: string;
  label: string;
  description: string;
  onSelect: () => void;
}

export function ChoiceDialog({
  title,
  subtitle,
  choices,
  onCancel,
  testIdPrefix,
}: {
  title: string;
  subtitle?: string;
  choices: DialogChoice[];
  onCancel: () => void;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  const firstRef = useRef<HTMLButtonElement>(null);

  // Focus the first option and wire Escape. One effect, no setState in
  // its body — it only touches the DOM and a listener.
  useEffect(() => {
    firstRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

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
          maxWidth: 520,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: subtitle ? 4 : 16 }}>
          {title}
        </h3>
        {subtitle && (
          <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
            {subtitle}
          </p>
        )}

        <div className="choice-dialog-list">
          {choices.map((choice, index) => (
            <button
              key={choice.key}
              ref={index === 0 ? firstRef : undefined}
              type="button"
              className="choice-dialog-option"
              onClick={choice.onSelect}
              data-testid={`${testIdPrefix}-option-${choice.key}`}
            >
              <span className="choice-dialog-option-label">{choice.label}</span>
              <span className="choice-dialog-option-desc">
                {choice.description}
              </span>
            </button>
          ))}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginTop: 16,
          }}
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            data-testid={`${testIdPrefix}-cancel`}
          >
            {t("cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
