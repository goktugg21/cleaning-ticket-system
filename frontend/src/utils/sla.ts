// SLA display helpers shared across the ticket list and detail views.
//
// The backend computes sla_display_state and sla_remaining_business_seconds
// authoritatively, but components that don't go through the API (or want a
// local re-derivation for safety) can call getSLADisplayState directly.

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

export const SLA_DISPLAY_STATE_LABEL: Record<SLADisplayState, string> = {
  ON_TRACK: "On track",
  AT_RISK: "At risk",
  BREACHED: "Breached",
  PAUSED: "Paused",
  COMPLETED: "Completed",
  HISTORICAL: "Historical",
};

const BUSINESS_HOURS_PER_DAY = 8;
const SECONDS_PER_HOUR = 60 * 60;
const SECONDS_PER_BUSINESS_DAY = BUSINESS_HOURS_PER_DAY * SECONDS_PER_HOUR;

export function formatSLATime(businessSeconds: number | null): string {
  if (businessSeconds === null) return "";
  if (businessSeconds === 0) return "Due now";
  const isOverdue = businessSeconds < 0;
  const abs = Math.abs(businessSeconds);
  const suffix = isOverdue ? "overdue" : "left";
  if (abs < 60 * 60) {
    const m = Math.max(1, Math.ceil(abs / 60));
    return `${m}m ${suffix}`;
  }
  const totalMinutes = Math.floor(abs / 60);
  if (abs < SECONDS_PER_BUSINESS_DAY) {
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return m === 0 ? `${h}h ${suffix}` : `${h}h ${m}m ${suffix}`;
  }
  const totalHours = Math.floor(totalMinutes / 60);
  const days = Math.floor(totalHours / BUSINESS_HOURS_PER_DAY);
  const hoursRemainder = totalHours % BUSINESS_HOURS_PER_DAY;
  return hoursRemainder === 0
    ? `${days}d ${suffix}`
    : `${days}d ${hoursRemainder}h ${suffix}`;
}
