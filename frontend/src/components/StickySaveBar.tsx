/**
 * Sprint 28 Batch 15.1 — sticky save bar.
 *
 * For long forms (Customer Permissions, Settings, future bulk
 * editors) the Save button can scroll out of the viewport, forcing
 * the user back to the top to commit changes. The bar pins to the
 * bottom of the page canvas while `dirty=true` and unmounts when
 * not — important so it doesn't trap focus or steal `onSave` taps
 * when the form is pristine.
 *
 * Intentionally style-only. Pages still own the form state machine,
 * the dirty-tracking, the validation, and the api call. This is a
 * UI container.
 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface StickySaveBarProps {
  dirty: boolean;
  saving?: boolean;
  onSave: () => void;
  onCancel?: () => void;
  saveLabel?: string;
  cancelLabel?: string;
  message?: ReactNode;
  testId?: string;
  /**
   * Optional testid attached to the inner Save button. Lets a page
   * preserve a locked testid (e.g. customer-policy-save) when the
   * actual save control moves into the sticky bar.
   */
  saveTestId?: string;
  /** Optional testid attached to the inner Cancel button. */
  cancelTestId?: string;
  /** Disable the save button independent of `saving` (e.g. validation errors). */
  saveDisabled?: boolean;
}

export function StickySaveBar({
  dirty,
  saving = false,
  onSave,
  onCancel,
  saveLabel,
  cancelLabel,
  message,
  testId,
  saveTestId,
  cancelTestId,
  saveDisabled = false,
}: StickySaveBarProps) {
  const { t } = useTranslation("common");

  if (!dirty) {
    return null;
  }

  const resolvedSaveLabel = saveLabel ?? t("save");
  const resolvedCancelLabel = cancelLabel ?? t("cancel");
  const resolvedMessage = message ?? t("unsaved_changes");

  return (
    <div
      className="sticky-save-bar"
      role="region"
      aria-label={typeof resolvedMessage === "string" ? resolvedMessage : undefined}
      data-testid={testId ?? "sticky-save-bar"}
    >
      <div className="sticky-save-bar-message">{resolvedMessage}</div>
      <div className="sticky-save-bar-actions">
        {onCancel && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={saving}
            data-testid={cancelTestId}
          >
            {resolvedCancelLabel}
          </button>
        )}
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onSave}
          disabled={saving || saveDisabled}
          data-testid={saveTestId}
        >
          {resolvedSaveLabel}
        </button>
      </div>
    </div>
  );
}


