import { useCallback, useRef, useState } from "react";

/**
 * Sprint 169 §1 — grow a dialog so an open picker list sits INSIDE it.
 *
 * ## Why this exists rather than more CSS
 *
 * This has been asked four sprints running and each answer solved a
 * neighbouring problem. Sprint 166 gave the modal a height floor, which
 * made an EMPTY dialog a vast white box. Sprint 167 removed the floor,
 * which was right. Sprint 168 stopped the list being CLIPPED by
 * portalling it to `document.body` — also right, and still not the
 * thing asked for: a portalled list is not clipped, but it hangs out of
 * the bottom of a short modal and over the page behind it.
 *
 * What was actually asked: **when a picker's list is open, the modal is
 * tall enough to contain it.**
 *
 * A portalled list is `position: fixed`, so it contributes nothing to
 * the modal's layout — no amount of CSS on the modal can make it grow
 * for something that is not in its box. The height has to be RESERVED,
 * and reserving it needs one number the CSS does not have: how far the
 * list's bottom falls past the modal's.
 *
 * ## Why one measurement is enough
 *
 * The reserve is ADDITIVE and applied below everything else, so the
 * modal's new bottom is exactly `oldBottom + reserve`. Setting
 * `reserve = listBottom + margin - oldBottom` therefore lands the
 * modal's edge just past the list's in one step — no measure/grow/
 * re-measure loop, and no oscillation.
 *
 * The 85vh cap still binds: past it the modal stops growing and its
 * grid scrolls, which is the Sprint 167 behaviour and is left alone.
 * A list that cannot fit even then flips above its control, which the
 * picker already handles.
 */
export function usePickerReserve(margin = 16) {
  const modalRef = useRef<HTMLDivElement>(null);
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
      const modal = modalRef.current;
      if (!modal) return;
      // `getBoundingClientRect().bottom` already includes whatever
      // reserve is currently applied, so subtract it back out to get
      // the un-reserved bottom this measurement is relative to.
      setReserve((current) => {
        const unreservedBottom = modal.getBoundingClientRect().bottom - current;
        return Math.max(0, Math.round(listBottom + margin - unreservedBottom));
      });
    },
    [margin],
  );

  return { modalRef, reserve, onPickerOpenChange };
}
