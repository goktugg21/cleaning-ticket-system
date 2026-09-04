/**
 * P-12 C1/C2 (§D.24 rule 3) — the contract's road, in the order things
 * happen. THE ordered constant: the list tabs, the counts and the
 * detail page's progress road all iterate it (never a second local
 * array — the Sprint 126 rule). "Cancelled" is off the road: a link at
 * the foot of the last tab (§D.22 rule 9), and a cancelled contract's
 * detail shows no road.
 */
import type { Contract } from "../api/contracts.types";

export const CONTRACT_ROAD = ["draft", "active", "ending", "ended"] as const;

/** The server's ENDING_SOON_DAYS (contracts/views_contracts.py) — the
 *  authority; /contracts/stats/ serves it as `ending_soon_days`, and a
 *  page without the stats read falls back to this constant. */
export const DEFAULT_ENDING_HORIZON_DAYS = 60;
export type ContractRoadKey = (typeof CONTRACT_ROAD)[number];

/**
 * Where ONE contract stands on the road, from the same facts the
 * server's `status_filter_q` reads: the derived status, and the end
 * date against the horizon (`ending_soon_days`, served by
 * `/contracts/stats/`). Null for CANCELLED — off the road.
 */
export function contractRoadKeyOf(
  contract: Pick<Contract, "status" | "end_date">,
  horizonDays: number,
  today: Date = new Date(),
): ContractRoadKey | null {
  if (contract.status === "CANCELLED") return null;
  if (contract.status === "DRAFT") return "draft";
  if (contract.status === "EXPIRED") return "ended";
  if (contract.end_date) {
    const end = new Date(`${contract.end_date}T00:00:00`);
    const horizon = new Date(today);
    horizon.setHours(0, 0, 0, 0);
    horizon.setDate(horizon.getDate() + horizonDays);
    if (end.getTime() <= horizon.getTime()) return "ending";
  }
  return "active";
}
