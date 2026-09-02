/**
 * P-12 §D.24 rule 4 — after every action the page says what happened,
 * what did NOT happen, and the one next step; the banner survives one
 * reload. This is the storage half of `DoneBanner`, pure so vitest can
 * pin the survive-one-reload contract with a fake Storage.
 *
 * The payload is strings only, deliberately: it goes through
 * sessionStorage, and a serialized ReactNode is a bug factory. Pages
 * compose the sentences (through t()) before announcing.
 *
 * Every storage access is try/caught and a broken storage means "no
 * banner", never a crash — the same stance as navHistory and the
 * notification greeting (a courtesy must never be what breaks a page).
 */

export interface DoneAnnouncement {
  /** What happened — "Draft made for B Amsterdam — €384.78." */
  title: string;
  /** What did NOT happen + the one next step. */
  body?: string;
  /** The next step's button. */
  actionLabel?: string;
  /** Router path the button navigates to. */
  actionTo?: string;
}

interface StoredDone {
  a: DoneAnnouncement;
  reloadsLeft: number;
}

const storageKey = (pageKey: string) => `guide.done.${pageKey}`;

/** sessionStorage, or null where the accessor itself throws. */
export function safeSessionStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Record an announcement so the page can re-show it across ONE reload. */
export function announceDone(
  storage: Storage | null,
  pageKey: string,
  a: DoneAnnouncement,
): void {
  if (!storage) return;
  try {
    const stored: StoredDone = { a, reloadsLeft: 1 };
    storage.setItem(storageKey(pageKey), JSON.stringify(stored));
  } catch {
    // Storage full or blocked — the in-memory banner still shows.
  }
}

/**
 * On page mount: the announcement to re-show, if one is still alive.
 * Each call consumes a life, so the banner survives exactly one
 * reload and then stays gone.
 */
export function takeDone(
  storage: Storage | null,
  pageKey: string,
): DoneAnnouncement | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(storageKey(pageKey));
    if (!raw) return null;
    const stored = JSON.parse(raw) as StoredDone;
    if (
      !stored ||
      typeof stored !== "object" ||
      typeof stored.a?.title !== "string" ||
      typeof stored.reloadsLeft !== "number"
    ) {
      storage.removeItem(storageKey(pageKey));
      return null;
    }
    if (stored.reloadsLeft <= 0) {
      storage.removeItem(storageKey(pageKey));
      return null;
    }
    storage.setItem(
      storageKey(pageKey),
      JSON.stringify({ ...stored, reloadsLeft: stored.reloadsLeft - 1 }),
    );
    return stored.a;
  } catch {
    return null;
  }
}

/** The person dismissed it — gone for good. */
export function clearDone(storage: Storage | null, pageKey: string): void {
  if (!storage) return;
  try {
    storage.removeItem(storageKey(pageKey));
  } catch {
    // Nothing to do — worst case the banner returns once after reload.
  }
}
