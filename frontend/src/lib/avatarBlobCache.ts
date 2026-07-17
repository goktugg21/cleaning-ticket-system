/**
 * RF-1 — module-level object-URL cache for authed avatar / logo blobs.
 *
 * Photos and logos are served from permission-gated endpoints, so they
 * must be fetched with the auth interceptor (via `api`) as blobs and
 * turned into object URLs — a plain <img src> to the endpoint would be
 * unauthenticated.
 *
 * The cache is keyed by the FULL url, which already carries a
 * `?v=<marker>` version derived from the stored file (see the backend
 * media_urls builders). So:
 *   - the same avatar shown in N rows fetches ONCE (no refetch storm);
 *   - when the underlying image changes, the url's marker changes, which
 *     is a new key -> exactly one refetch, and the superseded object URL
 *     is revoked on eviction.
 *
 * A bounded LRU-ish cap revokes the oldest object URL when exceeded, so
 * a long session browsing many people never leaks blobs.
 */
import { api } from "../api/client";

const CACHE_MAX = 200;

// Insertion-ordered; value is the in-flight/resolved fetch so concurrent
// callers for the same url share one request.
const cache = new Map<string, Promise<string | null>>();

async function fetchObjectUrl(url: string): Promise<string | null> {
  try {
    const response = await api.get(url, { responseType: "blob" });
    return URL.createObjectURL(response.data as Blob);
  } catch {
    return null;
  }
}

export function getAvatarObjectUrl(url: string): Promise<string | null> {
  const existing = cache.get(url);
  if (existing) return existing;

  const pending = fetchObjectUrl(url);
  cache.set(url, pending);

  if (cache.size > CACHE_MAX) {
    const oldestKey = cache.keys().next().value as string | undefined;
    if (oldestKey !== undefined) {
      const evicted = cache.get(oldestKey);
      cache.delete(oldestKey);
      void evicted?.then((objectUrl) => {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      });
    }
  }
  return pending;
}
