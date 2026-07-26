import type { ReactNode } from "react";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
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

    // showModal() promotes the <dialog> to the browser's top layer and makes
    // the rest of the document INERT (pointer input swallowed while the page
    // still scrolls). If this component unmounts while the dialog is still
    // open — a consumer navigating inside its onConfirm handler (e.g. the
    // invoice-delete flow), a parent list re-rendering the row away, a redirect
    // after an action — the node is torn out of the DOM without close() ever
    // running. Removing an open modal is only guaranteed to release the top
    // layer / inert state on engines that run the <dialog> "removing steps"
    // reliably; where they don't, the document is left scrollable but
    // click-dead until a manual refresh. Closing it here while it is still
    // attached ejects it from the top layer on every engine. Copy the node in
    // the effect body (not the cleanup) so the ref read satisfies the hooks
    // lint rule; the dialog node identity is stable for the component's life.
    useEffect(() => {
      const node = dialogRef.current;
      return () => {
        if (node?.open) node.close();
      };
    }, []);

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
