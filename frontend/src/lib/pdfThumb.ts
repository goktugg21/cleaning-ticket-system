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

// Sprint 122 — thumbnails rendered soft: the canvas is `display: none` until
// the page has finished rendering (DocumentThumb only flips it visible once
// this resolves), so `canvas.clientWidth` was always 0 and every thumbnail
// fell back to a hardcoded 160px raster that the tile then stretched to its
// real (larger) CSS size. The canvas's parent tile (.att-thumb-tile /
// .credential-thumb) IS visible immediately, and the stylesheet sizes the
// canvas to 100% of it — so measure the parent instead.
//
// We also rasterize at devicePixelRatio so HiDPI screens get a crisp bitmap
// rather than the browser upscaling a 1x render. Both are capped: DPR at 2
// (real displays essentially top out there; at thumbnail size a 3x render
// buys nothing visible) and the backing store width at 960px — a 3-col
// attachment tile stays well under 480px CSS-wide on any normal viewport, so
// 960 covers a full 2x render with room to spare. This only bites on an
// unusually wide tile (e.g. an ultra-wide monitor with no per-tile max-width),
// where it trades a little sharpness for a bounded canvas allocation instead
// of an unbounded one — still strictly better than the old fixed-160 fallback.
const MAX_DEVICE_PIXEL_RATIO = 2;
const MAX_BACKING_WIDTH = 960;
const FALLBACK_CSS_WIDTH = 160;

/**
 * Render page 1 of `blob` into `canvas`, scaled to the canvas's real display
 * width and the screen's pixel density. Throws on any failure so the caller
 * can fall back to the plain type-badge card — never a broken card.
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
    const targetCssWidth =
      canvas.parentElement?.clientWidth || FALLBACK_CSS_WIDTH;
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO);
    const backingWidth = Math.min(targetCssWidth * dpr, MAX_BACKING_WIDTH);
    const viewport = page.getViewport({ scale: backingWidth / base.width });
    canvas.width = Math.max(1, Math.round(viewport.width));
    canvas.height = Math.max(1, Math.round(viewport.height));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d context unavailable");
    await page.render({ canvasContext: ctx, canvas, viewport }).promise;
  } finally {
    void loadingTask.destroy();
  }
}
