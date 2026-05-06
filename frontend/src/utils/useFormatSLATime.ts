import { useTranslation } from "react-i18next";
import { SECONDS_PER_BUSINESS_DAY, BUSINESS_HOURS_PER_DAY } from "./sla";

// Same shape as the previous formatSLATime export, but the suffix words
// ("left" / "overdue") and the zero-state ("Due now") come from the
// active i18next language. The number formatting itself (Xm, Xh Ym, Xd Yh)
// is the same in both languages.
export function useFormatSLATime() {
  const { t } = useTranslation("common");
  return (businessSeconds: number | null): string => {
    if (businessSeconds === null) return "";
    if (businessSeconds === 0) return t("sla.due_now");
    const isOverdue = businessSeconds < 0;
    const abs = Math.abs(businessSeconds);
    const suffix = isOverdue ? t("sla.overdue") : t("sla.left");
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
  };
}
