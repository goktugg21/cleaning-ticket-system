/**
 * P-13 H (§D.24 rule 8) — the "How this page works" fold's memory.
 *
 * Open by default the FIRST time a user sees a page; once they close
 * it, closed stays closed — per page, per browser (localStorage: the
 * fold teaches a person, not a session). Pure over an injected
 * storage so vitest pins it in the node harness; every access is
 * try/caught — a browser that refuses storage gets the open-by-default
 * behaviour and nothing breaks.
 */

const KEY_PREFIX = "guide.how.";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function safeLocalStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Has this person closed this page's fold before? */
export function howClosed(
  storage: StorageLike | null,
  pageKey: string,
): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(KEY_PREFIX + pageKey) === "closed";
  } catch {
    return false;
  }
}

/** Remember the person's choice. Opening it again forgets "closed",
 *  so a page they re-opened deliberately greets them open next time. */
export function rememberHow(
  storage: StorageLike | null,
  pageKey: string,
  open: boolean,
): void {
  if (!storage) return;
  try {
    storage.setItem(KEY_PREFIX + pageKey, open ? "open" : "closed");
  } catch {
    // Memory is a courtesy; the fold still works without it.
  }
}
