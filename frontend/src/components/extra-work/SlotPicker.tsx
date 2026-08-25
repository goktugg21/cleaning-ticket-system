/**
 * W5-B / W-EW4 / T1 §1 — pick the days a series runs on.
 *
 * Each pick becomes ONE real Extra Work. That is stated on the screen,
 * next to the count, because "5 days" and "5 separate jobs, each with
 * its own price and its own invoice line" are not the same thought and
 * the operator is about to create the second one.
 *
 * T1 §1 — WHY THIS IS A CALENDAR NOW.
 *
 * It used to be a date field and an "Add day" button: to book five days
 * you typed five dates and pressed the button five times, and the thing
 * you were actually choosing — a shape in a month — was never on
 * screen. Tapping days in a month grid is the same choice in one
 * gesture, and it shows the weekend you were about to book by accident.
 *
 * The grid deliberately mirrors `planned-work/RecurringJobCalendar`:
 * 42 cells, Monday-first, same `repeat(7, 1fr)` geometry and the same
 * `weekday_short.N` vocabulary. Two calendars in one product that
 * disagree about which column Monday is in is its own small betrayal,
 * and a third invented one would have been worse.
 *
 * ONE TIME FOR ALL DAYS, THEN PER-ROW. Most series run at the same hour
 * every day, so that is one field, applied to every selected day. It is
 * a starting point and not a lock: each generated row still carries its
 * own date and its own time and can be changed or removed without
 * touching the others.
 *
 * WHAT THIS CONTROL DELIBERATELY DOES NOT DO. It offers no weekly
 * repeat — a schedule that runs every week until somebody stops it is
 * Recurring Work, a different feature with its own page — and no
 * "Moment" (at / before / after handover), which was taken out of this
 * product's UI and must not come back. The `condition` column stays
 * nullable and this control simply never sends the field:
 * `views_groups._SlotSerializer` has it `required=False`, and
 * `groups.create_batch` reads it with `slot.get("condition")`, so a
 * slot nobody was asked about stays unanswered instead of silently
 * claiming AT_HANDOVER.
 *
 * THE CEILING IS SHOWN, NOT JUST ENFORCED. The server refuses more than
 * `MAX_SLOTS`; this control will not build a list it knows will be
 * rejected, and says why while the operator is still choosing.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";

import type { ExtraWorkSlot } from "../../api/types";
import { BoundedList } from "../BoundedList";

/** Mirrors `groups.MAX_BATCH_SLOTS`. The SERVER's value is the rule;
 *  this one keeps the picker from building a list it knows will be
 *  refused. If they ever disagree the server wins and says so. */
export const MAX_SLOTS = 60;

/** How many days it takes before "is this actually a schedule?" is
 *  worth asking out loud. Four is the first count that cannot be read
 *  as "a couple of visits this month". */
const RECURRING_HINT_AT = 4;

/** Seven ~40px columns plus their gaps. Keeps the grid reading as a
 *  month instead of stretching to whatever the form is wide. */
const CALENDAR_WIDTH = 308;

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}

export function SlotPicker({
  slots,
  onChange,
}: {
  slots: ExtraWorkSlot[];
  onChange: (next: ExtraWorkSlot[]) => void;
}) {
  const { t, i18n } = useTranslation(["extra_work", "common"]);
  const locale = i18n.language || "nl";

  const [monthCursor, setMonthCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  /** The one optional time applied to every day as it is picked. */
  const [timeForAll, setTimeForAll] = useState("");
  const [error, setError] = useState("");

  const selected = useMemo(
    () => new Map(slots.map((s) => [s.date, s])),
    [slots],
  );

  /** 42-cell Monday-first grid for the displayed month — the same shape
   *  `RecurringJobCalendar` builds. */
  const cells = useMemo(() => {
    const offset = (monthCursor.getDay() + 6) % 7; // days back to Monday
    const gridStart = new Date(
      monthCursor.getFullYear(),
      monthCursor.getMonth(),
      1 - offset,
    );
    return Array.from(
      { length: 42 },
      (_, i) =>
        new Date(
          gridStart.getFullYear(),
          gridStart.getMonth(),
          gridStart.getDate() + i,
        ),
    );
  }, [monthCursor]);

  function toggleDay(iso: string) {
    setError("");
    if (selected.has(iso)) {
      onChange(slots.filter((s) => s.date !== iso));
      return;
    }
    if (slots.length + 1 > MAX_SLOTS) {
      setError(t("series.slot_limit", { limit: MAX_SLOTS }));
      return;
    }
    // OMITTED, not defaulted — `condition` is never set here at all.
    const slot: ExtraWorkSlot = { date: iso };
    if (timeForAll !== "") slot.time = timeForAll;
    onChange([...slots, slot]);
  }

  /** The one time field. Applying it rewrites every selected day, which
   *  is what "for all days" means; a day picked afterwards inherits it
   *  from `toggleDay`. Clearing it clears them all, because a blank
   *  time is a real answer and not an absence of instruction. */
  function applyTimeToAll(value: string) {
    setTimeForAll(value);
    onChange(
      slots.map((s) => {
        const next: ExtraWorkSlot = { date: s.date };
        if (value !== "") next.time = value;
        return next;
      }),
    );
  }

  /** Per-row date edit. The calendar reads the same list, so moving a
   *  row moves its tick; a collision with a day already picked is
   *  refused rather than silently collapsing two rows into one. */
  function editRowDate(fromISO: string, toISOValue: string) {
    setError("");
    if (!toISOValue || toISOValue === fromISO) return;
    if (selected.has(toISOValue)) {
      setError(t("series.slot_duplicate"));
      return;
    }
    onChange(
      slots.map((s) => (s.date === fromISO ? { ...s, date: toISOValue } : s)),
    );
  }

  function editRowTime(iso: string, value: string) {
    onChange(
      slots.map((s) => {
        if (s.date !== iso) return s;
        const next: ExtraWorkSlot = { date: s.date };
        if (value !== "") next.time = value;
        return next;
      }),
    );
  }

  const sorted = useMemo(
    () =>
      [...slots].sort((a, b) =>
        `${a.date}${a.time ?? ""}`.localeCompare(`${b.date}${b.time ?? ""}`),
      ),
    [slots],
  );

  return (
    <div className="ew-slot-picker" data-testid="extra-work-slot-picker">
      {/* T1 §1 — A MINI MONTH, not a banner.
          Left to itself the grid takes the whole form width, and seven
          columns of a 970px form are 135px wide and 30px tall: bars,
          not days. A month is recognisable because it is roughly square,
          so the nav, the weekday header and the grid share one capped
          box and the cells come out about 40px across. */}
      <div style={{ maxWidth: CALENDAR_WIDTH }}>
      {/* Month nav */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setMonthCursor((c) => addMonths(c, -1))}
          aria-label={t("series.month_prev")}
          data-testid="extra-work-slot-prev-month"
        >
          <ChevronLeft size={16} strokeWidth={2.2} />
        </button>
        <strong data-testid="extra-work-slot-month">
          {monthCursor.toLocaleDateString(locale, {
            month: "long",
            year: "numeric",
          })}
        </strong>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setMonthCursor((c) => addMonths(c, 1))}
          aria-label={t("series.month_next")}
          data-testid="extra-work-slot-next-month"
        >
          <ChevronRight size={16} strokeWidth={2.2} />
        </button>
      </div>

      {/* Weekday header, Monday-first (ISO 1..7) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(7, 1fr)",
          gap: 4,
          marginBottom: 4,
        }}
      >
        {[1, 2, 3, 4, 5, 6, 7].map((iso) => (
          <div
            key={iso}
            className="muted small"
            style={{ textAlign: "center", fontWeight: 600 }}
          >
            {t(`series.weekday_short.${iso}`)}
          </div>
        ))}
      </div>

      {/* Day grid — tapping toggles the day. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(7, 1fr)",
          gap: 4,
        }}
        role="group"
        aria-label={t("series.calendar_label")}
        data-testid="extra-work-slot-calendar"
      >
        {cells.map((cell) => {
          const iso = toISODate(cell);
          const inMonth = cell.getMonth() === monthCursor.getMonth();
          const isPicked = selected.has(iso);
          return (
            <button
              key={iso}
              type="button"
              className="btn btn-ghost btn-sm"
              aria-pressed={isPicked}
              disabled={!inMonth}
              onClick={() => toggleDay(iso)}
              data-testid="extra-work-slot-day"
              data-iso={iso}
              data-picked={isPicked ? "true" : "false"}
              style={{
                padding: "6px 0",
                minWidth: 0,
                justifyContent: "center",
                visibility: inMonth ? "visible" : "hidden",
                background: isPicked ? "var(--green-2)" : undefined,
                color: isPicked ? "#FFFFFF" : undefined,
                borderColor: isPicked ? "var(--green-2)" : undefined,
                fontWeight: isPicked ? 700 : undefined,
              }}
            >
              {cell.getDate()}
            </button>
          );
        })}
      </div>
      </div>

      {/* ONE time for every picked day. */}
      <label className="field" style={{ marginTop: 12, maxWidth: 220 }}>
        <span className="muted small">{t("series.time_for_all")}</span>
        <input
          type="time"
          className="field-input"
          value={timeForAll}
          onChange={(e) => applyTimeToAll(e.target.value)}
          data-testid="extra-work-slot-time-for-all"
        />
      </label>

      {/* T1 §1 — the cap and the duplicate refusal render HERE, against
          the calendar that produced them, not in the page's error
          banner a screen away. */}
      {error && (
        <div
          className="alert-error"
          role="alert"
          style={{ marginTop: 8 }}
          data-testid="extra-work-slot-error"
        >
          {error}
        </div>
      )}

      <p className="ew-slot-count" data-testid="extra-work-slot-count">
        <strong>{t("series.slot_count", { count: slots.length })}</strong>{" "}
        <span className="muted small">
          {t("series.slot_ceiling", { limit: MAX_SLOTS })}
        </span>
      </p>

      {slots.length >= RECURRING_HINT_AT && (
        <p
          className="muted small"
          role="status"
          data-testid="extra-work-slot-recurring-hint"
        >
          {t("series.recurring_nudge")}{" "}
          {/* `.link` on purpose: inside a `muted small` paragraph an
              unclassed <Link> inherits the paragraph's colour and has no
              underline, so the one word that leads to the other feature
              looks like the sentence around it. */}
          <Link className="link" to="/planned-work/new">
            {t("series.recurring_nudge_link")}
          </Link>
        </p>
      )}

      {/* The picked days, each still its own row. */}
      <BoundedList
        size="sm"
        count={sorted.length}
        ariaLabel={t("series.slot_list")}
        testIdPrefix="extra-work-slot-list"
      >
        <ul className="ew-slot-list">
          {sorted.map((slot) => (
            <li
              key={slot.date}
              className="ew-slot-item"
              data-testid="extra-work-slot-item"
            >
              <input
                type="date"
                className="field-input"
                /* A date input needs room for its own placeholder
                   (dd/mm/yyyy plus the picker glyph); the row's default
                   width clipped it to "3/01/2026". */
                style={{ minWidth: 150 }}
                aria-label={t("series.slot_date")}
                value={slot.date}
                onChange={(e) => editRowDate(slot.date, e.target.value)}
                data-testid="extra-work-slot-row-date"
              />
              <input
                type="time"
                className="field-input"
                style={{ minWidth: 120 }}
                aria-label={t("series.slot_time")}
                value={slot.time ?? ""}
                onChange={(e) => editRowTime(slot.date, e.target.value)}
                data-testid="extra-work-slot-row-time"
              />
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() =>
                  onChange(slots.filter((s) => s.date !== slot.date))
                }
                data-testid="extra-work-slot-remove"
              >
                {t("series.slot_remove")}
              </button>
            </li>
          ))}
        </ul>
      </BoundedList>
    </div>
  );
}
