// Sprint 121 — generic document thumbnail (extracted from AttachmentThumb).
//
// Renders a real preview of an authenticated document: images show the actual
// image; PDFs show a first-page thumbnail rendered client-side via pdfjs-dist
// (dynamically imported via ../lib/pdfThumb, so it stays out of the main
// bundle). Any failure or unsupported type falls back to `fallback` — never a
// broken thumbnail.
//
// This is the shared core: AttachmentThumb (ticket attachments) and the staff-
// credential row thumbnail both use it, differing only in the authenticated
// download URL they point at. The pdfjs rasterizer itself lives once in
// ../lib/pdfThumb — this component owns only the fetch/status/fallback wiring.
//
// The blob is fetched once per `url` (an object URL for the image case is
// revoked on unmount); the fetch runs inside an async function with a
// cancelled guard, so there is no synchronous setState in the effect body.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";

type ThumbStatus = "loading" | "image" | "pdf" | "fallback";

function documentPreviewKind(
  mimeType: string,
): "pdf" | "image" | "unsupported" {
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

export function DocumentThumb({
  url,
  mimeType,
  fallback,
  imgClassName = "att-thumb-img",
  canvasClassName = "att-thumb-canvas",
  imgTestId,
  pdfTestId,
  alt = "",
}: {
  /** Authenticated GET path (relative to the api client's baseURL) that
   *  returns the document blob. */
  url: string;
  mimeType: string;
  fallback: ReactNode;
  imgClassName?: string;
  canvasClassName?: string;
  imgTestId?: string;
  pdfTestId?: string;
  alt?: string;
}) {
  const kind = documentPreviewKind(mimeType);
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
        const response = await api.get(url, { responseType: "blob" });
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
  }, [url, kind]);

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
        className={imgClassName}
        src={imageUrl}
        alt={alt}
        loading="lazy"
        data-testid={imgTestId}
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
        className={canvasClassName}
        style={{ display: status === "pdf" ? "block" : "none" }}
        data-testid={pdfTestId}
      />
      {status !== "pdf" && fallback}
    </>
  );
}
