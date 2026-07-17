// RF-12 (Göktuğ 2026-06-24) — attachment card thumbnail with no click.
//
// Renders a real preview inside the attachment tile: images show the actual
// image; PDFs show a first-page thumbnail rendered client-side via pdfjs-dist
// (dynamically imported, so it stays out of the main bundle). Any failure or
// unsupported type falls back to `fallback` (the extension-badge card) — never
// a broken card. The tile's click-to-view + the Download action are unchanged
// (this only replaces the badge glyph with a preview).
//
// The authenticated blob is fetched once per attachment id (cached for the
// component's lifetime); the object URL is revoked on unmount. The fetch runs
// inside an async function with a cancelled guard, so there is no synchronous
// setState in the effect body.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { TicketAttachment } from "../api/types";

type ThumbStatus = "loading" | "image" | "pdf" | "fallback";

function previewKind(mimeType: string): "pdf" | "image" | "unsupported" {
  if (mimeType === "application/pdf") return "pdf";
  if (
    mimeType === "image/jpeg" ||
    mimeType === "image/png" ||
    mimeType === "image/webp"
  ) {
    return "image";
  }
  return "unsupported";
}

export function AttachmentThumb({
  ticketId,
  attachment,
  fallback,
}: {
  ticketId: number | string;
  attachment: TicketAttachment;
  fallback: ReactNode;
}) {
  const kind = previewKind(attachment.mime_type);
  const [status, setStatus] = useState<ThumbStatus>(
    kind === "unsupported" ? "fallback" : "loading",
  );
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (kind === "unsupported") return;
    let cancelled = false;

    async function load() {
      try {
        const response = await api.get(
          `/tickets/${ticketId}/attachments/${attachment.id}/download/`,
          { responseType: "blob" },
        );
        if (cancelled) return;
        const blob = response.data as Blob;
        if (kind === "image") {
          const objectUrl = URL.createObjectURL(blob);
          urlRef.current = objectUrl;
          setImageUrl(objectUrl);
          setStatus("image");
          return;
        }
        // pdf — render the first page into the (already-mounted) canvas.
        const canvas = canvasRef.current;
        if (!canvas) throw new Error("canvas not mounted");
        const { renderPdfFirstPage } = await import("../lib/pdfThumb");
        if (cancelled) return;
        await renderPdfFirstPage(blob, canvas);
        if (!cancelled) setStatus("pdf");
      } catch {
        if (!cancelled) setStatus("fallback");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [ticketId, attachment.id, kind]);

  // Revoke the image object URL on unmount (ref avoids a stale closure).
  useEffect(() => {
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, []);

  if (status === "fallback" || kind === "unsupported") {
    return <>{fallback}</>;
  }

  if (kind === "image") {
    return imageUrl ? (
      <img
        className="att-thumb-img"
        src={imageUrl}
        alt=""
        loading="lazy"
        data-testid="attachment-thumb-image"
      />
    ) : (
      <>{fallback}</>
    );
  }

  // pdf — keep the canvas mounted while loading so the effect can draw into
  // it; show the fallback badge until the first page is rendered.
  return (
    <>
      <canvas
        ref={canvasRef}
        className="att-thumb-canvas"
        style={{ display: status === "pdf" ? "block" : "none" }}
        data-testid="attachment-thumb-pdf"
      />
      {status !== "pdf" && fallback}
    </>
  );
}
