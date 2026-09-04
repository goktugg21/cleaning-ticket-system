import { useTranslation } from "react-i18next";

import type { WeekWithHours } from "../../api/timesheets.types";
import { useLocaleCode } from "../../lib/intl";
import type { IsoWeek } from "../../lib/isoWeek";
import { formatHours, isoWeeksInYear } from "../../lib/weeksWithHours";

/**
 * P-9 D3 — WHICH WEEKS HOLD HOURS, at a glance.
 *
 * One cell per ISO week of the year shown: filled and taller where
 * hours are saved, faint where none are, outlined on the week the page
 * is on. The week's hours sit in the cell's `title` (and its
 * accessible name); a click moves the page to that week. Shared by the
 * admin Hours page and My hours, so the two mark weeks the same way.
 *
 * Inline styles on purpose: the Hours pages lay their bars out inline
 * (W-HR1), and a strip this small does not earn a stylesheet block.
 */
export function WeekHoursStrip({
  year,
  week,
  weeks,
  onPick,
  testIdPrefix,
}: {
  year: number;
  week: IsoWeek;
  weeks: readonly WeekWithHours[];
  onPick: (next: IsoWeek) => void;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  const locale = useLocaleCode();
  const count = isoWeeksInYear(year);
  const byWeek = new Map<number, WeekWithHours>();
  for (const entry of weeks) {
    if (entry.iso_year === year) byWeek.set(entry.iso_week, entry);
  }
  const marked = [...byWeek.keys()].sort((a, b) => a - b);

  return (
    <ol
      aria-label={t("hours_weeks.strip_aria", { year })}
      data-testid={`${testIdPrefix}-strip`}
      data-weeks-with-hours={marked.join(",")}
      style={{
        display: "flex",
        gap: 3,
        listStyle: "none",
        margin: 0,
        padding: 0,
        alignItems: "flex-end",
        flexBasis: "100%",
        minWidth: 0,
        height: 18,
      }}
    >
      {Array.from({ length: count }, (_unused, index) => index + 1).map((n) => {
        const hit = byWeek.get(n);
        const current = week.isoYear === year && week.isoWeek === n;
        const title = hit
          ? t("hours_weeks.strip_title_hours", {
              week: n,
              hours: formatHours(hit.hours, locale),
            })
          : t("hours_weeks.strip_title_empty", { week: n });
        return (
          <li key={n} style={{ flex: "1 1 0", minWidth: 0, maxWidth: 16 }}>
            <button
              type="button"
              title={title}
              aria-label={title}
              aria-current={current ? "true" : undefined}
              data-testid={`${testIdPrefix}-mark-${n}`}
              data-has-hours={hit ? "true" : "false"}
              onClick={() => onPick({ isoYear: year, isoWeek: n })}
              style={{
                display: "block",
                width: "100%",
                height: hit ? 14 : 7,
                padding: 0,
                borderRadius: 2,
                border: "none",
                outline: current ? "2px solid var(--text)" : "none",
                outlineOffset: 1,
                background: hit ? "var(--green)" : "var(--border)",
                cursor: "pointer",
              }}
            />
          </li>
        );
      })}
    </ol>
  );
}
