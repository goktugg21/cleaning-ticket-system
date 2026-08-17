import { useCallback, useRef, useState } from "react";

/**
 * Sprint 169 §1 / Sprint 170 §8 — grow a dialog so an open picker list
 * sits INSIDE it.
 *
 * ## Why this exists rather than more CSS
 *
 * A portalled list is `position: fixed`, so it contributes nothing to
 * the modal's layout — no amount of CSS on the modal can make it grow
 * for a box that is not in it. The height has to be RESERVED, and
 * reserving it needs one number the CSS does not have: how far the
 * list's bottom falls past where the modal's content ends.
 *
 * ## Why it is measured against a SPACER, not against the modal
 *
 * This is the whole of Sprint 170 §8, and both failed shapes are
 * recorded because each looked correct and each produced a modal that
 * grew the first time and then appeared broken:
 *
 *   1. Sprint 169 derived the un-reserved bottom by SUBTRACTING the
 *      current reserve from a live `getBoundingClientRect()`. Every
 *      measurement then depended on the previous one.
 *   2. Remembering the un-reserved bottom in a ref failed for a subtler
 *      reason: at the moment it was recorded (on close) the reserve was
 *      still applied, because React had not re-rendered yet. It stored
 *      a RESERVED bottom and called it un-reserved.
 *
 * Both are the same mistake — reading a number whose value depends on
 * the thing being computed. This one cannot: the reserve is rendered as
 * a SPACER at the end of the modal, and the spacer's TOP edge is where
 * the content ends *regardless of the spacer's own height*. So
 *
 *     reserve = listBottom + margin - spacerTop
 *
 * is exact in one pass, needs no memory of earlier values, and gives
 * the same answer on the tenth open as on the first. Nothing can drift
 * it, which is what "it bugged back" meant.
 *
 * The 85vh cap still binds: past it the modal stops growing and its
 * grid scrolls, which is the Sprint 167 behaviour and is left alone.
 */
export function usePickerReserve(margin = 16) {
  /** Put on the modal element. */
  const modalRef = useRef<HTMLDivElement>(null);
  /** Put on the spacer, which must be the LAST child of the modal. */
  const spacerRef = useRef<HTMLDivElement>(null);
  const [reserve, setReserve] = useState(0);

  /**
   * Pass as a picker's `onOpenChange`. `null` (the list closed) drops
   * the reserve back to zero, so an empty dialog with every picker shut
   * stays exactly as short as it was — the part of the Sprint 167 fix
   * that must not regress.
   */
  const onPickerOpenChange = useCallback(
    (listBottom: number | null) => {
      if (listBottom === null) {
        setReserve(0);
        return;
      }
      const spacer = spacerRef.current;
      if (!spacer) return;
      // The spacer's top is fixed by the content ABOVE it, so this is
      // independent of whatever reserve is applied right now.
      const contentEnd = spacer.getBoundingClientRect().top;
      setReserve(Math.max(0, Math.round(listBottom + margin - contentEnd)));
    },
    [margin],
  );

  return { modalRef, spacerRef, reserve, onPickerOpenChange };
}
