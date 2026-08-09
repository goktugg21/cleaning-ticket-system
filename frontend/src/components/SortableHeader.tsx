/**
 * A sortable column header, defined ONCE.
 *
 * `aria-sort` lives on the `<th>` — the columnheader is what ARIA sorts —
 * and the clickable thing is a real `<button>` inside it, so the header
 * works from the keyboard. An `onClick` on the `<th>` would not.
 *
 * Sprint 157 §3 — extracted. The customers list and the buildings list
 * each carried their own copy, and the buildings one even had a comment
 * saying it was duplicated "rather than shared". Adding a third copy for
 * the companies list is the point at which that stops being a
 * defensible shortcut: three hand-maintained copies of a keyboard and
 * ARIA contract will not stay in step, and the next person to fix a
 * focus bug will fix one of them. CLAUDE.md's rule about a second
 * independently-maintained copy applies to behaviour as much as to
 * render order.
 */

/** `none` while another column owns the sort. */
export type SortState = "none" | "ascending" | "descending";

export function SortableHeader({
  label,
  sort,
  testId,
  onSort,
  sortByLabel,
}: {
  label: string;
  sort: SortState;
  testId: string;
  onSort: () => void;
  /** The accessible name — "Sort by Name", not just "Name", so a screen
   *  reader announces what the button DOES rather than repeating the
   *  column title it already read. */
  sortByLabel: string;
}) {
  return (
    <th aria-sort={sort === "none" ? undefined : sort}>
      <button
        type="button"
        className="th-sort"
        data-sort={sort}
        aria-label={sortByLabel}
        data-testid={testId}
        onClick={onSort}
      >
        {label}
        <span className="th-sort-caret" aria-hidden="true">
          {sort === "descending" ? "▼" : "▲"}
        </span>
      </button>
    </th>
  );
}
