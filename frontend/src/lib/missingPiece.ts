/**
 * P-5 S2.4 — THE MISSING-PIECE POINTER.
 *
 * When a step blocks on something unfinished elsewhere ("the hours are
 * missing", "this person has no day"), the sentence that says so gets
 * a button, and the button lands the reader ON the missing part: the
 * right tab or modal opens, the part scrolls into view and is lit for a
 * moment, and it says what it needs. System-wide pattern for every
 * "X is missing" pointer.
 *
 * Two halves, deliberately decoupled so a pointer can target a part
 * that is not mounted yet (another tab, a modal about to open):
 *
 *   pointAtMissingPiece(id)   remembers the id and tells every mounted
 *                             anchor;
 *   useMissingPieceAnchor(id) returns a ref; the element scrolls and
 *                             lights up the moment it is the pending
 *                             target — on mount, or when pointed at
 *                             while mounted — and the target is
 *                             consumed so it fires once.
 */
import { useEffect, useRef } from "react";

const EVENT = "missing-piece";
const HIGHLIGHT_CLASS = "piece-highlight";
const HIGHLIGHT_MS = 4000;

let pending: string | null = null;

export function pointAtMissingPiece(id: string): void {
  pending = id;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: id }));
}

function land(element: HTMLElement): void {
  element.scrollIntoView({ behavior: "smooth", block: "center" });
  element.classList.add(HIGHLIGHT_CLASS);
  window.setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), HIGHLIGHT_MS);
}

export function useMissingPieceAnchor<T extends HTMLElement = HTMLDivElement>(
  id: string,
) {
  const ref = useRef<T | null>(null);
  // No dependency list on purpose: the element often arrives a render
  // or two AFTER the component mounts (a card that first renders its
  // loading state — the ticket's Money card), and no event fires
  // then. Re-checking every render is cheap and idempotent: it acts
  // once, only when this id is the pending target AND the element
  // exists.
  useEffect(() => {
    const consume = () => {
      if (pending !== id || !ref.current) return;
      pending = null;
      // Next frame: a tab that just switched may still be laying out.
      window.requestAnimationFrame(() => ref.current && land(ref.current));
    };
    consume();
    window.addEventListener(EVENT, consume);
    return () => window.removeEventListener(EVENT, consume);
  });
  return ref;
}
