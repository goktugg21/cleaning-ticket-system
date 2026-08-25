/**
 * W6-H — the day columns of the plan grid.
 *
 * A pure helper in `src/lib/` with the others, because
 * `react-refresh/only-export-components` is right that a file exporting
 * both components and functions breaks fast refresh — and because a
 * date range is the kind of thing that deserves to be testable on its
 * own rather than as a closure inside a dialog.
 */

/** Every day from `start` to `end` inclusive, or [] when the window is
 *  not set.
 *
 *  CAPPED, because the window is operator-typed and a mistyped year
 *  would otherwise try to render 365 columns in a modal. Past the cap
 *  the grid draws what it can and the undated column still takes the
 *  rest; the SERVER has no such limit and is unaffected, so a plan that
 *  already spans more days keeps every one of its rows. */
export const MAX_GRID_DAYS = 31;

export function dayRange(start: string, end: string): string[] {
  if (start === "") return [];
  const first = new Date(`${start}T00:00:00`);
  if (Number.isNaN(first.getTime())) return [];
  const last = end === "" ? first : new Date(`${end}T00:00:00`);
  // An end before the start is a half-typed window, not an empty one:
  // the start day is still a real column and dropping it would make the
  // grid flicker to nothing mid-edit.
  if (Number.isNaN(last.getTime()) || last < first) return [start];
  const out: string[] = [];
  const cursor = new Date(first);
  // LOCAL wall date, never `toISOString()` — the cursor is a LOCAL
  // midnight, and toISOString renders the UTC instant, which east of
  // Greenwich is still YESTERDAY. Window 27..29 rendered columns
  // 26/27/28 (the owner's EW 83 screenshot), and because these strings
  // are also the grid's cell keys and the payload's dates, hours typed
  // under "27-08" were SAVED to the 26th. Same trap this codebase has
  // documented twice for datetime-local seeding; this was the date-only
  // copy of it.
  const pad = (n: number) => String(n).padStart(2, "0");
  while (cursor <= last && out.length < MAX_GRID_DAYS) {
    out.push(
      `${cursor.getFullYear()}-${pad(cursor.getMonth() + 1)}-${pad(
        cursor.getDate(),
      )}`,
    );
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}
