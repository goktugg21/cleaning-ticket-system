/**
 * Sprint 28 Batch 15.4 — customer Extra-Work rejection dialog.
 *
 * Modal that captures the mandatory `customer_reject_reason` the
 * backend now requires when a CUSTOMER_USER transitions a request to
 * `CUSTOMER_REJECTED`. Two-press confirmation: the user opens the
 * dialog from the detail-page reject button, types a non-empty
 * reason, then clicks "Confirm rejection". An empty/whitespace-only
 * reason keeps the confirm button disabled — the backend would reject
 * it anyway with a 400, this is defence in depth.
 *
 * The component is intentionally headless w.r.t. the surrounding
 * page state — callers control `open` and supply `onConfirm` /
 * `onCancel`. The reason text is cleared from local state on close
 * so re-opening starts fresh.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

export interface RejectReasonDialogProps {
  open: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
  title?: string;
  description?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

export function RejectReasonDialog({
  open,
  onCancel,
  onConfirm,
  title,
  description,
  placeholder,
  confirmLabel,
  cancelLabel,
}: RejectReasonDialogProps) {
  const { t } = useTranslation("extra_work");
  const [reason, setReason] = useState("");

  if (!open) return null;
  const trimmed = reason.trim();
  const disabled = trimmed.length === 0;

  return (
    <div
      className="reject-modal-backdrop"
      data-testid="reject-reason-dialog"
      role="dialog"
      aria-modal="true"
    >
      <div className="reject-modal">
        <h3 className="reject-modal-title">
          {title ?? t("detail.reject_dialog_title")}
        </h3>
        <p className="reject-modal-desc">
          {description ?? t("detail.reject_dialog_description")}
        </p>
        <textarea
          data-testid="reject-reason-textarea"
          className="field-textarea reject-modal-textarea"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={placeholder ?? t("detail.reject_dialog_placeholder")}
          rows={4}
          autoFocus
        />
        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="reject-reason-cancel"
            onClick={() => {
              setReason("");
              onCancel();
            }}
          >
            {cancelLabel ?? t("detail.reject_dialog_cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm reject-modal-confirm"
            data-testid="reject-reason-confirm"
            disabled={disabled}
            onClick={() => {
              const r = reason.trim();
              setReason("");
              onConfirm(r);
            }}
          >
            {confirmLabel ?? t("detail.reject_dialog_confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

