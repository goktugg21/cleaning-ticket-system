/**
 * P-12 §D.24 rule 4 — "the page moves you to where the thing went and
 * highlights it". The move carries `?highlight=<id>` in the URL; the
 * landing page consumes the param (stripped immediately, the
 * useSavedBanner precedent — a copied link must not re-highlight) and
 * tints the row for HIGHLIGHT_MS.
 *
 * Pure half of `useHighlightParam`, vitest-pinned.
 */

export const HIGHLIGHT_PARAM = "highlight";
export const HIGHLIGHT_MS = 10_000;
/** The CSS class the tinted row carries (components/guide/guide.css). */
export const HIGHLIGHT_CLASS = "guide-highlight";

/**
 * Read-and-remove the highlight id from a URLSearchParams IN PLACE.
 * Returns the id (null when absent or empty) and whether the params
 * changed — the caller only rewrites the URL when they did.
 */
export function takeHighlight(params: URLSearchParams): {
  id: string | null;
  changed: boolean;
} {
  if (!params.has(HIGHLIGHT_PARAM)) return { id: null, changed: false };
  const raw = params.get(HIGHLIGHT_PARAM) ?? "";
  params.delete(HIGHLIGHT_PARAM);
  return { id: raw === "" ? null : raw, changed: true };
}

/** Append ?highlight=<id> to a router path. */
export function withHighlight(path: string, id: string | number): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}${HIGHLIGHT_PARAM}=${encodeURIComponent(String(id))}`;
}
