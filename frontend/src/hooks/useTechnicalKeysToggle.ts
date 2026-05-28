import { useEffect, useState } from "react";

/**
 * Sprint 29 Batch 29.1 — toggle that controls whether the
 * `PolicyToggleGrid` exposes the underlying technical permission
 * keys ("Affects: customer.ticket.approve_own, ...") to the
 * operator.
 *
 * Default OFF for every user — non-technical customer admins
 * shouldn't be confronted with `customer.*` key names just to
 * scan the policy grid. Super admins and integration partners can
 * flip it on; the choice persists in `localStorage` and syncs
 * across tabs via the `storage` event.
 *
 * Scope is strictly the `PolicyToggleGrid` affects-line. The
 * `OverrideDrawer` is excluded by design — that drawer's purpose
 * is per-key override, and the key IS the primary identifier.
 */
const STORAGE_KEY = "cleanops.permissions.show_technical_keys";

export function useTechnicalKeysToggle(): [boolean, (next: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  const setAndPersist = (next: boolean) => {
    setEnabled(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      /* localStorage disabled (private mode) — in-memory only */
    }
  };

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setEnabled(e.newValue === "true");
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  return [enabled, setAndPersist];
}
