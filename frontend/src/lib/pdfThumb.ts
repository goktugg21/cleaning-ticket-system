// RF-12 (Göktuğ 2026-06-24) — lazy PDF first-page rasterizer.
//
// This whole module is dynamically imported by <AttachmentThumb>, so
// pdfjs-dist (large, Apache-2.0) lands in its OWN lazy chunk and never
// bloats the main bundle. The worker is resolved by Vite via the `?url`
// import so it ships as a separate hashed asset (typed as string through
// `vite/client`).
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Render page 1 of `blob` into `canvas`, scaled to the canvas's rendered
 * CSS width (the card width). Throws on any failure so the caller can fall
 * back to the plain type-badge card — never a broken card.
 */
export async function renderPdfFirstPage(
  blob: Blob,
  canvas: HTMLCanvasElement,
): Promise<void> {
  const data = await blob.arrayBuffer();
  const loadingTask = pdfjs.getDocument({ data });
  const doc = await loadingTask.promise;
  try {
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const targetWidth = canvas.clientWidth || 160;
    const viewport = page.getViewport({ scale: targetWidth / base.width });
    canvas.width = Math.max(1, Math.round(viewport.width));
    canvas.height = Math.max(1, Math.round(viewport.height));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d context unavailable");
    await page.render({ canvasContext: ctx, canvas, viewport }).promise;
  } finally {
    void loadingTask.destroy();
  }
}
