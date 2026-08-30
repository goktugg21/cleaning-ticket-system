/**
 * P-4 (Part D) — NAVIGATION TELLS THE TRUTH.
 *
 * A ticket of kind MEERWERK is the same meerwerk in its execution phase
 * (base SoT §1.4: the unified tickets QUEUE keeps it, with the pill).
 * Its detail page lives under /tickets/<id>, so the sidebar lit
 * "Tickets" while the reader was inside extra work. The route cannot
 * say what kind the record is; the page that loaded it can. This is
 * the smallest possible bridge: the ticket page publishes the kind it
 * loaded, the shell subscribes. Nothing else reads it.
 */
import { useSyncExternalStore } from "react";

import type { TicketKind } from "../api/types";

let current: { id: number; kind: TicketKind } | null = null;
const listeners = new Set<() => void>();

export function publishCurrentTicketKind(next: { id: number; kind: TicketKind } | null): void {
  current = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot() {
  return current;
}

/** The kind of the ticket the detail page currently shows, or null. */
export function useCurrentTicketKind(): { id: number; kind: TicketKind } | null {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
