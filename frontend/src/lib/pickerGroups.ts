// Sprint 139 §3 — grouping helper for the shared category-grouped
// multi-select picker.
//
// Lives in `lib/` rather than beside `CategoryGroupedPicker.tsx`
// because `react-refresh/only-export-components` (correctly) rejects a
// component module that also exports plain functions — exporting both
// breaks Fast Refresh for the component.

export interface PickerGroup<T> {
  key: string;
  name: string;
  /** Every row in the group, regardless of the active text filter. */
  items: T[];
  /** The subset the active text filter currently shows. */
  visible: T[];
}

/**
 * Build the grouped structure from a flat row list. `categoryOf` maps a
 * row to its category id; rows whose category is missing from
 * `categories` land in a trailing fallback group rather than being
 * silently dropped — a row that vanishes from a picker is exactly the
 * class of defect these sprints keep removing.
 *
 * Groups with no rows at all are omitted: unlike the pricing category
 * INDEX (Sprint 137 item 4), where an empty category must stay visible
 * so the operator can price into it, an empty group inside a PICKER is
 * a dead end with nothing to select.
 */
export function buildPickerGroups<T>({
  rows,
  categories,
  categoryOf,
  matchesFilter,
  fallbackName,
}: {
  rows: T[];
  categories: { id: number; name: string }[];
  categoryOf: (row: T) => number | null;
  matchesFilter: (row: T) => boolean;
  fallbackName: string;
}): PickerGroup<T>[] {
  const groups: PickerGroup<T>[] = categories.map((category) => {
    const items = rows.filter((row) => categoryOf(row) === category.id);
    return {
      key: String(category.id),
      name: category.name,
      items,
      visible: items.filter(matchesFilter),
    };
  });
  const known = new Set(categories.map((c) => c.id));
  const orphans = rows.filter((row) => {
    const id = categoryOf(row);
    return id === null || !known.has(id);
  });
  groups.push({
    key: "__uncategorised__",
    name: fallbackName,
    items: orphans,
    visible: orphans.filter(matchesFilter),
  });
  return groups.filter((group) => group.items.length > 0);
}
