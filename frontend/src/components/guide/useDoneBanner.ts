import { useCallback, useEffect, useState } from "react";

import {
  DONE_EVENT,
  announceDone,
  clearDone,
  safeSessionStorage,
  takeDone,
  type DoneAnnouncement,
} from "./doneBannerStore";

/**
 * The page half of `DoneBanner`: announce after an action, re-show
 * across one reload, dismiss for good.
 *
 * The reload survivor is consumed ONCE per page-load through a
 * module-level cache — a plain `takeDone` in the initializer would
 * burn a life per mount (StrictMode double-invokes initializers, and
 * SPA remounts are not reloads), and the banner would die early.
 * Within one page-load the announcement simply persists until
 * dismissed, which is also the §D.24 behaviour: the banner is not a
 * toast.
 */
const consumedThisPageLoad = new Map<string, DoneAnnouncement | null>();

function takeOncePerPageLoad(pageKey: string): DoneAnnouncement | null {
  if (!consumedThisPageLoad.has(pageKey)) {
    consumedThisPageLoad.set(pageKey, takeDone(safeSessionStorage(), pageKey));
  }
  return consumedThisPageLoad.get(pageKey) ?? null;
}

export function useDoneBanner(pageKey: string): {
  done: DoneAnnouncement | null;
  announce: (a: DoneAnnouncement) => void;
  dismiss: () => void;
} {
  const [done, setDone] = useState<DoneAnnouncement | null>(() =>
    takeOncePerPageLoad(pageKey),
  );

  // A raw-store announce from ANOTHER component (a ceremony inside the
  // page) reaches this mounted hook through the event — setState in an
  // event callback, the sanctioned shape.
  useEffect(() => {
    const onDone = (event: Event) => {
      const detail = (event as CustomEvent).detail as
        | { pageKey?: string; announcement?: DoneAnnouncement }
        | undefined;
      if (!detail || detail.pageKey !== pageKey || !detail.announcement) return;
      consumedThisPageLoad.set(pageKey, detail.announcement);
      setDone(detail.announcement);
    };
    window.addEventListener(DONE_EVENT, onDone);
    return () => window.removeEventListener(DONE_EVENT, onDone);
  }, [pageKey]);

  const announce = useCallback(
    (a: DoneAnnouncement) => {
      consumedThisPageLoad.set(pageKey, a);
      announceDone(safeSessionStorage(), pageKey, a);
      setDone(a);
    },
    [pageKey],
  );

  const dismiss = useCallback(() => {
    consumedThisPageLoad.set(pageKey, null);
    clearDone(safeSessionStorage(), pageKey);
    setDone(null);
  }, [pageKey]);

  return { done, announce, dismiss };
}
