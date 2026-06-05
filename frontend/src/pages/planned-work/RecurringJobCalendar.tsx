// Sprint 6 — recurring-job occurrence calendar (explicit per-date control).
//
// A navigable month grid over GET …/calendar/. The recurrence RULE pre-fills
// the ticks; the manager hand-shapes the dates:
//   * untick a rule/PLANNED date  -> skip-date  (persists a SKIPPED row)
//   * re-tick a skipped date       -> clear-date (reverts to rule-generated)
//   * tick an empty off-rule date  -> add-date   (ad-hoc PLANNED occurrence)
//   * untick an ad-hoc date        -> clear-date (removes it)
// A date with a generated/completed ticket is LOCKED (not toggleable). Each
// click toggles the WHOLE date (all active windows — the backend actions are
// per-date). After each action the month's calendar is refetched.
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
  PlannedOccurrenceStatus,
  RecurringJobCalendar,
  RecurringJobCalendarDate,
} from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { useToast } from "../../components/ToastProvider";

type DateTick = "rule" | "skipped" | "adhoc" | "locked" | "empty";

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
}: {
  jobId: number;
  canManage: boolean;
}) {
  const { t, i18n } = useTranslation(["planned_work", "common"]);
  const { push } = useToast();
  const locale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [calendar, setCalendar] = useState<RecurringJobCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyDate, setBusyDate] = useState<string | null>(null);
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

  async function handleDayClick(date: string, tick: DateTick) {
    if (busyDate || !canManage) return;
    setBusyDate(date);
    try {
      let toastKey: string;
      if (tick === "empty") {
        await addRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_added";
      } else if (tick === "rule") {
        await skipRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_skipped";
      } else if (tick === "skipped" || tick === "adhoc") {
        await clearRecurringJobDate(jobId, date);
        toastKey = "calendar.toast_cleared";
      } else {
        return; // locked — not toggleable
      }
      await reload();
      push({ variant: "success", title: t(toastKey) });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    } finally {
      setBusyDate(null);
    }
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
        <div>
          <div className="section-head-title">{t("calendar.title")}</div>
          <p className="muted small" style={{ marginTop: 2 }}>
            {t("calendar.desc")}
          </p>
        </div>
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
          const interactive =
            canManage && inMonth && !isPast && tick !== "locked";
          const windowCount = entry?.windows.length ?? 0;
          const ticketId =
            entry?.windows.find((w) => w.ticket_id != null)?.ticket_id ?? null;

          return (
            <CalendarCell
              key={iso}
              iso={iso}
              dayNumber={cell.getDate()}
              inMonth={inMonth}
              isPast={isPast}
              tick={tick}
              interactive={interactive}
              busy={busyDate === iso}
              windowCount={windowCount}
              ticketId={tick === "locked" ? ticketId : null}
              title={windowsTitle(entry)}
              addLabel={t("calendar.add_aria", { date: iso })}
              onClick={() => handleDayClick(iso, tick)}
            />
          );
        })}
      </div>

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
  busy,
  windowCount,
  ticketId,
  title,
  addLabel,
  onClick,
}: {
  iso: string;
  dayNumber: number;
  inMonth: boolean;
  isPast: boolean;
  tick: DateTick;
  interactive: boolean;
  busy: boolean;
  windowCount: number;
  ticketId: number | null;
  title: string;
  addLabel: string;
  onClick: () => void;
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

  // A locked, ticket-linked date deep-links to its operational ticket.
  if (tick === "locked" && ticketId != null) {
    return (
      <Link
        to={`/tickets/${ticketId}`}
        style={{ ...baseStyle, textDecoration: "none" }}
        title={title}
        data-testid="calendar-day"
        data-date={iso}
        data-tick={tick}
      >
        {inner}
      </Link>
    );
  }

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
      onClick={onClick}
      disabled={busy}
      title={tick === "empty" ? addLabel : title}
      aria-label={tick === "empty" ? addLabel : undefined}
      data-testid="calendar-day"
      data-date={iso}
      data-tick={tick}
    >
      {inner}
    </button>
  );
}
