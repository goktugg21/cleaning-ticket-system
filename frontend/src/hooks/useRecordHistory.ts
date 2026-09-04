/**
 * W14 §3 — record every location the app lands on.
 *
 * Mounted once, inside the router, above the routes. `useLocation`
 * fires for pushes, replaces and pops alike, which is what the recorder
 * needs: a `replace` changes what an index HOLDS, and a stale record
 * would let a back link promise a page the reader would not reach.
 *
 * An effect, not a render-time call, because `history.state.idx` is only
 * correct once React Router has committed the navigation.
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { recordLocation } from "../lib/navHistory";

export function useRecordHistory(): null {
  const location = useLocation();
  useEffect(() => {
    recordLocation(location.pathname + location.search);
  }, [location.pathname, location.search]);
  return null;
}

/** Component form, so `App` can mount it beside `<Routes>` without
 *  becoming a hook host itself. */
export function HistoryRecorder(): null {
  return useRecordHistory();
}
