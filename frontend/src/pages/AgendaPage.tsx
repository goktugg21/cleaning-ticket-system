// "My Work" — the Work Plan. Role-adaptive since Sprint 111, and since
// Sprint 179A built on ONE composite endpoint rather than on a slot list:
//
//   - Every admitted role gets the WEEK (`WorkPlanWeek` below), fed by
//     GET /api/tickets/work-plan/. The server applies the §12B
//     week-placement rule, merges dated ticket slots WITH assigned extra
//     work, and returns the counts — so a chip describes the whole
//     scope rather than whatever the browser happened to fetch.
//   - STAFF see their own week and can close their own slots.
//   - SA / CA / BM pass `?scope=company` and see the TEAM's week, which
//     the server admits through `scope_tickets_for` / `scope_extra_work_for`
//     — the same scopes the ticket and extra-work lists use, never a
//     second path. A team card carries no completion buttons: an admin
//     reading the week is not working it.
//   - BUILDING_MANAGER additionally keeps its assigned-tickets table
//     below the week. The two answer different questions — "what is
//     dated this week" and "which tickets am I answerable for" — and
//     dropping the second to make room for the first would lose
//     information the manager had.
//   - Any role failing `canAccessAgenda`: a role-guard empty state.
//
// The §12B rule, in one paragraph, because every marker on this page is
// an expression of it: a job appears in the week(s) its planned window
// covers — its home, whatever its status. A STARTED job ALSO appears in
// the current week. A job past its deadline and unfinished also appears
// in the current week, marked overdue. Untouched future work appears
// only in its own week, plus the Upcoming list. And a card shown outside
// its planned week SAYS WHY, with its planned date on it — a card that
// turns up somewhere unexpected without explaining itself is worse than
// one that does not turn up.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlarmClock,
  CalendarClock,
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Lock,
  Ticket,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { setTicketSchedule, updateStaffSlot } from "../api/admin";
import type { SlotStatus } from "../api/admin";
import { getApiError } from "../api/client";
import { listAllTickets } from "../api/tickets";
import type { Role, TicketList } from "../api/types";
import { getWorkPlan, planExtraWorkForDate } from "../api/workPlan";
import type {
  WorkPlanEntry,
  WorkPlanKind,
  WorkPlanResponse,
} from "../api/workPlan";
import { useAuth } from "../auth/AuthContext";
import {
  agendaShowsTeamWeek,
  canAccessAgenda,
} from "../auth/permissions";
import { BoundedList } from "../components/BoundedList";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
// Sprint 183 — the week's three pieces, extracted. This file was 1334
// lines holding a role dispatcher, a manager table, the week, the card,
// the placement marker and two modals; the card and the column are the
// two the sprint rebuilds, and they are easier to reason about with a
// file each than as two of six things in one.
import { WorkPlanCard } from "../components/workplan/WorkPlanCard";
import { detailPath, formatDay } from "../components/workplan/entryHelpers";
import { matchesChip } from "../components/workplan/chips";
import { WorkPlanDayColumn } from "../components/workplan/WorkPlanDayColumn";
import { WorkPlanStrip } from "../components/workplan/WorkPlanStrip";
import type { ChipKey } from "../components/workplan/chips";
import { ExtraWorkOriginPill } from "../components/ExtraWorkOriginPill";
import { PageHeader } from "../components/PageHeader";
import { RejectReasonDialog } from "../components/RejectReasonDialog";
import { SlotStatusBadge } from "../components/SlotStatusBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { formatDate, useLocaleCode } from "../lib/intl";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  isoWeekStart,
  shiftIsoWeek,
  toDateString,
} from "../lib/isoWeek";
import type { IsoWeek } from "../lib/isoWeek";
import { SlotCompletionDialog } from "./SlotCompletionDialog";

// Ticket sub-type label keys — the canonical map lives in the create
// ticket flow (`create_ticket:type_*`); reuse those exact keys here so
// the labels stay in lockstep rather than printing the raw enum (mirrors
// CustomerTicketsPage).
type TicketTypeValue =
  | "REPORT"
  | "COMPLAINT"
  | "REQUEST"
  | "SUGGESTION"
  | "QUOTE_REQUEST"
  // Sprint 143 §2 — the catch-all operators asked for.
  | "OTHER";

const TICKET_TYPE_KEYS: Record<TicketTypeValue, string> = {
  REPORT: "type_report",
  COMPLAINT: "type_complaint",
  REQUEST: "type_request",
  SUGGESTION: "type_suggestion",
  QUOTE_REQUEST: "type_quote_request",
  OTHER: "type_other",
};


// ---------------------------------------------------------------------------
// Role dispatcher — see the file-header comment for the per-role surfaces.
// ---------------------------------------------------------------------------
export function AgendaPage() {
  const { me } = useAuth();
  const role = me?.role ?? null;
  if (!canAccessAgenda(role)) {
    return <AgendaRoleGuard />;
  }
  if (role === "BUILDING_MANAGER") {
    return (
      <>
        <WorkPlanWeek />
        <ManagerTicketsAgenda embedded />
      </>
    );
  }
  return <WorkPlanWeek />;
}

// ---------------------------------------------------------------------------
// SA / CA / any non-STAFF-non-BM role reaching /agenda by direct URL.
// ---------------------------------------------------------------------------
function AgendaRoleGuard() {
  const { t } = useTranslation("staff_slots");
  return (
    <div data-testid="agenda-role-guard">
      <PageHeader title={t("agenda.page_title")} />
      <EmptyState
        icon={Lock}
        title={t("agenda.role_guard_title")}
        description={t("agenda.role_guard_desc")}
        testId="agenda-role-guard-empty"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// BUILDING_MANAGER — assigned tickets (union of Ticket.assigned_to +
// TicketManagerAssignment) via the ticket list `?my_managed=1` filter.
// Kept BESIDE the week rather than replaced by it: "what is dated this
// week" and "which tickets am I answerable for" are different questions.
// ---------------------------------------------------------------------------
function ManagerTicketsAgenda({ embedded = false }: { embedded?: boolean }) {
  const { t } = useTranslation(["staff_slots", "common", "create_ticket"]);
  const [rows, setRows] = useState<TicketList[]>([]);
  // Starts true so the initial render shows the loading bar without a
  // synchronous setState in the effect body (keeps the page clear of
  // react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Server-side `scope_tickets_for` runs BEFORE the `my_managed`
    // filter, so an out-of-scope ticket can never appear even if the
    // caller were somehow name-matched onto it.
    listAllTickets({ my_managed: true })
      .then((data) => {
        if (!cancelled) setRows(data ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(getApiError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-testid="agenda-manager-page" style={embedded ? { marginTop: 24 } : undefined}>
      {!embedded && (
        <PageHeader
          eyebrow={t("common:ops")}
          title={t("agenda.manager_title")}
          subtitle={t("agenda.manager_subtitle")}
        />
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Ticket}
          title={t("agenda.manager_empty_title")}
          description={t("agenda.manager_empty_desc")}
          testId="agenda-manager-empty"
        />
      ) : (
        <section
          className="card"
          data-testid="agenda-manager-section"
          style={{ padding: "20px 22px", overflow: "hidden" }}
        >
          <div className="section-head" style={{ marginBottom: 12 }}>
            <div>
              <div className="section-head-title">
                {t("agenda.manager_list_title")}
              </div>
              <div className="section-head-sub">
                {t("agenda.manager_list_subtitle", { count: rows.length })}
              </div>
            </div>
          </div>

          {/* CLAUDE.md #8 — a SERVER collection, so bounded. A manager
              with two hundred managed tickets used to render two hundred
              rows down the page. */}
          <BoundedList
            size="lg"
            count={rows.length}
            ariaLabel={t("agenda.manager_list_title")}
            testIdPrefix="agenda-manager"
            className="table-wrap"
          >
            <table className="data-table" data-testid="agenda-manager-table">
              <thead>
                <tr>
                  <th>{t("common:customer_view.ticket_table.col_subject")}</th>
                  <th>{t("common:customer_view.ticket_table.col_type")}</th>
                  <th>{t("common:customer_view.ticket_table.col_status")}</th>
                  <th>{t("common:customer_view.ticket_table.col_building")}</th>
                  <th>{t("common:customer_view.ticket_table.col_created")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ClickableRow
                    key={row.id}
                    to={`/tickets/${row.id}`}
                    testId="agenda-manager-row"
                  >
                    <td className="td-subject">
                      <Link to={`/tickets/${row.id}`}>{row.title}</Link>
                      {/* Sprint 180 §3 — a manager's own agenda was the
                          one list where an Extra Work ticket looked
                          exactly like a normal one. The data was
                          already on the row (`extra_work_origin`); only
                          the pill was missing. */}
                      {row.extra_work_origin && (
                        <ExtraWorkOriginPill
                          ewId={row.extra_work_origin.extra_work_request_id}
                          testId="agenda-manager-row-extra-work-origin"
                          style={{ marginLeft: 8 }}
                        />
                      )}
                    </td>
                    <td>
                      {TICKET_TYPE_KEYS[row.type as TicketTypeValue]
                        ? t(
                            `create_ticket:${TICKET_TYPE_KEYS[row.type as TicketTypeValue]}`,
                          )
                        : row.type}
                    </td>
                    <td>
                      <StatusBadge
                        status={{ kind: "ticket", value: row.status }}
                      />
                    </td>
                    <td>{row.building_name}</td>
                    <td>{formatDate(row.created_at)}</td>
                  </ClickableRow>
                ))}
              </tbody>
            </table>
          </BoundedList>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The week. One fetch, one placement rule, one set of counts.
// ---------------------------------------------------------------------------
function WorkPlanWeek() {
  const { t } = useTranslation(["staff_slots", "common", "create_ticket"]);
  const { me } = useAuth();
  const { push } = useToast();
  const locale = useLocaleCode();
  const role = me?.role ?? null;
  const teamWeek = agendaShowsTeamWeek(role);

  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [data, setData] = useState<WorkPlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const [chip, setChip] = useState<ChipKey>("");
  const [kindFilter, setKindFilter] = useState<"" | WorkPlanKind>("");
  /** Sprint 183 §4 — the reference's "search by title or description".
   *
   *  Client-side, and honestly so: the week's entries are a BOUNDED,
   *  complete set (the response says through `truncated` when they are
   *  not), so filtering them here narrows exactly what is on screen. The
   *  CHIPS stay server counts — they describe the whole scope, which no
   *  amount of client filtering can know. A search box that quietly
   *  moved the chip numbers would be the defect Sprint 179A removed. */
  const [search, setSearch] = useState("");
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [upcomingOpen, setUpcomingOpen] = useState(false);
  const [completionTarget, setCompletionTarget] = useState<WorkPlanEntry | null>(
    null,
  );
  const [unableTarget, setUnableTarget] = useState<WorkPlanEntry | null>(null);
  // Sprint 181 §8 — which undated row is being planned, and why the
  // last attempt failed. Keyed by entry rather than a bare boolean so
  // only the pressed button goes busy.
  const [planningKey, setPlanningKey] = useState<string | null>(null);
  const [planError, setPlanError] = useState("");

  const weekParam = formatIsoWeek(week);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const payload = await getWorkPlan(weekParam, teamWeek);
        if (!cancelled) setData(payload);
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
    // The role decides WHICH week is fetched, so it belongs in the deps
    // — a role that resolves after the first render must re-fetch.
  }, [weekParam, teamWeek, refreshKey]);

  function reload() {
    setRefreshKey((n) => n + 1);
  }

  /**
   * Sprint 181 §8 — one action to move a job out of the undated lane
   * and onto a day.
   *
   * "Today", not a date picker, because that is the action the lane
   * exists for: the reason a job has no date is almost never that
   * somebody meant a different one, it is that nobody set one. A picker
   * asks a question; this answers the common case and leaves the
   * uncommon one to the ticket's own schedule card.
   *
   * Sprint 182 §3 — BOTH kinds now. It used to be ticket slots only,
   * and that was a real limit rather than an oversight: an extra work's
   * only date was `preferred_date`, which is the CUSTOMER's wish
   * (Sprint 176 §3 was explicit — the customer states a wish, the
   * provider commits to a deadline), and writing it here would have had
   * the work plan put words in a customer's mouth. Sprint 182 gives the
   * provider a date of its own, `provider_planned_date`, so the lane's
   * one action now works on the rows it could not reach.
   *
   * The two branches write through different endpoints because they are
   * genuinely different records — a ticket has a schedule, an extra work
   * has a planned day — and one shared "plan this" endpoint over two
   * models would be a third thing to keep in step with both.
   */
  async function planForToday(entry: WorkPlanEntry) {
    setPlanningKey(entry.key);
    setPlanError("");
    try {
      // Local noon: a bare midnight is the value most likely to fall
      // into the previous day once the server converts to UTC, which is
      // the bug `extra_work.billing.billing_month` had to be taught
      // about. Noon is safe in every timezone this app runs in.
      const today = new Date();
      today.setHours(12, 0, 0, 0);
      if (entry.ticket_id !== null) {
        await setTicketSchedule(entry.ticket_id, {
          scheduled_start_at: today.toISOString(),
        });
      } else if (entry.extra_work_id !== null) {
        // A DATE, not a timestamp: `provider_planned_date` is a DateField
        // and the day is the whole fact. Formatted from the local date
        // parts rather than `toISOString().slice(0, 10)`, which converts
        // to UTC first and files an evening in Amsterdam under the next
        // day.
        await planExtraWorkForDate(entry.extra_work_id, toDateString(today));
      } else {
        return;
      }
      push({ title: t("agenda.undated_planned"), variant: "success" });
      reload();
    } catch (err) {
      // Surfaced, never swallowed. Until Agent A's branch is merged the
      // extra-work half answers 400 here, and a button that silently did
      // nothing would be worse than one that says why.
      setPlanError(getApiError(err));
    } finally {
      setPlanningKey(null);
    }
  }

  /** Mon-Sun of the loaded week, ALWAYS all seven — a week with nothing
   *  on Thursday must show an empty Thursday, not silently close the
   *  gap and leave the reader counting columns.
   *
   *  Taken from the RESPONSE's own week rather than from local state:
   *  while a week change is in flight the two disagree for a render,
   *  and columns keyed off the new week would find no entry from the
   *  old one — seven "nothing planned" columns, mid-fetch, for a week
   *  that is full. The local week is the fallback for the first paint
   *  only. */
  const dayKeys = useMemo(() => {
    const start = data ? fromDateString(data.week.start) : isoWeekStart(week);
    return Array.from({ length: 7 }, (_unused, index) =>
      toDateString(
        new Date(start.getFullYear(), start.getMonth(), start.getDate() + index),
      ),
    );
  }, [data, week]);

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const needle = search.trim().toLowerCase();
  const counts = data?.counts ?? null;
  const todayKey = data?.today ?? toDateString(new Date());

  const filtered = useMemo(
    () =>
      entries.filter((entry) => {
        if (!matchesChip(entry, chip)) return false;
        if (kindFilter && entry.kind !== kindFilter) return false;
        if (needle) {
          const haystack = [
            entry.title,
            entry.ticket_no,
            entry.building_name,
            entry.customer_name,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(needle)) return false;
        }
        return true;
      }),
    [entries, chip, kindFilter, needle],
  );

  const groups = useMemo(
    () =>
      dayKeys.map((key) => ({
        key,
        items: filtered.filter((entry) => entry.day === key),
      })),
    [dayKeys, filtered],
  );

  /** Nothing anywhere — not "nothing this week". The week's own
   *  emptiness is said by the seven day markers. */
  const planIsEmpty =
    counts !== null &&
    counts.total === 0 &&
    counts.overdue_all === 0 &&
    counts.upcoming === 0 &&
    counts.undated === 0;

  const weekRangeLabel = useMemo(() => {
    const days = isoWeekDays(week);
    return `${formatDate(toDateString(days[0]))} – ${formatDate(
      toDateString(days[6]),
    )}`;
  }, [week]);

  async function handleUnableConfirm(reason: string) {
    const entry = unableTarget;
    setUnableTarget(null);
    if (!entry || entry.ticket_id === null) return;
    try {
      await updateStaffSlot(entry.ticket_id, entry.source_id, {
        slot_status: "UNABLE_TO_COMPLETE",
        unable_to_complete_reason: reason,
      });
      reload();
      push({ variant: "success", title: t("unable.toast_done") });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    }
  }

  function handleCompletionDone() {
    setCompletionTarget(null);
    reload();
    push({ variant: "success", title: t("complete.toast_done") });
  }

  return (
    <div data-testid="agenda-page">
      <PageHeader
        eyebrow={t("common:ops")}
        title={t("agenda.page_title")}
        subtitle={
          teamWeek ? t("agenda.page_subtitle_team") : t("agenda.page_subtitle")
        }
      />

      {/* Sprint 182 §3 — ONE sentence, in plain words, saying what this
          week holds AND what it does not.
          The page used to admit the second half only obliquely: a muted
          count of undated rows below the fold, and six columns reading
          "Nothing planned" while two thirds of the live work sat outside
          the week entirely. A reader had to assemble "most of the work is
          not here" out of an absence. It is stated instead, and in the
          operator's words — jobs, not entries; "not planned yet", not
          "undated". */}
      {counts !== null && (
        <p
          className="muted"
          data-testid="agenda-overview"
          style={{ marginTop: -4 }}
        >
          {t("agenda.overview_week", { count: counts.total })}
          {counts.undated > 0 && (
            <> · {t("agenda.overview_unplanned", { count: counts.undated })}</>
          )}
          {counts.overdue_all > 0 && (
            <> · {t("agenda.overview_overdue", { count: counts.overdue_all })}</>
          )}
        </p>
      )}

      {loading && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="hours-tiles-head">
        <span className="hours-tiles-title">{t("agenda.week_title")}</span>
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
          data-testid="agenda-week-stepper"
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setWeek((w) => shiftIsoWeek(w, -1))}
            aria-label={t("agenda.prev_week")}
            data-testid="agenda-week-prev"
          >
            <ChevronLeft size={14} strokeWidth={2.5} />
          </button>
          {/* Sprint 171 §3 — the week RANGE, which is what an operator
              reads. "2026-W33" is precise and tells nobody which days. */}
          <span
            style={{ fontWeight: 600, minWidth: 210, textAlign: "center" }}
            data-testid="agenda-week-label"
          >
            {weekRangeLabel}
            <span className="muted small" style={{ marginLeft: 6 }}>
              {weekParam}
            </span>
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setWeek((w) => shiftIsoWeek(w, 1))}
            aria-label={t("agenda.next_week")}
            data-testid="agenda-week-next"
          >
            <ChevronRight size={14} strokeWidth={2.5} />
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setWeek(currentIsoWeek())}
            data-testid="agenda-week-today"
          >
            {t("agenda.this_week")}
          </button>
          {/* Two questions the WEEK cannot answer, so they get their own
              buttons: "what is late, anywhere" and "what is coming after
              this week". Both counts are the server's. */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setOverdueOpen(true)}
            data-testid="agenda-overdue-open"
          >
            <AlarmClock size={14} strokeWidth={2.5} />
            {t("agenda.overdue_button", { count: counts?.overdue_all ?? 0 })}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setUpcomingOpen(true)}
            data-testid="agenda-upcoming-open"
          >
            <CalendarRange size={14} strokeWidth={2.5} />
            {t("agenda.upcoming_button", { count: counts?.upcoming ?? 0 })}
          </button>
        </div>
      </div>

      {/* Sprint 183 §4 — the reference's counted strip. Every number is
          the SERVER's, over the whole scope, and every chip filters. */}
      <WorkPlanStrip counts={counts} active={chip} onChange={setChip} />

      {/* Sprint 183 §4 — search + source, the reference's filter row.

          The reference has a third control, a Status dropdown, and it is
          not here: the strip above IS the status filter, and offering
          the same choice twice is the "one control, one question" rule
          this batch is written around.

          "Source" rather than the reference's "Type": Sprint 182
          measured that a ticket TYPE filter on a page holding two kinds
          of work silently emptied every extra work out of the week.
          Kept ours. */}
      <form className="filter-bar" onSubmit={(e) => e.preventDefault()}>
        <div className="filter-field search">
          <span className="filter-label">{t("common:search")}</span>
          <input
            className="filter-control"
            type="search"
            value={search}
            placeholder={t("agenda.search_placeholder")}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="agenda-search"
          />
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("agenda.filter_source")}</span>
          <select
            className="filter-control"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value as "" | WorkPlanKind)}
            data-testid="agenda-filter-kind"
          >
            <option value="">{t("agenda.all_sources")}</option>
            <option value="TICKET_SLOT">{t("agenda.source_ticket")}</option>
            <option value="EXTRA_WORK">{t("agenda.source_extra_work")}</option>
          </select>
        </div>
      </form>

      {/* Sprint 181 §8 — the undated work has a PLACE now.
          This was one muted sentence saying N items had no date. On
          crmtest that sentence stood for 43 of 70 live tickets: two
          thirds of the work admitted to and not shown, while six of the
          seven week columns underneath read "Nothing planned". A count
          is not somewhere to put something.
          It sits ABOVE the week, because unplanned work is what you deal
          with before you read a plan, and the action that moves a row
          out of here and into the week is on the row itself. */}
      {data && data.undated_entries.length > 0 && (
        <section
          className="card"
          data-testid="agenda-undated-lane"
          style={{ marginBottom: 18, padding: "16px 18px" }}
        >
          <div className="section-head-title" style={{ marginBottom: 4 }}>
            {t("agenda.undated_title")}
          </div>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("agenda.undated_desc")}
          </p>
          <BoundedList
            size="lg"
            count={data.undated_entries.length}
            ariaLabel={t("agenda.undated_title")}
            testIdPrefix="agenda-undated"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {data.undated_entries.map((entry) => (
                <UndatedRow
                  key={entry.key}
                  entry={entry}
                  busy={planningKey === entry.key}
                  onPlanToday={() => planForToday(entry)}
                />
              ))}
            </ul>
          </BoundedList>
          {data.truncated.undated_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", {
                count: data.limits.undated_entries,
              })}
            </p>
          )}
          {planError && (
            <div className="alert-error" role="alert">
              {planError}
            </div>
          )}
        </section>
      )}

      {/* A list that silently stops is the same defect as a count that
          describes one page — so when the bound bites, it says so. */}
      {data?.truncated.entries && (
        <p className="wp-notice" role="status" data-testid="agenda-truncated">
          {t("agenda.truncated_note", { count: data.limits.entries })}
        </p>
      )}

      {/* The empty state is about the whole PLAN, not about this week:
          a week with nothing in it is a normal week and gets seven
          empty columns, which is information. "No work assigned" is
          only true when there is nothing anywhere. */}
      {!loading && !error && planIsEmpty ? (
        <EmptyState
          icon={CalendarClock}
          title={t("agenda.empty_title")}
          description={t("agenda.empty_desc")}
          testId="agenda-empty"
        />
      ) : (
        <div className="agenda-week-grid" data-testid="agenda-week-grid">
          {groups.map((group) => (
            <WorkPlanDayColumn
              key={group.key}
              iso={group.key}
              isToday={group.key === todayKey}
              count={group.items.length}
            >
              {group.items.map((entry) => (
                <WorkPlanCard
                  key={entry.key}
                  entry={entry}
                  role={role}
                  locale={locale}
                  onComplete={() => setCompletionTarget(entry)}
                  onUnable={() => setUnableTarget(entry)}
                />
              ))}
            </WorkPlanDayColumn>
          ))}
        </div>
      )}

      {overdueOpen && data && (
        <EntryTableModal
          title={t("agenda.overdue_title")}
          description={t("agenda.overdue_desc")}
          rows={data.overdue_entries}
          truncated={data.truncated.overdue_entries}
          limit={data.limits.overdue_entries}
          emptyLabel={t("agenda.overdue_none")}
          dateColumnLabel={t("agenda.col_deadline")}
          showOverdueBy
          role={role}
          onClose={() => setOverdueOpen(false)}
          testId="agenda-overdue"
        />
      )}

      {upcomingOpen && data && (
        <EntryTableModal
          title={t("agenda.upcoming_title")}
          description={t("agenda.upcoming_desc")}
          rows={data.upcoming_entries}
          truncated={data.truncated.upcoming_entries}
          limit={data.limits.upcoming_entries}
          emptyLabel={t("agenda.upcoming_none")}
          dateColumnLabel={t("agenda.col_planned")}
          showOverdueBy={false}
          role={role}
          onClose={() => setUpcomingOpen(false)}
          testId="agenda-upcoming"
        />
      )}

      {completionTarget && completionTarget.ticket_id !== null && (
        <SlotCompletionDialog
          slot={{
            id: completionTarget.source_id,
            ticket_id: completionTarget.ticket_id,
          }}
          onCancel={() => setCompletionTarget(null)}
          onDone={handleCompletionDone}
        />
      )}

      <RejectReasonDialog
        open={unableTarget !== null}
        title={t("unable.dialog_title")}
        description={t("unable.dialog_desc")}
        placeholder={t("unable.dialog_placeholder")}
        confirmLabel={t("unable.dialog_confirm")}
        cancelLabel={t("common:cancel")}
        onCancel={() => setUnableTarget(null)}
        onConfirm={handleUnableConfirm}
      />
    </div>
  );
}

// The card, the placement marker and `detailPath` now live in
// `components/workplan/WorkPlanCard.tsx` — see Sprint 183 §3.

/**
 * Sprint 181 §8 — one row of the undated lane.
 *
 * Deliberately NOT `WorkPlanCard`. That card carries a planned window,
 * a time, an overdue marker and completion actions — every one of which
 * is about a job that HAS a date, and all of them would be blank or
 * meaningless here. A row in this lane needs three things: what it is,
 * where it is, and the one action that gets it out of this lane. The
 * sprint's own rule applies hardest here: if a control does not change
 * what somebody does next, it is not on this row.
 */
function UndatedRow({
  entry,
  busy,
  onPlanToday,
}: {
  entry: WorkPlanEntry;
  busy: boolean;
  onPlanToday: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const isTicket = entry.ticket_id !== null;
  return (
    <li
      className="wp-undated-row"
      data-testid={`agenda-undated-row-${entry.key}`}
    >
      <div className="wp-undated-row-main">
        <Link
          to={
            isTicket
              ? `/tickets/${entry.ticket_id}`
              : `/extra-work/${entry.extra_work_id}`
          }
        >
          {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
          {entry.title}
        </Link>
        <span className="muted small">
          {[entry.building_name, entry.customer_name]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      {/* Sprint 182 §3 — the SAME action on both kinds. A ticket writes
          its schedule, an extra work writes the provider's planned day;
          the row does not make the reader care which. */}
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={onPlanToday}
        disabled={busy}
        data-testid={`agenda-undated-plan-${entry.key}`}
      >
        {busy ? t("agenda.undated_planning") : t("agenda.undated_plan_today")}
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// The two "elsewhere" lists. Same table, two questions.
// ---------------------------------------------------------------------------
function EntryTableModal({
  title,
  description,
  rows,
  truncated,
  limit,
  emptyLabel,
  dateColumnLabel,
  showOverdueBy,
  role,
  onClose,
  testId,
}: {
  title: string;
  description: string;
  rows: WorkPlanEntry[];
  truncated: boolean;
  limit: number;
  emptyLabel: string;
  dateColumnLabel: string;
  showOverdueBy: boolean;
  role: Role | null;
  onClose: () => void;
  testId: string;
}) {
  const { t } = useTranslation(["staff_slots", "common", "create_ticket"]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid={`${testId}-modal`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
        paddingTop: "6vh",
        overflowY: "auto",
      }}
    >
      <div
        className="card"
        style={{
          width: "min(96vw, 1040px)",
          padding: 24,
          maxHeight: "85vh",
          overflowY: "auto",
        }}
      >
        <div className="section-head" style={{ marginBottom: 12 }}>
          <div>
            <span className="section-head-title">{title}</span>
            <div className="section-head-sub">{description}</div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            data-testid={`${testId}-close`}
          >
            {t("common:cancel")}
          </button>
        </div>
        {truncated && (
          <p className="wp-notice" role="status">
            {t("agenda.truncated_note", { count: limit })}
          </p>
        )}
        <BoundedList
          size="lg"
          count={rows.length}
          ariaLabel={title}
          testIdPrefix={testId}
          className="table-wrap"
          emptyState={<p className="muted">{emptyLabel}</p>}
        >
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                <th>{t("agenda.col_item")}</th>
                <th>{t("agenda.filter_source")}</th>
                <th>{t("common:customer")}</th>
                <th>{t("common:building")}</th>
                <th>{dateColumnLabel}</th>
                {showOverdueBy && <th>{t("agenda.col_overdue_by")}</th>}
                <th>{t("common:status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => {
                const to = detailPath(entry, role);
                return (
                  <tr key={entry.key} data-testid={`${testId}-row`}>
                    <td className="td-subject">
                      {to ? (
                        <Link to={to}>
                          {entry.ticket_no ? `#${entry.ticket_no} · ` : ""}
                          {entry.title}
                        </Link>
                      ) : (
                        <>
                          {entry.ticket_no ? `#${entry.ticket_no} · ` : ""}
                          {entry.title}
                        </>
                      )}
                    </td>
                    <td>
                      {entry.kind === "EXTRA_WORK"
                        ? t("agenda.source_extra_work")
                        : t("agenda.source_ticket")}
                    </td>
                    <td>{entry.customer_name ?? "—"}</td>
                    <td>{entry.building_name ?? "—"}</td>
                    <td className="td-date">
                      {showOverdueBy
                        ? entry.due_date
                          ? formatDay(entry.due_date)
                          : "—"
                        : entry.planned_start
                          ? formatDay(entry.planned_start)
                          : "—"}
                    </td>
                    {showOverdueBy && (
                      <td>
                        {entry.overdue_days !== null
                          ? t("agenda.overdue_days", {
                              count: entry.overdue_days,
                            })
                          : "—"}
                      </td>
                    )}
                    <td>
                      {entry.kind === "EXTRA_WORK" ? (
                        <StatusBadge
                          status={{ kind: "extra-work", value: entry.status }}
                          variant="cell"
                        />
                      ) : (
                        <SlotStatusBadge status={entry.status as SlotStatus} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </BoundedList>
      </div>
    </div>
  );
}
