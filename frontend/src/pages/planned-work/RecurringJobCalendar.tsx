// Sprint 6 — recurring-job occurrence calendar (explicit per-date control).
//
// A navigable month grid over GET …/calendar/. The recurrence RULE pre-fills
// the ticks; the manager hand-shapes the dates:
//   * untick a rule/PLANNED date  -> skip-date  (persists a SKIPPED row)
//   * re-tick a skipped date       -> clear-date (reverts to rule-generated)
//   * tick an empty off-rule date  -> add-date   (ad-hoc PLANNED occurrence)
//   * untick an ad-hoc date        -> clear-date (removes it)
// A date with a generated/completed ticket is LOCKED (not toggleable). Each
// action applies to the WHOLE date (all active windows — the backend actions
// are per-date). After each action the month's calendar is refetched.
//
// W-PW1 — the calendar is the page's primary surface, so a click no longer
// fires an action blind. It opens that date's ACTIONS WHERE THE CLICK
// HAPPENED, and the action is chosen from the list. The state machine above
// is untouched: the popover offers exactly the transitions that date allows,
// and each one still calls the same per-date endpoint it always did. What
// changed is that the operator now reads what is about to happen before it
// happens, and that the actions the occurrence TABLE used to own (change the
// time window, cancel the visit, open the spawned ticket) are reachable from
// the date they belong to instead of from a second list of the same dates.
//
// Provider-only surface (the parent gates rendering on the recurring-job
// detail page). Read-only when the job is archived.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Check, ChevronLeft, ChevronRight, Lock, Plus } from "lucide-react";

import {
  addRecurringJobDate,
  clearRecurringJobDate,
  getRecurringJobCalendar,
  skipRecurringJobDate,
} from "../../api/plannedWork";
import type {
  PlannedOccurrence,
  PlannedOccurrenceStatus,
  RecurringJobCalendar,
  RecurringJobCalendarDate,
} from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { useToast } from "../../components/ToastProvider";

type DateTick = "rule" | "skipped" | "adhoc" | "locked" | "cancelled" | "empty";

/** One entry in a date's actions panel. Exactly one of `run` / `to`:
 *  an action that writes, or a link that leaves the page. */
interface DayAction {
  key: string;
  label: string;
  run?: () => void;
  to?: string;
}

// Statuses that mean the date has real, materialized/actioned work and so is
// not toggleable from the calendar (cancel/override live in the table below).
const LOCKED_STATUSES: ReadonlySet<PlannedOccurrenceStatus> = new Set<
  PlannedOccurrenceStatus
>(["TICKET_CREATED", "COMPLETED"]);

/** W-FIX1 B4 (audit F36) — a date whose visits were called off, missed
 *  or moved away is NOT "ticket created / done"; it used to paint green
 *  with a lock under that legend. Its own tick, its own legend line. */
const CALLED_OFF_STATUSES: ReadonlySet<PlannedOccurrenceStatus> = new Set<
  PlannedOccurrenceStatus
>(["MISSED", "RESCHEDULED", "CANCELLED"]);

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISODate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}

function monthIndex(d: Date): number {
  return d.getFullYear() * 12 + d.getMonth();
}

/** W-FIX1 B4 — the fetch window: from the job's start (or 180 days
 *  back, whichever is later — the server caps the whole span at 366
 *  days) to 180 days ahead. */
function horizonFor(minDate: string | undefined): { from: string; to: string } {
  const today = new Date();
  const back = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 180);
  const ahead = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 180);
  let from = back;
  if (minDate) {
    const start = parseISODate(minDate);
    if (start.getTime() > back.getTime()) from = start;
  }
  if (from.getTime() > today.getTime()) from = today;
  return { from: toISODate(from), to: toISODate(ahead) };
}

function deriveTick(entry: RecurringJobCalendarDate | undefined): DateTick {
  if (!entry || entry.windows.length === 0) return "empty";
  const w = entry.windows;
  if (w.some((x) => LOCKED_STATUSES.has(x.status))) return "locked";
  if (w.every((x) => x.status === "SKIPPED")) return "skipped";
  if (w.every((x) => CALLED_OFF_STATUSES.has(x.status) || x.status === "SKIPPED")) {
    return "cancelled";
  }
  if (w.some((x) => x.is_ad_hoc)) return "adhoc";
  return "rule";
}

export function RecurringJobCalendar({
  jobId,
  canManage,
  occurrencesByDate,
  onOverride,
  onCancelVisit,
  onChanged,
  minDate,
}: {
  jobId: number;
  canManage: boolean;
  /** W-FIX1 B4 (audit F48) — the earliest month the calendar may show:
   *  the job's start. The horizon is fetched from there (bounded by
   *  the server's 366-day cap) so "Previous month" reaches the past. */
  minDate?: string;
  /** The job's occurrences keyed by ISO date. The calendar endpoint says
   *  what a date IS; the override and cancel actions need the occurrence
   *  ROW, which only the occurrence list carries — so the parent, which
   *  already loads it, hands it down rather than this component fetching
   *  the same rows a second time. */
  occurrencesByDate: Map<string, PlannedOccurrence[]>;
  onOverride: (occ: PlannedOccurrence) => void;
  onCancelVisit: (occ: PlannedOccurrence) => void;
  /** Fired after any per-date write, so the parent can re-read the
   *  occurrences it handed down. Without it the popover would keep
   *  offering actions computed from rows the write just invalidated. */
  onChanged: () => void;
}) {
  const { t, i18n } = useTranslation(["planned_work", "common"]);
  const { push } = useToast();
  const locale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [calendar, setCalendar] = useState<RecurringJobCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyDate, setBusyDate] = useState<string | null>(null);
  /** Treatment 1 — a refused date write, shown in the popover that fired
   *  it rather than in a toast over an unchanged calendar. */
  const [dateError, setDateError] = useState("");
  // W-PW1 — the open date-actions popover: which date, and the screen rect
  // of the cell that was clicked, so the panel opens against that cell.
  const [dayMenu, setDayMenu] = useState<{
    iso: string;
    tick: DateTick;
    rect: { top: number; left: number; bottom: number; right: number };
  } | null>(null);
  // Lazy-init to the current month; the parent keys this component by job id
  // so a job change remounts + re-seeds (no resync effect).
  const [monthCursor, setMonthCursor] = useState<Date>(() =>
    startOfMonth(new Date()),
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await getRecurringJobCalendar(jobId, horizonFor(minDate));
        if (cancelled) return;
        setCalendar(data);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [jobId, minDate]);

  // Escape closes the panel. Registered only while one is open, so the
  // page carries no listener when there is nothing to close.
  useEffect(() => {
    if (!dayMenu) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setDayMenu(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dayMenu]);

  async function reload() {
    const data = await getRecurringJobCalendar(jobId, horizonFor(minDate));
    setCalendar(data);
  }

  const dateMap = useMemo(() => {
    const map = new Map<string, RecurringJobCalendarDate>();
    for (const entry of calendar?.dates ?? []) map.set(entry.date, entry);
    return map;
  }, [calendar]);

  const todayISO = toISODate(new Date());

  /** The three per-date writes, unchanged in behaviour — only now they
   *  are chosen by name from the popover instead of inferred from the
   *  date's current tick. */
  async function runDateAction(
    date: string,
    action: "add" | "skip" | "clear",
  ) {
    if (busyDate || !canManage) return;
    // Treatment 1 — the popover is NOT dismissed up front. It is the
    // control that fired this write and it is anchored to the very date
    // the write is about, so it is where a refusal has to appear; it
    // used to close first and answer from a toast floating over a
    // calendar that still showed the old tick.
    setDateError("");
    setBusyDate(date);
    try {
      let toastKey: string;
      if (action === "add") {
        await addRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_added";
      } else if (action === "skip") {
        await skipRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_skipped";
      } else {
        await clearRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_cleared";
      }
      await reload();
      onChanged();
      setDayMenu(null);
      push({ variant: "success", title: t(toastKey) });
    } catch (err) {
      setDateError(getApiError(err));
    } finally {
      setBusyDate(null);
    }
  }

  function openDayMenu(iso: string, tick: DateTick, el: HTMLElement) {
    setDateError("");
    const r = el.getBoundingClientRect();
    setDayMenu((current) =>
      current?.iso === iso
        ? null
        : {
            iso,
            tick,
            rect: {
              top: r.top,
              left: r.left,
              bottom: r.bottom,
              right: r.right,
            },
          },
    );
  }

  // Month-nav bounds: only months overlapping the fetched horizon.
  const minMonth = calendar ? startOfMonth(parseISODate(calendar.from)) : null;
  const maxMonth = calendar ? startOfMonth(parseISODate(calendar.to)) : null;
  const canPrev = minMonth ? monthIndex(monthCursor) > monthIndex(minMonth) : false;
  const canNext = maxMonth ? monthIndex(monthCursor) < monthIndex(maxMonth) : false;

  // Build a 6-week (42-cell) Monday-first grid for the displayed month.
  const cells = useMemo(() => {
    const monthStart = monthCursor;
    const offset = (monthStart.getDay() + 6) % 7; // days back to Monday
    const gridStart = new Date(
      monthStart.getFullYear(),
      monthStart.getMonth(),
      1 - offset,
    );
    return Array.from({ length: 42 }, (_, i) =>
      new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i),
    );
  }, [monthCursor]);

  /** What this date can actually be asked to do, in the order an
   *  operator reads them. Empty list => the cell is not clickable, so a
   *  date with nothing to offer never opens an empty panel. */
  function dayActions(iso: string, tick: DateTick): DayAction[] {
    const isPast = iso < todayISO;
    const occs = occurrencesByDate.get(iso) ?? [];
    // The date's actions target ONE occurrence; with several windows on a
    // date the first live one is the row those actions belong to.
    const occ =
      occs.find((o) => o.status !== "CANCELLED" && o.status !== "SKIPPED") ??
      occs[0] ??
      null;
    const ticketId = occ?.ticket_id ?? null;
    const out: DayAction[] = [];

    if (ticketId != null) {
      out.push({ key: "ticket", label: t("calendar.action_open_ticket"), to: `/tickets/${ticketId}` });
    }
    const writable = canManage && !isPast;
    if (writable && tick === "empty") {
      out.push({ key: "add", label: t("calendar.action_add"), run: () => runDateAction(iso, "add") });
    }
    if (writable && tick === "rule") {
      out.push({ key: "skip", label: t("calendar.action_skip"), run: () => runDateAction(iso, "skip") });
    }
    if (writable && tick === "skipped") {
      out.push({ key: "restore", label: t("calendar.action_restore"), run: () => runDateAction(iso, "clear") });
    }
    if (writable && tick === "adhoc") {
      out.push({ key: "remove", label: t("calendar.action_remove"), run: () => runDateAction(iso, "clear") });
    }
    if (canManage && occ && occ.status !== "CANCELLED") {
      out.push({
        key: "override",
        label: t("calendar.action_move"),
        run: () => { setDayMenu(null); onOverride(occ); },
      });
    }
    if (
      canManage &&
      occ &&
      (occ.status === "PLANNED" ||
        occ.status === "TICKET_CREATED" ||
        occ.status === "RESCHEDULED")
    ) {
      out.push({
        key: "cancel",
        label: t("calendar.action_cancel"),
        run: () => { setDayMenu(null); onCancelVisit(occ); },
      });
    }
    return out;
  }

  function windowsTitle(entry: RecurringJobCalendarDate | undefined): string {
    if (!entry) return "";
    return entry.windows
      .map((w) => {
        const label = w.window_label || t("calendar.window_default");
        return `${label}: ${t(`occ_status.${w.status}`)}`;
      })
      .join("\n");
  }

  if (loading) {
    return (
      <div className="card" style={{ padding: "16px 18px", marginBottom: 16 }}>
        <p className="muted small" data-testid="recurring-job-calendar-loading">
          {t("calendar.loading")}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div className="alert-error" role="alert">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div
      className="card rj-cal"
      data-testid="recurring-job-calendar"
    >
      <div className="section-head">
        <div className="section-head-title">{t("calendar.title")}</div>
      </div>

      {!canManage && (
        <p className="muted small rj-cal-readonly">
          {t("calendar.archived_readonly")}
        </p>
      )}

      {/* Month navigation */}
      <div className="rj-cal-nav">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setMonthCursor((c) => addMonths(c, -1))}
          disabled={!canPrev}
          aria-label={t("calendar.prev_month")}
          data-testid="calendar-prev"
        >
          <ChevronLeft size={16} strokeWidth={2.2} />
        </button>
        <strong data-testid="calendar-month-label">
          {monthCursor.toLocaleDateString(locale, {
            month: "long",
            year: "numeric",
          })}
        </strong>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setMonthCursor((c) => addMonths(c, 1))}
          disabled={!canNext}
          aria-label={t("calendar.next_month")}
          data-testid="calendar-next"
        >
          <ChevronRight size={16} strokeWidth={2.2} />
        </button>
      </div>

      {/* Weekday header (Monday-first, ISO 1..7) */}
      <div className="rj-cal-grid rj-cal-weekdays">
        {[1, 2, 3, 4, 5, 6, 7].map((iso) => (
          <div key={iso} className="muted small rj-cal-weekday">
            {t(`weekday_short.${iso}`)}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div
        className="rj-cal-grid"
        data-testid="calendar-grid"
      >
        {cells.map((cell) => {
          const iso = toISODate(cell);
          const inMonth = cell.getMonth() === monthCursor.getMonth();
          const entry = dateMap.get(iso);
          const tick = deriveTick(entry);
          const isPast = iso < todayISO;
          const windowCount = entry?.windows.length ?? 0;
          // A cell is clickable when it has something to offer. That is a
          // strictly wider set than the old `interactive`: a LOCKED date
          // with a ticket, and a past date whose ticket still exists, were
          // reachable before only as a bare link and are now reachable as
          // the same panel every other date opens.
          const interactive = inMonth && dayActions(iso, tick).length > 0;

          return (
            <CalendarCell
              key={iso}
              iso={iso}
              dayNumber={cell.getDate()}
              inMonth={inMonth}
              isPast={isPast}
              tick={tick}
              interactive={interactive}
              open={dayMenu?.iso === iso}
              busy={busyDate === iso}
              windowCount={windowCount}
              title={windowsTitle(entry)}
              menuLabel={t("calendar.open_actions_aria", { date: iso })}
              onOpen={(el) => openDayMenu(iso, tick, el)}
            />
          );
        })}
      </div>

      {/* W-PW1 — the clicked date's actions, opened against that date's
          own cell. The backdrop is a real button so a click anywhere else
          closes it and so the panel is dismissible from the keyboard. */}
      {dayMenu && (
        <>
          <button
            type="button"
            className="pw-daypop-backdrop"
            aria-label={t("calendar.close_actions")}
            onClick={() => setDayMenu(null)}
          />
          <DayMenu
            date={dayMenu.iso}
            rect={dayMenu.rect}
            actions={dayActions(dayMenu.iso, dayMenu.tick)}
            label={formatDayMenuDate(dayMenu.iso, locale)}
            error={dateError}
            onClose={() => setDayMenu(null)}
          />
        </>
      )}

      {/* Legend — P-7 S9: DERIVED from the same tick list the cells
          paint with, so the legend and the grid cannot drift; every
          colour is a CSS class, and skipped / cancelled no longer share
          one dot. */}
      <div className="rj-cal-legend" data-testid="calendar-legend">
        {LEGEND_TICKS.map(([tick, key]) => (
          <LegendDot key={tick} tick={tick} label={t(key)} />
        ))}
      </div>
    </div>
  );
}

function formatDayMenuDate(iso: string, locale: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/** The per-date actions panel. Positioned against the CLICKED CELL's own
 *  screen rect and then clamped into the viewport, so a date in the last
 *  column or the bottom row opens inward instead of off-screen. */
function DayMenu({
  date,
  rect,
  actions,
  label,
  error,
  onClose,
}: {
  date: string;
  rect: { top: number; left: number; bottom: number; right: number };
  actions: DayAction[];
  label: string;
  /** Treatment 1 — the last refusal for THIS date, or "". */
  error: string;
  onClose: () => void;
}) {
  const WIDTH = 210;
  const GAP = 6;
  const estHeight = 42 + actions.length * 34 + (error ? 44 : 0);
  const left = Math.max(
    8,
    Math.min(rect.left, window.innerWidth - WIDTH - 8),
  );
  const opensUpward = rect.bottom + GAP + estHeight > window.innerHeight;
  const top = opensUpward
    ? Math.max(8, rect.top - GAP - estHeight)
    : rect.bottom + GAP;

  return (
    <div
      className="pw-daypop"
      role="menu"
      style={{ top, left, width: WIDTH }}
      data-testid="calendar-day-menu"
      data-date={date}
    >
      <div className="pw-daypop-date">{label}</div>
      {actions.map((action) =>
        action.to ? (
          <Link
            key={action.key}
            to={action.to}
            className="pw-daypop-action"
            role="menuitem"
            data-testid={`calendar-day-action-${action.key}`}
            onClick={onClose}
          >
            {action.label}
          </Link>
        ) : (
          <button
            key={action.key}
            type="button"
            className="pw-daypop-action"
            role="menuitem"
            data-testid={`calendar-day-action-${action.key}`}
            onClick={action.run}
          >
            {action.label}
          </button>
        ),
      )}
      {error && (
        <div
          className="alert-error pw-daypop-error"
          role="alert"
          data-testid="calendar-day-error"
        >
          {error}
        </div>
      )}
    </div>
  );
}

/** The legend's rows, in the order the eye reads them; each tick's
 *  colour lives in `.rj-cal-cell--<tick>` / `.rj-cal-dot--<tick>` in
 *  index.css — one place for the grid and the legend. */
const LEGEND_TICKS: [DateTick, string][] = [
  ["rule", "calendar.legend_rule"],
  ["adhoc", "calendar.legend_adhoc"],
  ["locked", "calendar.legend_done"],
  ["skipped", "calendar.legend_skipped"],
  ["cancelled", "calendar.legend_cancelled"],
];

function LegendDot({ tick, label }: { tick: DateTick; label: string }) {
  return (
    <span className="muted small rj-cal-legend-item" data-tick={tick}>
      <span aria-hidden="true" className={`rj-cal-dot rj-cal-dot--${tick}`} />
      {label}
    </span>
  );
}

function CalendarCell({
  iso,
  dayNumber,
  inMonth,
  isPast,
  tick,
  interactive,
  open,
  busy,
  windowCount,
  title,
  menuLabel,
  onOpen,
}: {
  iso: string;
  dayNumber: number;
  inMonth: boolean;
  isPast: boolean;
  tick: DateTick;
  interactive: boolean;
  open: boolean;
  busy: boolean;
  windowCount: number;
  title: string;
  menuLabel: string;
  onOpen: (el: HTMLElement) => void;
}) {
  const inner = (
    <>
      <span className="rj-cal-day-no">{dayNumber}</span>
      <span className="rj-cal-day-marks">
        {tick === "rule" && <Check size={14} strokeWidth={2.5} />}
        {tick === "adhoc" && (
          <>
            <Check size={14} strokeWidth={2.5} />
            <Plus size={11} strokeWidth={3} />
          </>
        )}
        {tick === "locked" && <Lock size={12} strokeWidth={2.2} />}
        {windowCount > 1 && (
          <span className="rj-cal-day-count">×{windowCount}</span>
        )}
      </span>
    </>
  );

  // P-7 S9 — classes, not a style map: the tick decides the colour
  // through `.rj-cal-cell--<tick>`; out-of-month and past cells are
  // modifiers on the same element.
  const cellClass = [
    "rj-cal-cell",
    inMonth ? `rj-cal-cell--${tick}` : "rj-cal-cell--outside",
    inMonth && isPast && tick !== "locked" ? "rj-cal-cell--past" : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (!inMonth) {
    return <div className={cellClass} aria-hidden="true" />;
  }

  // A date with nothing to offer stays inert — the same non-interactive
  // cell it has always been, so an out-of-horizon or fully-past date does
  // not invite a click that would open an empty panel.
  if (!interactive) {
    return (
      <div
        className={cellClass}
        title={title}
        data-testid="calendar-day"
        data-date={iso}
        data-tick={tick}
      >
        {inner}
      </div>
    );
  }

  return (
    <button
      type="button"
      className={`${cellClass} rj-cal-cell--interactive`}
      style={{ cursor: busy ? "wait" : "pointer" }}
      onClick={(event) => onOpen(event.currentTarget)}
      disabled={busy}
      title={title || menuLabel}
      aria-label={menuLabel}
      aria-haspopup="menu"
      aria-expanded={open}
      data-testid="calendar-day"
      data-date={iso}
      data-tick={tick}
    >
      {inner}
    </button>
  );
}
