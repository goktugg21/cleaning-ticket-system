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
import type { CSSProperties } from "react";
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

type DateTick = "rule" | "skipped" | "adhoc" | "locked" | "empty";

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
>(["TICKET_CREATED", "COMPLETED", "MISSED", "RESCHEDULED", "CANCELLED"]);

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

function deriveTick(entry: RecurringJobCalendarDate | undefined): DateTick {
  if (!entry || entry.windows.length === 0) return "empty";
  const w = entry.windows;
  if (w.some((x) => LOCKED_STATUSES.has(x.status))) return "locked";
  if (w.every((x) => x.status === "SKIPPED")) return "skipped";
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
}: {
  jobId: number;
  canManage: boolean;
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
        const data = await getRecurringJobCalendar(jobId);
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
  }, [jobId]);

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
    const data = await getRecurringJobCalendar(jobId);
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
      className="card"
      style={{ padding: "16px 18px", marginBottom: 16 }}
      data-testid="recurring-job-calendar"
    >
      <div className="section-head">
        <div className="section-head-title">{t("calendar.title")}</div>
      </div>

      {!canManage && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("calendar.archived_readonly")}
        </p>
      )}

      {/* Month navigation */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginTop: 12,
          marginBottom: 8,
        }}
      >
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
            {t(`weekday_short.${iso}`)}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(7, 1fr)",
          gap: 4,
        }}
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

      {/* Legend */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 14,
          marginTop: 12,
        }}
      >
        <LegendDot tone="var(--accent, #2563eb)" label={t("calendar.legend_rule")} />
        <LegendDot tone="#7c3aed" label={t("calendar.legend_adhoc")} />
        <LegendDot tone="var(--text-faint, #9ca3af)" label={t("calendar.legend_skipped")} />
        <LegendDot tone="#16a34a" label={t("calendar.legend_done")} />
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

function LegendDot({ tone, label }: { tone: string; label: string }) {
  return (
    <span
      className="muted small"
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 10,
          height: 10,
          borderRadius: 3,
          background: tone,
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}

const TICK_STYLE: Record<
  DateTick,
  { border: string; background: string; color: string }
> = {
  rule: {
    border: "var(--accent, #2563eb)",
    background: "var(--accent-soft, #eff6ff)",
    color: "var(--accent, #2563eb)",
  },
  adhoc: { border: "#7c3aed", background: "#f5f3ff", color: "#7c3aed" },
  skipped: {
    border: "var(--border)",
    background: "transparent",
    color: "var(--text-faint, #9ca3af)",
  },
  locked: { border: "#16a34a", background: "#f0fdf4", color: "#16a34a" },
  empty: {
    border: "var(--border)",
    background: "transparent",
    color: "var(--text, inherit)",
  },
};

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
  const style = TICK_STYLE[tick];
  const inner = (
    <>
      <span style={{ fontSize: 12, fontWeight: 600 }}>{dayNumber}</span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
        {tick === "rule" && <Check size={14} strokeWidth={2.5} />}
        {tick === "adhoc" && (
          <>
            <Check size={14} strokeWidth={2.5} />
            <Plus size={11} strokeWidth={3} />
          </>
        )}
        {tick === "locked" && <Lock size={12} strokeWidth={2.2} />}
        {windowCount > 1 && (
          <span style={{ fontSize: 10, fontWeight: 700 }}>×{windowCount}</span>
        )}
      </span>
    </>
  );

  const baseStyle: CSSProperties = {
    minHeight: 46,
    borderRadius: 8,
    border: `1px solid ${inMonth ? style.border : "transparent"}`,
    background: inMonth ? style.background : "transparent",
    color: inMonth ? style.color : "var(--text-faint, #9ca3af)",
    opacity: inMonth ? (isPast && tick !== "locked" ? 0.5 : 1) : 0.35,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
    padding: 4,
    width: "100%",
  };

  if (!inMonth) {
    return <div style={baseStyle} aria-hidden="true" />;
  }

  // A date with nothing to offer stays inert — the same non-interactive
  // cell it has always been, so an out-of-horizon or fully-past date does
  // not invite a click that would open an empty panel.
  if (!interactive) {
    return (
      <div
        style={baseStyle}
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
      style={{ ...baseStyle, cursor: busy ? "wait" : "pointer" }}
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
