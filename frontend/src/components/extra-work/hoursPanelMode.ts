/**
 * P-9 C5 — WHEN the "hours worked" panel is on screen, per phase.
 *
 * Hours worked are entered only once the work has started: before that
 * the money surface shows the plan's hours and one sentence; after the
 * invoice the saved hours are read-only. ONE table for both mounts of
 * the panel — the unspawned request's own page and the spawned
 * ticket's Extra work card (where `/extra-work/<id>` redirects once
 * work exists) — so the two cannot disagree. Exhaustive over the phase
 * enum: a new phase fails to compile here.
 */
import type { ExtraWorkDisplayPhase } from "../../api/types";

export type HoursPanelMode = "none" | "before" | "edit" | "read_only";

export const HOURS_PANEL_MODE: Record<ExtraWorkDisplayPhase, HoursPanelMode> = {
  WAITING_PRICE: "none",
  WAITING_YOUR_APPROVAL: "none",
  WAITING_CUSTOMER_APPROVAL: "none",
  WAITING_PLANNING: "before",
  SCHEDULED: "before",
  IN_EXECUTION: "edit",
  WAITING_COMPLETION_APPROVAL: "edit",
  DONE: "edit",
  INVOICED: "read_only",
  REJECTED: "none",
  CANCELLED: "none",
};
