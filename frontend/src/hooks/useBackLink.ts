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
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { Role } from "../api/types";
import { EXTRA_WORK_TABS } from "../lib/extraWorkTabs";
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

/**
 * FE-4 (Addendum D §D.12 item 1) — BACK GOES WHERE YOU CAME FROM.
 *
 * The owner: "back" on a detail page must return to the surface the
 * reader actually came from — My Schedule with its week and filters,
 * Mijn meldingen, Tickets with its query — not to a fixed list.
 *
 * The in-app origin is `navHistory.previousPath()`, read ONCE when the
 * detail mounts (a detail that navigates to a sibling detail stays
 * mounted, and its origin does not change under it). When that path is
 * one of the surfaces below, the link points at it — the FULL path,
 * query included, so the week and the filters ride along — and a plain
 * click steps the history back (`useBackLink`), which is what restores
 * scroll and state rather than remounting the list. When there is no
 * in-app origin (a deep link, a fresh tab, a notification), the role's
 * own home list is the honest default: staff and building managers
 * live on My Schedule, customers on Mijn meldingen, provider admins on
 * Tickets.
 */
const ORIGINS: { test: RegExp; labelKey: string }[] = [
  { test: /^\/agenda(?:[/?#]|$)/, labelKey: "back_to.schedule" },
  { test: /^\/my\/meldingen(?:[/?#]|$)/, labelKey: "back_to.my_meldingen" },
  { test: /^\/tickets(?:[?#]|$)/, labelKey: "back_to.tickets" },
  // P-11 A6 — since P-9 the Extra work list ALWAYS lives on a tab path
  // (the bare /extra-work redirects to one), so the test is built from
  // the tab table itself: a new tab joins the back link the moment it
  // exists, and /extra-work/<id> (a detail, not a list) still does not
  // match.
  {
    test: new RegExp(
      `^/extra-work(?:/(?:${EXTRA_WORK_TABS.join("|")}))?(?:[?#]|$)`,
    ),
    labelKey: "back_to.extra_work",
  },
  { test: /^\/start(?:[/?#]|$)/, labelKey: "back_to.start" },
  { test: /^\/inbox(?:[/?#]|$)/, labelKey: "back_to.inbox" },
  { test: /^\/admin\/customers\/\d+/, labelKey: "back_to.customer" },
  { test: /^\/(?:[?#]|$)/, labelKey: "back_to.dashboard" },
];

function roleHome(role: Role | null | undefined): { to: string; labelKey: string } {
  if (role === "STAFF" || role === "BUILDING_MANAGER") {
    return { to: "/agenda", labelKey: "back_to.schedule" };
  }
  if (role === "CUSTOMER_USER") {
    return { to: "/my/meldingen", labelKey: "back_to.my_meldingen" };
  }
  return { to: "/tickets", labelKey: "back_to.tickets" };
}

export interface OriginBackLink extends BackLinkProps {
  label: string;
}

export function useOriginBackLink(
  role: Role | null | undefined,
  options: {
    /** An explicit origin the caller was handed (router state), which
     *  outranks the recorded history. */
    override?: string | null;
    /** The default when there is no in-app origin, instead of the role's
     *  home (a meerwerk detail defaults to the meerwerk list). */
    fallbackTo?: string;
    fallbackLabelKey?: string;
    /** An origin the caller refuses even when recorded (P-11 A6: a
     *  ticket born from extra work is never "from Tickets" — extra
     *  work is not on that page). A refused origin falls through to
     *  the fallback. */
    notFrom?: RegExp;
  } = {},
): OriginBackLink {
  const { t } = useTranslation("common");
  // Read once, at mount: the origin is where the reader CAME from.
  const [origin] = useState<string | null>(() => options.override ?? previousPath());
  const accepted = origin && !options.notFrom?.test(origin) ? origin : null;
  const known = accepted ? ORIGINS.find((o) => o.test.test(accepted)) : undefined;
  const home = roleHome(role);
  const target = known && accepted
    ? { to: accepted, labelKey: known.labelKey }
    : options.fallbackTo
      ? { to: options.fallbackTo, labelKey: options.fallbackLabelKey ?? home.labelKey }
      : home;
  const link = useBackLink(target.to);
  return { ...link, label: t(target.labelKey) };
}
