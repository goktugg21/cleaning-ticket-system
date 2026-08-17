import { useTranslation } from "react-i18next";

import { HoursComparisonView } from "./HoursComparisonView";

/**
 * Sprint 166 §4 — the SCREEN for the hours comparison, kept as a
 * standalone route so a direct link still works. Sprint 169 §6 moved
 * the report itself into `HoursComparisonView`, which the Reports page
 * also opens in a modal.
 */
export function HoursComparisonPage() {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <div data-testid="hours-comparison-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("eyebrow")}
          </div>
          <h2 className="page-title">{t("hours_comparison.title")}</h2>
          <p className="page-sub">{t("hours_comparison.subtitle")}</p>
        </div>
      </div>
      <HoursComparisonView />
    </div>
  );
}
