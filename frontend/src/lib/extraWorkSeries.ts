/**
 * W5-B — folding a day-by-day series into one list entry.
 *
 * A pure helper, in `src/lib/` with the other pure helpers, because
 * ESLint's `react-refresh/only-export-components` is right: a file that
 * exports both components and functions breaks fast refresh, and the
 * fix it names is a separate module. Being separately importable also
 * makes this testable on its own, which a closure inside the page would
 * not be.
 */
import type {
  ExtraWorkGroupSummary,
  ExtraWorkRequestList,
} from "../api/types";

/** Fold day-by-day series into one entry each.
 *
 *  Order is preserved and a series takes the position of its FIRST
 *  member, so turning series on does not reshuffle a list somebody was
 *  reading. An ungrouped work passes through untouched — that is the
 *  overwhelming majority of rows and the case that must not regress.
 *
 *  Note what this does NOT do: it never asks the server for a header
 *  record and it never treats a member as special. The reference system
 *  elects `group_sequence == 1` the header and branches its status
 *  filter on that election, which is the direct cause of its list
 *  totals disagreeing with its own statistics endpoint. Here the header
 *  is a rendering artefact that exists only in the browser; the counts
 *  on it come from the server and describe the whole series. */
type ListEntry =
  | { kind: "row"; row: ExtraWorkRequestList }
  | {
      kind: "series";
      group: ExtraWorkGroupSummary;
      rows: ExtraWorkRequestList[];
    };

export function foldSeries(rows: ExtraWorkRequestList[]): ListEntry[] {
  const out: ListEntry[] = [];
  const seenAt = new Map<number, number>();
  for (const row of rows) {
    if (!row.group) {
      out.push({ kind: "row", row });
      continue;
    }
    const at = seenAt.get(row.group.id);
    if (at === undefined) {
      seenAt.set(row.group.id, out.length);
      out.push({ kind: "series", group: row.group, rows: [row] });
    } else {
      const entry = out[at];
      if (entry.kind === "series") entry.rows.push(row);
    }
  }
  return out;
}
