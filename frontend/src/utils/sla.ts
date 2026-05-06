// SLA display helpers shared across the ticket list and detail views.
//
// The backend computes sla_display_state and sla_remaining_business_seconds
// authoritatively, but components that don't go through the API (or want a
// local re-derivation for safety) can call getSLADisplayState directly.
//
// Translation note: i18n B2 moved the user-visible label map and the
// formatter from this module into hooks (useSLALabel / useFormatSLATime).
// What remains here is type-only data plus the math constants — anything
// that doesn't need the active language.

export type SLADisplayState =
  | "ON_TRACK"
  | "AT_RISK"
  | "BREACHED"
  | "PAUSED"
  | "COMPLETED"
  | "HISTORICAL";

export type SLAStatus =
  | "ON_TRACK"
  | "AT_RISK"
  | "BREACHED"
  | "COMPLETED"
  | "HISTORICAL";

export interface SLAFields {
  sla_status: SLAStatus | null;
  sla_paused_at: string | null;
}

export function getSLADisplayState(ticket: SLAFields): SLADisplayState {
  if (ticket.sla_status === "HISTORICAL") return "HISTORICAL";
  if (ticket.sla_status === "COMPLETED") return "COMPLETED";
  if (ticket.sla_paused_at !== null) return "PAUSED";
  if (ticket.sla_status === "BREACHED") return "BREACHED";
  if (ticket.sla_status === "AT_RISK") return "AT_RISK";
  return "ON_TRACK";
}

export const BUSINESS_HOURS_PER_DAY = 8;
export const SECONDS_PER_HOUR = 60 * 60;
export const SECONDS_PER_BUSINESS_DAY =
  BUSINESS_HOURS_PER_DAY * SECONDS_PER_HOUR;
