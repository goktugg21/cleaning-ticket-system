/**
 * W14 §3 — WHERE THE APP HAS BEEN, so that "back" can go back.
 *
 * ## What the owner reported
 *
 *     "I go to Extra Work, open a detail, press browser back, and it
 *      throws me to the dashboard. I can never reach the previous page.
 *      It has been like this since the system was first built."
 *
 * ## What was actually happening — measured, on the live site
 *
 * Two separate defects, both of which end with the reader somewhere
 * they did not ask for:
 *
 * 1. **One click, two history entries.** The ticket rows are a
 *    `<tr onClick={() => navigate(...)}>` wrapped around `<Link>`s to
 *    the same place. Clicking the link navigates, the click then
 *    bubbles to the row, and the row navigates again. Instrumenting
 *    `history.pushState` on crmtest, one click on ticket 343 logged:
 *
 *        PUSH /tickets/343
 *        PUSH /tickets/343
 *
 *    and `history.state.idx` went 1 -> 3. One press of Back therefore
 *    landed on `/tickets/343` — the page it was pressed on. The list
 *    was two presses away, and only for the rows whose cell happened to
 *    be a link.
 *
 * 2. **"Back to tickets" went to the dashboard, and PUSHED.**
 *    `TicketDetailPage` rendered `<Link to="/">` under the label
 *    `back_to_tickets`, three times. So the in-page back control landed
 *    on `/` — which is the owner's "it throws me to the dashboard",
 *    exactly — and because a `<Link>` pushes, the browser's own Back
 *    then returned to the ticket. Forward and backward both broken, in
 *    opposite directions.
 *
 * ## Why a module rather than `navigate(-1)` everywhere
 *
 * `navigate(-1)` alone is wrong for a back LINK: on a deep link, a
 * fresh tab, or a reload there is no previous in-app entry, and -1
 * leaves the app entirely. And it is wrong for a LABELLED one — "Back
 * to Extra Work" that lands on the dashboard because that is where you
 * happened to come from is a control that lies.
 *
 * So this records the path at each history index and lets a back link
 * ask one precise question: *is the entry behind me the page my label
 * names?* If it is, go back — the reader returns to the list with its
 * scroll, its filters and its page intact, which a fresh push cannot
 * do. If it is not, follow the link and push, which is what the label
 * promised.
 *
 * ## Why `history.state.idx`
 *
 * React Router's own history writes `{usr, key, idx}` into
 * `history.state` and keeps `idx` correct across Back and Forward.
 * Measured on crmtest: `{"idx":0}` on a fresh load or a deep-linked
 * tab, `{"usr":null,"key":"...","idx":1}` after one in-app navigation.
 * Reading it means the index survives a reload, which a counter of our
 * own would not.
 *
 * `sessionStorage` for the same reason: per tab, cleared when the tab
 * is, and it survives the reload that a module-level array would not.
 * Every access is wrapped — a browser with site data blocked throws on
 * the accessor itself, and a back link must never be what breaks a
 * page.
 */

const KEY = "navHistory.v1";
/** Enough for any plausible drill-down; the stack is trimmed from the
 *  front so a long session cannot grow the entry without bound. */
const MAX = 60;

/** `paths[i]` is what history index `base + i` was showing. Keeping the
 *  base explicit is what lets the stack be trimmed from the front
 *  without the remaining entries silently meaning a different index. */
interface Stack {
  base: number;
  paths: (string | null)[];
}

const EMPTY: Stack = { base: 0, paths: [] };

function read(): Stack {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      typeof (parsed as Stack).base === "number" &&
      Array.isArray((parsed as Stack).paths)
    ) {
      return parsed as Stack;
    }
    return EMPTY;
  } catch {
    return EMPTY;
  }
}

function write(stack: Stack): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(stack));
  } catch {
    /* private mode, blocked site data: the back links fall back to
       their labelled destination, which is always correct. */
  }
}

/** React Router's index for the current entry, or null when the browser
 *  will not say (a fresh document, a non-router entry). */
export function historyIndex(): number | null {
  try {
    const state = window.history.state as { idx?: unknown } | null;
    const idx = state?.idx;
    return typeof idx === "number" && idx >= 0 ? idx : null;
  } catch {
    return null;
  }
}

/**
 * Remember that history index `idx` is showing `path`.
 *
 * Called on every location change, replaces included: a `replace` is
 * still a change of what that index holds, and a stale entry would let
 * a back link claim a destination the reader would not actually reach.
 */
export function recordLocation(path: string): void {
  const idx = historyIndex();
  if (idx === null) return;
  let { base, paths } = read();
  // A fresh tab, or a session whose recorded window no longer contains
  // this index: start again from here rather than write into a slot
  // that means something else.
  if (idx < base) {
    base = idx;
    paths = [];
  }
  // A jump forward past the end (a reload, a `window.location` hop)
  // leaves holes; null is an honest "we never saw this one" and reads
  // as "no, that is not the page you named".
  while (paths.length < idx - base) paths.push(null);
  paths[idx - base] = path;
  // Anything ahead of the current entry has been discarded by the push.
  paths.length = idx - base + 1;
  if (paths.length > MAX) {
    const drop = paths.length - MAX;
    base += drop;
    paths = paths.slice(drop);
  }
  write({ base, paths });
}

/** The path of the entry immediately behind this one, or null when
 *  there is none or we never saw it. */
export function previousPath(): string | null {
  const idx = historyIndex();
  if (idx === null || idx <= 0) return null;
  const { base, paths } = read();
  const at = idx - 1 - base;
  if (at < 0 || at >= paths.length) return null;
  return paths[at] ?? null;
}

/**
 * Is `candidate` the same PAGE as `target`?
 *
 * Pathname only. `/extra-work?tab=quotes` is still the Extra Work list,
 * and a back link labelled "Back to Extra Work" that refused to go back
 * because the list had a filter on it would be refusing in exactly the
 * case where going back matters most — that filter is the state the
 * reader wants restored.
 */
export function samePage(candidate: string | null, target: string): boolean {
  if (!candidate) return false;
  const strip = (value: string) => {
    const cut = value.search(/[?#]/);
    const path = cut === -1 ? value : value.slice(0, cut);
    return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
  };
  return strip(candidate) === strip(target);
}
