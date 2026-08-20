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

/**
 * A business-time duration as a bare number of units — "45m", "1h 37m",
 * "2d 3h" — with NO word attached to it.
 *
 * The word is the caller's job, and that is the whole point. The old
 * `useFormatSLATime` glued the suffix on here ("1h 37m overdue"), so a
 * screen that wanted to say "Late by 1h 37m" had to render the state
 * word and this string side by side and the reader got the same fact
 * twice: a "Breached" pill next to the words "Breached — 1h 37m
 * overdue". One sentence needs one string, so the duration comes out
 * naked and `useDeadlineText` builds the sentence around it.
 *
 * Unit letters are identical in both languages, exactly as they were
 * before — this is not a translated string and never was.
 */
export function formatBusinessDuration(businessSeconds: number): string {
  const abs = Math.abs(businessSeconds);
  if (abs < 60 * 60) {
    return `${Math.max(1, Math.ceil(abs / 60))}m`;
  }
  const totalMinutes = Math.floor(abs / 60);
  if (abs < SECONDS_PER_BUSINESS_DAY) {
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  }
  const totalHours = Math.floor(totalMinutes / 60);
  const days = Math.floor(totalHours / BUSINESS_HOURS_PER_DAY);
  const hoursRemainder = totalHours % BUSINESS_HOURS_PER_DAY;
  return hoursRemainder === 0 ? `${days}d` : `${days}d ${hoursRemainder}h`;
}
