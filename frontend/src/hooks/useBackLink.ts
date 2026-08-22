/**
 * W14 §3 — a back link that actually goes back.
 *
 * `useBackLink("/extra-work")` returns the two props a back `<Link>`
 * needs. It renders as an ordinary link to the named page — so it is
 * right-clickable, middle-clickable, and correct with no history at all
 * — and when the entry immediately behind this one IS that page, a
 * plain left click steps the history back instead of pushing a fourth
 * entry onto it.
 *
 * The difference matters twice over:
 *
 *   * the reader returns to the list they left, with its scroll, its
 *     filters and its page still on it, rather than to a freshly
 *     mounted one;
 *   * pressing this and then pressing the browser's Back does not
 *     bounce them straight back into the detail they just left, which
 *     is what a pushing back link does and is half of the owner's "I
 *     can never reach the previous page".
 *
 * The label never lies: `navHistory.samePage` requires the previous
 * entry to be the page the label names, so "Back to Extra Work" that
 * would land on the dashboard follows its href and goes to Extra Work.
 *
 * Modified clicks are left entirely alone — ctrl/cmd/shift/alt and
 * middle-click are the reader asking the BROWSER for something, and a
 * `preventDefault` there would break open-in-new-tab.
 */
import type { MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { previousPath, samePage } from "../lib/navHistory";

export interface BackLinkProps {
  to: string;
  onClick: (event: MouseEvent<HTMLAnchorElement>) => void;
}

export function useBackLink(to: string): BackLinkProps {
  const navigate = useNavigate();
  return {
    to,
    onClick: (event: MouseEvent<HTMLAnchorElement>) => {
      if (event.defaultPrevented) return;
      if (event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      // Asked at CLICK time, not at render time: the answer depends on
      // where the history head is now, and the head moves under a page
      // that stays mounted.
      if (!samePage(previousPath(), to)) return;
      event.preventDefault();
      navigate(-1);
    },
  };
}
