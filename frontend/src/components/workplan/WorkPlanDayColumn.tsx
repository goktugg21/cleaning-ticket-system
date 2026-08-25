import type { ReactNode } from "react";
import { CalendarOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLocaleCode } from "../../lib/intl";
import "./workplan-day.css";

/**
 * Sprint 183 §2 — one day of the week, as a boxed column.
 *
 * The reference's day is a tinted header band carrying the weekday name
 * over a large day number, above a body of fixed generous height. Ours
 * was a plain `<h3>` with the full localised date ("Monday 3 August
 * 2026") and a body that grew with its load, so a week with one busy
 * Thursday rendered as one tall column and six stubs.
 *
 * Two things this does that the reference's screenshot cannot show, and
 * that we keep:
 *
 *   - the header carries the day's COUNT. A column whose body scrolls
 *     can hide work below its fold, and "3" in the header is how the
 *     reader knows to scroll. The reference's columns are short enough
 *     not to need it; ours are not, because this product puts a sidebar
 *     beside the week.
 *   - the empty state has an accessible NAME. The reference shows a
 *     bare muted icon; a screen reader would read nothing at all, so
 *     the icon carries the sentence the column used to print.
 */
export function WorkPlanDayColumn({
  iso,
  isToday,
  count,
  onOpen,
  children,
}: {
  /** "YYYY-MM-DD" — the day this column stands for. */
  iso: string;
  isToday: boolean;
  /** How many cards are in it, AFTER filtering. */
  count: number;
  /** T2-3 — open this day full-width. Absent on a day with nothing in
   *  it: a modal listing nothing is a click that answers nothing, and a
   *  header that looks pressable but is not is worse than a plain one. */
  onOpen?: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("staff_slots");
  const locale = useLocaleCode();
  // Explicit midnight: a bare date string parses as UTC, which anywhere
  // east of Greenwich renders the previous day.
  const date = new Date(`${iso}T00:00:00`);
  const weekday = date.toLocaleDateString(locale, { weekday: "short" });
  const dayNumber = date.toLocaleDateString(locale, { day: "numeric" });
  const fullDate = date.toLocaleDateString(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <section
      className={isToday ? "wp-day wp-day-today" : "wp-day"}
      data-testid={isToday ? "agenda-day-today" : "agenda-day"}
      aria-label={fullDate}
    >
      {/* T2-3 — the header is the door to the day. A <button> rather
          than a click handler on the div, so it is reachable by keyboard
          and announces itself; `aria-label` repeats the full date
          because "Mon 3" is not a sentence a screen reader can use. */}
      {onOpen ? (
        <button
          type="button"
          className="wp-day-head wp-day-head-button"
          data-testid="agenda-group-heading"
          onClick={onOpen}
          aria-label={fullDate}
        >
          <span className="wp-day-name">{weekday}</span>
          <span className="wp-day-number">{dayNumber}</span>
          <span className="wp-day-count">
            {t("agenda.day_count", { count })}
          </span>
        </button>
      ) : (
        <div className="wp-day-head" data-testid="agenda-group-heading">
          <span className="wp-day-name">{weekday}</span>
          <span className="wp-day-number">{dayNumber}</span>
        </div>
      )}
      <div className="wp-day-body">
        {count === 0 ? (
          <div
            className="wp-day-empty"
            data-testid="agenda-day-empty"
            role="img"
            aria-label={t("agenda.day_empty")}
            title={t("agenda.day_empty")}
          >
            <CalendarOff size={22} strokeWidth={1.75} />
          </div>
        ) : (
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {children}
          </ul>
        )}
      </div>
    </section>
  );
}
