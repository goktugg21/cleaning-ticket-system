import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { HIGHLIGHT_MS, HIGHLIGHT_PARAM, takeHighlight } from "./highlight";

/**
 * P-12 §D.24 rule 4 — read `?highlight=<id>` and hold it for
 * HIGHLIGHT_MS. Rows compare their own id against the return value and
 * add HIGHLIGHT_CLASS while it matches.
 *
 * The id is DERIVED from the URL during render (no setState in the
 * effect body — the house rule); the timer's callback is what expires
 * it and strips the param. The param therefore lives in the URL for
 * the highlight's ten seconds and is gone after — a reload inside the
 * window re-shows a tint the person may not have seen yet, which is
 * the useful reading of it.
 */
export function useHighlightParam(): string | null {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get(HIGHLIGHT_PARAM);
  const [expiredId, setExpiredId] = useState<string | null>(null);

  useEffect(() => {
    if (raw == null || raw === "") return;
    const timer = window.setTimeout(() => {
      setExpiredId(raw);
      const next = new URLSearchParams(window.location.search);
      const took = takeHighlight(next);
      if (took.changed) setSearchParams(next, { replace: true });
    }, HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [raw, setSearchParams]);

  return raw != null && raw !== "" && raw !== expiredId ? raw : null;
}
