// Sprint 119 — shared in-app PDF preview, mirroring the ticket-attachment
// preview in TicketDetailPage (RF-5): a click handler (never an effect)
// fetches the file as an authenticated blob and opens the dialog
// immediately in a loading state, filling in once the blob resolves.
// Generalized over {url, filename} rather than any one entity's type so it
// is reusable across document surfaces (today: staff credential
// documents, which are backend-enforced PDF-only).
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../api/client";

export interface PdfPreviewTarget {
  url: string;
  filename: string;
}

export interface PdfPreviewDialogHandle {
  open: (target: PdfPreviewTarget) => void;
  close: () => void;
}

export const PdfPreviewDialog = forwardRef<PdfPreviewDialogHandle, object>(
  function PdfPreviewDialog(_props, ref) {
    const { t } = useTranslation("staff_credentials");
    const dialogRef = useRef<HTMLDialogElement>(null);
    const blobUrlRef = useRef<string | null>(null);
    const [target, setTarget] = useState<PdfPreviewTarget | null>(null);
    const [blobUrl, setBlobUrl] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    function revokeBlobUrl() {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    }

    useImperativeHandle(
      ref,
      () => ({
        open: (next) => {
          revokeBlobUrl();
          setTarget(next);
          setBlobUrl(null);
          setError("");
          setLoading(true);
          dialogRef.current?.showModal();
          void (async () => {
            try {
              const response = await api.get(next.url, {
                responseType: "blob",
              });
              const objectUrl = URL.createObjectURL(response.data);
              blobUrlRef.current = objectUrl;
              setBlobUrl(objectUrl);
            } catch (err) {
              setError(getApiError(err));
            } finally {
              setLoading(false);
            }
          })();
        },
        close: () => dialogRef.current?.close(),
      }),
      [],
    );

    function requestClose() {
      dialogRef.current?.close();
    }

    // The real cleanup runs here so Esc-to-close is handled the same way as
    // an explicit close button (mirrors TicketDetailPage's attachment preview).
    function handleClosed() {
      revokeBlobUrl();
      setTarget(null);
      setBlobUrl(null);
      setError("");
      setLoading(false);
    }

    function handleDownload() {
      if (!blobUrl || !target) return;
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = target.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    }

    // Same top-layer safety as ConfirmDialog and the ticket-attachment
    // preview (Sprint 118): showModal() puts the dialog in the browser's top
    // layer and makes the rest of the document inert. If this unmounts while
    // still open, close it here — while the node is still attached — so it
    // is ejected from the top layer on every engine.
    useEffect(() => {
      const node = dialogRef.current;
      return () => {
        revokeBlobUrl();
        if (node?.open) node.close();
      };
    }, []);

    return (
      <dialog
        ref={dialogRef}
        className="att-preview-dialog"
        onClose={handleClosed}
        aria-label={target?.filename ?? t("preview.title")}
      >
        <div className="att-preview-head">
          <div className="att-preview-head-info">
            <span className="att-thumb-ext">PDF</span>
            <span className="att-preview-name">
              {target?.filename ?? t("preview.title")}
            </span>
          </div>
          <div className="att-preview-head-actions">
            {blobUrl && target && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleDownload}
                data-testid="pdf-preview-download"
              >
                <Download size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>{t("field.download")}</span>
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={requestClose}
              data-testid="pdf-preview-close"
            >
              {t("modal.close")}
            </button>
          </div>
        </div>
        <div className="att-preview-body">
          {loading ? (
            <div className="att-preview-status">{t("preview.loading")}</div>
          ) : error ? (
            <div className="att-preview-status att-preview-status-error">
              {error}
            </div>
          ) : blobUrl ? (
            <iframe
              className="att-preview-frame"
              src={blobUrl}
              title={target?.filename ?? t("preview.title")}
              data-testid="pdf-preview-frame"
            />
          ) : null}
        </div>
      </dialog>
    );
  },
);
