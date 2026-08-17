/**
 * Sprint 155 §4 — the system-wide rule, in one place.
 *
 * The owner stated it explicitly: **no screen edits anything directly.**
 * The operator presses Edit (or "Edit basics") first; only then do
 * checkboxes, per-row removes and bulk actions appear. The Permissions
 * page is the one deliberate exception and does not use this.
 *
 * `CustomerPricingPage` (Sprint 137 item 7, hardened in Sprint 142) got
 * this right first, and this hook is that implementation lifted out
 * rather than reworded. It is a hook and not a copied block because the
 * sweep covers eight screens: eight hand-maintained copies of a
 * correctness rule is the same defect shape as Sprint 126's second
 * render-order array — the copies agree on the day they are written and
 * not after.
 *
 * The two properties worth keeping are both DERIVED, and deriving them
 * is what makes them impossible to get wrong later:
 *
 *  1. **`editMode` is `requested && there is something to act on`.**
 *     Edit mode over an empty list shows a toolbar hanging over nothing.
 *     That state is reachable from both directions — opening the mode on
 *     an empty list, and emptying the list WHILE in the mode — and no
 *     amount of gating the Edit button closes the second one.
 *
 *  2. **The selection is filtered to what is still selectable.** Raw
 *     selection state is never pruned by anything, so a key outlives its
 *     row: select a row, have it removed (by this session or another),
 *     and a stale key is left pointing at something gone. Sprint 138 §3
 *     shipped exactly that bug on the pricing page — a bulk action fired
 *     against an archived row and reported a phantom success.
 *
 * Neither needs an effect, which matters: a resync effect would be a
 * synchronous setState in an effect body, which CLAUDE.md forbids and
 * which `react-hooks/set-state-in-effect` is already at its baseline for.
 */
import { useState } from "react";

export interface EditModeController<K> {
  /** What the UI renders. NEVER read the raw request instead of this. */
  editMode: boolean;
  /** The operator's raw intent — only for the "empty list" affordance,
   *  where there are no rows so `editMode` is false but an Add button
   *  still has to be reachable. */
  editModeRequested: boolean;
  /** The selection, filtered to keys that are still selectable. */
  selection: K[];
  isSelected: (key: K) => boolean;
  toggle: (key: K) => void;
  selectAll: () => void;
  clear: () => void;
  /** True when every selectable row is selected (and there is one). */
  allSelected: boolean;
  start: () => void;
  /** Leaves edit mode AND clears the selection — a selection that
   *  survived the exit would silently reappear on the next Edit. */
  exit: () => void;
  toggleMode: () => void;
}

export function useEditMode<K>(
  selectableKeys: K[],
  options?: {
    /** For screens that already own their selection state.
     *
     *  Three admin lists (Buildings, Customers, the customer's Buildings
     *  sub-page) keep a selection that spans PAGES — "select all" adds
     *  the current page's ids to what is already chosen, and the bulk
     *  action fires against the union. This hook's own selection is
     *  filtered to `selectableKeys`, which on a paginated list is one
     *  page, so adopting it wholesale would silently drop the
     *  off-screen half of a selection.
     *
     *  Those screens therefore keep their own array and take only the
     *  MODE from here, clearing their state through this callback so
     *  "leaving edit mode clears the selection" still holds everywhere.
     *  The alternative — a second local copy of the derived-mode rule on
     *  each of them — is the drift this hook exists to prevent. */
    onExit?: () => void;
  },
): EditModeController<K> {
  const [editModeRequested, setEditModeRequested] = useState(false);
  const [rawSelection, setRawSelection] = useState<K[]>([]);

  const editMode = editModeRequested && selectableKeys.length > 0;

  const available = new Set(selectableKeys);
  const selection = rawSelection.filter((key) => available.has(key));

  const exit = () => {
    setEditModeRequested(false);
    setRawSelection([]);
    options?.onExit?.();
  };

  return {
    editMode,
    editModeRequested,
    selection,
    isSelected: (key) => selection.includes(key),
    toggle: (key) =>
      setRawSelection((current) =>
        current.includes(key)
          ? current.filter((k) => k !== key)
          : [...current, key],
      ),
    selectAll: () => setRawSelection([...selectableKeys]),
    clear: () => setRawSelection([]),
    allSelected:
      selectableKeys.length > 0 && selection.length === selectableKeys.length,
    start: () => setEditModeRequested(true),
    exit,
    toggleMode: () => (editMode ? exit() : setEditModeRequested(true)),
  };
}
