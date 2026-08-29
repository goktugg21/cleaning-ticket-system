import { Children, useState } from "react";
import type { ReactNode } from "react";
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
 *
 * P-3 §A.7 — NO INNER SCROLLBAR. The body used to be capped at 420px
 * and scroll inside itself, which hid the bottom of a busy day behind
 * a scrollbar nobody saw (Chrome paints overlay scrollbars that fade).
 * The column now GROWS with its load, and past `FOLD` cards it folds
 * the rest behind one "Toon er nog N" button — the reader sees that
 * there is more, and how much, instead of a clean edge that lies.
 */

/** How many cards a column shows before it folds the rest. */
const FOLD = 6;

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
  const [expanded, setExpanded] = useState(false);
  const cards = Children.toArray(children);
  const hidden = expanded ? 0 : Math.max(0, cards.length - FOLD);
  const shown = hidden > 0 ? cards.slice(0, FOLD) : cards;
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
          {/* Today the only caller omits `onOpen` exactly when the count
              is 0, so this never renders — but the count is a property
              of the COLUMN, not of whether it has a door, and a future
              caller that passes work without a handler should not
              silently lose it. */}
          {count > 0 && (
            <span className="wp-day-count">
              {t("agenda.day_count", { count })}
            </span>
          )}
        </div>
      )}
      <div className="wp-day-body">
        {count === 0 ? (
          <div className="wp-day-empty" data-testid="agenda-day-empty">
            {/* P-2 — words, not a crossed-out calendar that reads as a
                broken image. */}
            {t("agenda.day_empty")}
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
            {shown}
          </ul>
        )}
        {cards.length > FOLD && (
          <button
            type="button"
            className="btn btn-ghost btn-sm wp-day-more"
            onClick={() => setExpanded((open) => !open)}
            aria-expanded={expanded}
            data-testid="agenda-day-more"
          >
            {hidden > 0
              ? t("agenda.show_more", { count: hidden })
              : t("agenda.show_less")}
          </button>
        )}
      </div>
    </section>
  );
}
