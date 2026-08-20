import { useTranslation } from "react-i18next";
import type { SLADisplayState } from "./sla";
import { formatBusinessDuration } from "./sla";

/**
 * W7 — the deadline vocabulary, in words a cleaner reads without help.
 *
 * "SLA" is a contract term. Nobody on a mop or on a customer's front
 * desk knows it, and every user-visible string that carried it has been
 * replaced with what is actually true: there is a deadline, and it has
 * either passed or it has not. The CODE names are untouched — the
 * backend field is still `sla_status`, the display union is still
 * `SLADisplayState`, the query parameter is still `?sla=` — because
 * renaming those buys the reader nothing and costs every other surface
 * a migration.
 */

// Translates the six deadline states to one plain word or phrase each.
// Returned as a function so call sites stay terse:
// `const slaLabel = useSLALabel(); slaLabel("BREACHED");`
export function useSLALabel() {
  const { t } = useTranslation("common");
  return (state: SLADisplayState): string => {
    switch (state) {
      case "ON_TRACK":
        return t("sla.on_track");
      case "AT_RISK":
        return t("sla.at_risk");
      case "BREACHED":
        return t("sla.breached");
      case "PAUSED":
        return t("sla.paused");
      case "COMPLETED":
        return t("sla.completed");
      case "HISTORICAL":
        return t("sla.historical");
      default:
        return state;
    }
  };
}

/**
 * ONE statement about the deadline, for a person to act on.
 *
 * The owner's complaint was six chips for one idea — a state pill, a
 * countdown pill, and then the same two facts repeated as prose beside
 * them — with nothing saying what the clock was measured against. So
 * every state resolves to a single sentence here, and it is the only
 * place any screen is allowed to phrase it:
 *
 *   ON_TRACK   "On time - 6h left"
 *   AT_RISK    "Almost late - 1h left"
 *   BREACHED   "Late by 1h 37m"          <- said once, with the amount
 *   PAUSED     "Waiting on customer"     <- the clock is not running
 *   COMPLETED  "Finished"
 *   HISTORICAL "No deadline"             <- never an empty cell
 *
 * A missing countdown falls back to the bare state word rather than to
 * a blank: `sla_remaining_business_seconds` is nullable on the list
 * serializer, and a row that renders nothing is the defect this
 * function exists to remove.
 */
export function useDeadlineText() {
  const { t } = useTranslation("common");
  const label = useSLALabel();
  return (
    state: SLADisplayState,
    remainingBusinessSeconds: number | null,
  ): string => {
    // The three states with no running clock say only what they are.
    if (
      state === "HISTORICAL" ||
      state === "PAUSED" ||
      state === "COMPLETED"
    ) {
      return label(state);
    }
    if (remainingBusinessSeconds === null) return label(state);
    if (remainingBusinessSeconds === 0) return t("sla.due_now");
    const time = formatBusinessDuration(remainingBusinessSeconds);
    // A negative remainder is late, whatever the stored state says. The
    // engine reconciles on a Celery tick, so a row can be past its
    // deadline a few minutes before its status catches up; reading the
    // number rather than the label means the screen is never the last
    // to know.
    if (remainingBusinessSeconds < 0) return t("sla.late_by", { time });
    if (state === "BREACHED") return t("sla.breached");
    return state === "AT_RISK"
      ? t("sla.due_soon", { time })
      : t("sla.due_in", { time });
  };
}
