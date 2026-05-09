import type { ReactNode } from "react";
import { forwardRef, useImperativeHandle, useRef } from "react";
import { useTranslation } from "react-i18next";

export interface ConfirmDialogHandle {
  open: () => void;
  close: () => void;
}

export interface ConfirmDialogProps {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void | Promise<void>;
  onCancel?: () => void;
  busy?: boolean;
  busyLabel?: string;
  destructive?: boolean;
  // Sprint 12: optional gate so callers can require, e.g., a typed
  // confirmation phrase before the confirm button activates. Defaults
  // to false — pre-existing callers keep their current behaviour.
  confirmDisabled?: boolean;
}

export const ConfirmDialog = forwardRef<ConfirmDialogHandle, ConfirmDialogProps>(
  function ConfirmDialog(
    {
      title,
      body,
      confirmLabel,
      cancelLabel,
      onConfirm,
      onCancel,
      busy = false,
      busyLabel,
      destructive = false,
      confirmDisabled = false,
    },
    ref,
  ) {
    const { t } = useTranslation("common");
    const resolvedCancelLabel = cancelLabel ?? t("cancel");
    const dialogRef = useRef<HTMLDialogElement>(null);

    useImperativeHandle(
      ref,
      () => ({
        open: () => dialogRef.current?.showModal(),
        close: () => dialogRef.current?.close(),
      }),
      [],
    );

    const handleCancel = () => {
      dialogRef.current?.close();
      onCancel?.();
    };

    // No btn-danger / btn-ghost-danger class exists in the CSS today; the
    // destructive flag is accepted for forward compatibility but currently
    // resolves to the same btn-primary styling the existing dialogs used.
    const confirmClass =
      destructive && false ? "btn btn-ghost-danger btn-sm" : "btn btn-primary btn-sm";

    const renderedBusyLabel = busyLabel ?? `${confirmLabel}…`;

    return (
      <dialog
        ref={dialogRef}
        style={{
          padding: 24,
          borderRadius: 8,
          border: "1px solid var(--border)",
          maxWidth: 460,
        }}
      >
        <h3 style={{ marginBottom: 8 }}>{title}</h3>
        <div style={{ color: "var(--text-muted)", marginBottom: 16 }}>{body}</div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleCancel}
            disabled={busy}
          >
            {resolvedCancelLabel}
          </button>
          <button
            type="button"
            className={confirmClass}
            onClick={() => {
              void onConfirm();
            }}
            disabled={busy || confirmDisabled}
          >
            {busy ? renderedBusyLabel : confirmLabel}
          </button>
        </div>
      </dialog>
    );
  },
);
