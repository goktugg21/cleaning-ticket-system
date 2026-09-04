/**
 * P-13 H (§D.24 rule 8) — the "How this page works" fold's memory.
 *
 * P-14 A3 (owner: "you can make them closed automatically — your
 * call"): CLOSED by default, everywhere, always — the summary line
 * beside the title keeps the fold one click away. A person who opens
 * it is remembered open — per page, per browser (localStorage: the
 * fold teaches a person, not a session). Pure over an injected
 * storage so vitest pins it in the node harness; every access is
 * try/caught — a browser that refuses storage gets the
 * closed-by-default behaviour and nothing breaks.
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

/** Has this person left this page's fold open? Closed is the default:
 *  only a stored "open" opens it. */
export function howOpen(
  storage: StorageLike | null,
  pageKey: string,
): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(KEY_PREFIX + pageKey) === "open";
  } catch {
    return false;
  }
}

/** Remember the person's choice. Closing it again forgets "open",
 *  so a page they closed deliberately greets them closed next time. */
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
