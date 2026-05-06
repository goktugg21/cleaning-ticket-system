import { useTranslation } from "react-i18next";
import type { SLADisplayState } from "./sla";

// Translates the six SLA display states. Returned as a function so call sites
// stay terse: `const slaLabel = useSLALabel(); slaLabel("BREACHED");`. The
// translation namespace is `common` because SLA labels appear on multiple
// pages (Dashboard list, TicketDetail card, future Reports legend).
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
