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
import { useEffect, useMemo, useState, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlarmClock,
  CalendarClock,
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Lock,
  SlidersHorizontal,
  Ticket,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { setTicketSchedule, updateStaffSlot } from "../api/admin";
import type { SlotStatus } from "../api/admin";
import { getApiError } from "../api/client";
import { bulkTriageTickets, listAllTickets, type TicketTriageAction } from "../api/tickets";
import { transitionExtraWork } from "../api/extraWork";
import type { Role, TicketList } from "../api/types";
import { getWorkPlan, planExtraWorkForDate } from "../api/workPlan";
import type {
  WorkPlanEntry,
  WorkPlanKind,
  WorkPlanPart,
  WorkPlanResponse,
} from "../api/workPlan";
import { useAuth } from "../auth/AuthContext";
import {
  agendaShowsTeamWeek,
  canAccessAgenda,
  canManageTimesheets,
} from "../auth/permissions";
import { BoundedList } from "../components/BoundedList";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { MultiSelectToolbar } from "../components/MultiSelectToolbar";
// Sprint 183 — the week's three pieces, extracted. This file was 1334
// lines holding a role dispatcher, a manager table, the week, the card,
// the placement marker and two modals; the card and the column are the
// two the sprint rebuilds, and they are easier to reason about with a
// file each than as two of six things in one.
import {
  EntryStatusBadge,
  FactsList,
  WorkPlanCard,
} from "../components/workplan/WorkPlanCard";
import { cardFacts } from "../components/workplan/cardFacts";
import {
  dedupeByJob,
  detailPath,
  entryLabel,
  formatDay,
  partHostDays,
} from "../components/workplan/entryHelpers";
import { PlanItDialog } from "../components/workplan/PlanItDialog";
import type { PlanItChoice } from "../components/workplan/PlanItDialog";
import { PlanManyDialog } from "../components/workplan/PlanManyDialog";
import type { PlanManyResult } from "../components/workplan/PlanManyDialog";
import { ZoneStrip } from "../components/workplan/ZoneStrip";
import "../components/workplan/workplan-zones.css";
import { CHIPS, FOLDED_KEYS, matchesChip } from "../components/workplan/chips";
import { latenessOf, sortLate } from "../components/workplan/lateness";
import { LateBadge, LateStrip } from "../components/workplan/LateStrip";
import { PartChips } from "../components/workplan/PartChips";
import { WorkPlanDayColumn } from "../components/workplan/WorkPlanDayColumn";
import { WorkPlanStrip } from "../components/workplan/WorkPlanStrip";
import type { ChipKey } from "../components/workplan/chips";
import { ExtraWorkOriginPill } from "../components/ExtraWorkOriginPill";
import { PageHeader } from "../components/PageHeader";
import { RejectReasonDialog } from "../components/RejectReasonDialog";
import { SlotStatusBadge } from "../components/SlotStatusBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { formatDate, localeCode } from "../lib/intl";
import { shortDay } from "../lib/shortDate";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  isoWeekStart,
  parseIsoWeek,
  plannedDayIso,
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

// P-10 A3 — a strip shows this many rows before "Show all N".
const STRIP_ROWS = 8;


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
  const { t, i18n } = useTranslation(["staff_slots", "common", "create_ticket"]);
  const { me } = useAuth();
  const { push } = useToast();
  const role = me?.role ?? null;
  const teamWeek = agendaShowsTeamWeek(role);

  /* FE-4 (Addendum D §D.12 item 1) — THE WEEK AND THE FILTERS ARE PART
     OF THE ADDRESS. "Back" from a ticket steps the history to this page,
     and a week or a filter kept in component state would be gone by
     then; in the URL (`?week=2026-W35&status=open&show=TICKET_SLOT&q=`)
     the page comes back exactly as it was left. `replace: true`, so
     flipping through weeks does not fill the history. */
  const [searchParams, setSearchParams] = useSearchParams();
  const setParam = (key: string, value: string) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (value) params.set(key, value);
        else params.delete(key);
        return params;
      },
      { replace: true },
    );
  };
  const week: IsoWeek = useMemo(
    () => parseIsoWeek(searchParams.get("week") ?? "") ?? currentIsoWeek(),
    [searchParams],
  );
  const setWeek = (next: IsoWeek | ((w: IsoWeek) => IsoWeek)) => {
    const value = typeof next === "function" ? next(week) : next;
    setParam("week", formatIsoWeek(value));
  };
  const [data, setData] = useState<WorkPlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const chipParam = searchParams.get("status") ?? "";
  const chip: ChipKey = CHIPS.some((c) => c.key === chipParam)
    ? (chipParam as ChipKey)
    : "";
  const setChip = (next: ChipKey) => setParam("status", next);
  const kindParam = searchParams.get("show") ?? "";
  const kindFilter: "" | WorkPlanKind =
    kindParam === "TICKET_SLOT" || kindParam === "EXTRA_WORK" ? kindParam : "";
  const setKindFilter = (next: "" | WorkPlanKind) => setParam("show", next);
  /** Sprint 183 §4 — the reference's "search by title or description".
   *
   *  Client-side, and honestly so: the week's entries are a BOUNDED,
   *  complete set (the response says through `truncated` when they are
   *  not), so filtering them here narrows exactly what is on screen. The
   *  CHIPS stay server counts — they describe the whole scope, which no
   *  amount of client filtering can know. A search box that quietly
   *  moved the chip numbers would be the defect Sprint 179A removed. */
  const search = searchParams.get("q") ?? "";
  const setSearch = (next: string) => setParam("q", next);
  const [overdueOpen, setOverdueOpen] = useState(false);
  /** T2-3 — the "YYYY-MM-DD" whose day is open full-width, or null. The
   *  DAY KEY rather than the group object: `groups` is rebuilt whenever a
   *  filter or the week changes, and holding the object would pin a
   *  stale row set open behind the user's own filtering. */
  const [dayModal, setDayModal] = useState<string | null>(null);
  const [upcomingOpen, setUpcomingOpen] = useState(false);
  const [completionTarget, setCompletionTarget] = useState<WorkPlanEntry | null>(
    null,
  );
  const [unableTarget, setUnableTarget] = useState<WorkPlanEntry | null>(null);
  /** Treatment 1 — the "can't complete" failure, shown in its own modal. */
  const [unableError, setUnableError] = useState("");
  /* P-9 §A.1 — "Plan it": the one button on a "Not planned yet" row
     opens a small dialog with today pre-filled (never writes today
     blind). `planTarget` is the row being planned; `planBusy` /
     `planError` belong to that dialog. */
  const [planTarget, setPlanTarget] = useState<WorkPlanEntry | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  /* P-10 A5 — "Plan N": the selected rows the one dialog plans. */
  const [planMany, setPlanMany] = useState<WorkPlanEntry[] | null>(null);
  /* P-11 F — "Show all N" opens the zone's OWN list: the strip
     expands to every row (bounded by scroll), never the old table
     modal. The modal stays for the day and Overdue doors, which are a
     different question. */
  const [stripAll, setStripAll] = useState<Record<string, boolean>>({});
  const toggleStripAll = (id: string) =>
    setStripAll((current) => ({ ...current, [id]: !current[id] }));
  /* P-6 V4 — stale-work triage. Select rows in the "Not planned yet"
     drawer, then park or close them with ONE reason, through the
     existing transitions (`/tickets/bulk-triage/` walks the machine's
     own legs; a meerwerk is cancelled through its own transition with
     the same reason as an override). Per-item results are reported. */
  const [triageMode, setTriageMode] = useState(false);
  const [triageSelected, setTriageSelected] = useState<Set<string>>(() => new Set());
  const [triageAction, setTriageAction] = useState<TicketTriageAction | null>(null);
  const [triageBusy, setTriageBusy] = useState(false);
  const [triageReport, setTriageReport] = useState<{
    ok: number;
    skipped: number;
    failed: { label: string; error: string }[];
  } | null>(null);

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

  /** P-10 A6 — reload and RESOLVE once the new payload is on screen, so
   *  a caller can toast AFTER the strip count and the board changed:
   *  the three agree in the same render. */
  async function refetch() {
    try {
      const payload = await getWorkPlan(weekParam, teamWeek);
      setData(payload);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  /** P-10 A5 — after one Save of "Plan N": reload first, then say what
   *  happened. Refused rows stay in the dialog (and selected) with their
   *  reason on the row; saved rows have already left the strip. */
  async function handlePlanManySaved(result: PlanManyResult) {
    await refetch();
    const names = result.refused.map((row) => row.label).join(", ");
    const title =
      result.planned > 0
        ? t("agenda.plan_many_saved", { count: result.planned })
        : t("agenda.plan_many_none_saved");
    push({
      title: result.refused.length > 0 ? `${title} ${t("agenda.plan_many_refused", { names })}` : title,
      variant: result.refused.length > 0 ? "info" : "success",
    });
    if (result.refused.length === 0) {
      setPlanMany(null);
      triageExit();
    } else {
      const keep = new Set(result.refused.map((row) => row.key));
      setTriageSelected((prev) => new Set([...prev].filter((key) => keep.has(key))));
    }
  }

  /** P-9 §A.1 — plan an undated row on the day (and time) the operator
   *  chose in the Plan-it dialog. A ticket writes its schedule (and,
   *  ticked by default, moves everyone on it — ruling 12(e)); an extra
   *  work writes the provider's planned day. */
  async function planEntry(entry: WorkPlanEntry, choice: PlanItChoice) {
    setPlanBusy(true);
    setPlanError("");
    try {
      if (entry.ticket_id !== null) {
        // P-3 §A.3 — a DAY, not a moment, unless a time was chosen: a
        // naive local instant the server reads in ITS zone.
        await setTicketSchedule(entry.ticket_id, {
          scheduled_start_at: choice.time
            ? `${choice.day}T${choice.time}:00`
            : plannedDayIso(choice.day),
          apply_to_slots: choice.applyToSlots,
        });
      } else if (entry.extra_work_id !== null) {
        await planExtraWorkForDate(entry.extra_work_id, choice.day);
      } else {
        return;
      }
      // A6 — the reload lands BEFORE the toast, so the strip count, the
      // board and the toast agree in the same render.
      await refetch();
      setPlanTarget(null);
      push({
        title: t("agenda.plan_it_saved", { date: shortDay(choice.day, localeCode(), todayKey) }),
        variant: "success",
      });
    } catch (err) {
      // Surfaced in the dialog, never swallowed.
      setPlanError(getApiError(err));
    } finally {
      setPlanBusy(false);
    }
  }

  /** W24-FX1 §2b — the undated lane, one row per JOB.
   *
   *  The server's ticket source is one row per ASSIGNED PERSON, so a
   *  ticket with two staff on it arrives twice (see `dedupeByJob`). The
   *  week grid below keeps both — each person has their own card. This
   *  lane must not: its one action writes the ticket's schedule, so the
   *  second row is the same button against the same record. */
  const undatedJobs = useMemo(
    () =>
      data
        ? // FE-4 — oldest first: the row that has waited longest is the
          // one to deal with first.
          [...dedupeByJob(data.undated_entries)].sort(
            (a, b) => (b.unplanned_age_days ?? 0) - (a.unplanned_age_days ?? 0),
          )
        : [],
    [data],
  );
  const undatedOldest = undatedJobs[0]?.unplanned_age_days ?? null;
  // P-7 S8 — parked work: out of the nag, its own quiet list in the
  // drawer, with the reason each was parked for.
  const parkedJobs = useMemo(
    () => (data ? dedupeByJob(data.parked_entries ?? []) : []),
    [data],
  );
  const parkedShown =
    data && !data.truncated.parked_entries ? parkedJobs.length : (data?.counts.parked ?? 0);

  function triageToggle(key: string) {
    setTriageSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function triageExit() {
    setTriageMode(false);
    setTriageSelected(new Set());
    setTriageAction(null);
  }

  async function runTriage(reason: string) {
    if (!triageAction || triageBusy) return;
    const chosen = undatedJobs.filter((entry) => triageSelected.has(entry.key));
    const tickets = chosen.filter((entry) => entry.ticket_id !== null);
    const extraWorks = chosen.filter(
      (entry) => entry.ticket_id === null && entry.extra_work_id !== null,
    );
    setTriageBusy(true);
    const failed: { label: string; error: string }[] = [];
    let ok = 0;
    let skipped = 0;
    const labelOf = (entry: WorkPlanEntry) =>
      entry.ticket_no ? `${entry.ticket_no} · ${entry.title}` : entry.title;
    try {
      if (tickets.length > 0) {
        const result = await bulkTriageTickets({
          ticket_ids: tickets.map((entry) => entry.ticket_id as number),
          action: triageAction,
          reason,
        });
        for (const item of result.results) {
          const entry = tickets.find((row) => row.ticket_id === item.id);
          if (item.ok) ok += 1;
          else failed.push({ label: entry ? labelOf(entry) : String(item.id), error: item.error ?? "generic" });
        }
      }
      if (triageAction === "park") {
        // A meerwerk has no parked state; it is skipped and said so.
        skipped = extraWorks.length;
      } else {
        for (const entry of extraWorks) {
          try {
            await transitionExtraWork(entry.extra_work_id as number, {
              to_status: "CANCELLED",
              note: reason,
              is_override: true,
              override_reason: reason,
            });
            ok += 1;
          } catch (err) {
            failed.push({ label: labelOf(entry), error: getApiError(err) });
          }
        }
      }
      setTriageReport({ ok, skipped, failed });
      push({
        title: t("agenda.triage_done", { ok, failed: failed.length }),
        variant: failed.length === 0 ? "success" : "info",
      });
      setTriageAction(null);
      setTriageSelected(new Set());
      await refetch();
    } catch (err) {
      push({ title: getApiError(err), variant: "error" });
    } finally {
      setTriageBusy(false);
    }
  }


  /** What the overview line says. The deduped count once the lane holds
   *  every row; the server's own count while the lane is bounded. */
  const undatedShown =
    data && !data.truncated.undated_entries
      ? undatedJobs.length
      : (data?.counts.undated ?? 0);

  /** WP-1 G1 — the follow-up list, one row per JOB for the same reason
   *  the undated lane dedupes: a person can hold several slots on one
   *  stuck ticket, and the list is about the job. */
  const stuckJobs = useMemo(
    () => (data ? dedupeByJob(data.stuck_entries) : []),
    [data],
  );
  /** P-3 §A.1 — work sent to the customer, one row per job. In the
   *  current week these are in NO column (rule 9); the chip is where
   *  they live. Browsing a past week they sit in their columns as
   *  history, so the chip is only offered on the working board. */
  const waitingJobs = useMemo(
    () => (data ? dedupeByJob(data.waiting_customer_entries) : []),
    [data],
  );
  const waitingShown =
    data && !data.truncated.waiting_customer_entries
      ? waitingJobs.length
      : (data?.counts.waiting_customer ?? 0);
  /** P-10 A2 — reported done, waiting for a manager's check, and not
   *  this viewer's to check (the server keeps the viewer's own on their
   *  today). One row per job. */
  const reviewJobs = useMemo(
    () => (data ? dedupeByJob(data.review_entries ?? []) : []),
    [data],
  );
  const reviewShown =
    data && !data.truncated.review_entries ? reviewJobs.length : (data?.counts.review ?? 0);
  /** The strip's one sentence: "reported done, not yet checked: Gökhan 2
   *  · Sophie 1 · oldest 6 days" — first names, counted over the loaded
   *  rows; a worker's strip says whose check it waits on. */
  const reviewSummary = useMemo(() => {
    if (!teamWeek) return t("agenda.strip_review_worker_summary");
    const byManager = new Map<string, number>();
    let oldest = 0;
    for (const entry of reviewJobs) {
      for (const name of entry.manager_names) {
        const first = name.split(" ")[0] || name;
        byManager.set(first, (byManager.get(first) ?? 0) + 1);
      }
      oldest = Math.max(oldest, entry.waiting_days ?? 0);
    }
    const managers = [...byManager.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([name, count]) => `${name} ${count}`)
      .join(" · ");
    return managers
      ? t("agenda.strip_review_summary", { managers, count: oldest })
      : t("agenda.strip_review_summary_plain", { count: oldest });
  }, [reviewJobs, teamWeek, t]);

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
  /** W-LATE §1a — the late strip's rows, one per job, through the ONE
   *  helper. The server already sorts them; `sortLate` re-applies the
   *  same key so the page never trusts an order it did not check. */
  const lateEntries = useMemo(
    () => (data ? sortLate(data.late_entries) : []),
    [data],
  );
  const needle = search.trim().toLowerCase();
  const counts = data?.counts ?? null;
  const todayKey = data?.today ?? toDateString(new Date());

  // P-2 §1 — TODAY IS ON SCREEN. The grid is 1530px wide and scrolls
  // inside its wrap; on a Saturday the viewport showed Mon-Fri and every
  // carried late job hung on the invisible Saturday column.
  //
  // P-14 A5 — and on a COLUMN BOUNDARY. Centring today cut Monday on
  // the left AND Sunday on the right at 1440: half a column on each
  // edge at first paint, which reads as a rendering fault (rule 7).
  // The wrap now opens at the EARLIEST column start that still shows
  // today in full — the left edge is always a whole column, today is
  // always visible, as much of the earlier week as fits is shown, and
  // the real scrollbar + edge shadows (W24-FX1) declare the rest.
  // `scroll-snap` in the CSS keeps hand scrolls on boundaries too.
  const weekScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const wrap = weekScrollRef.current;
    if (!wrap || !data) return;
    const today = wrap.querySelector<HTMLElement>('[data-testid="agenda-day-today"]');
    if (!today) return;
    const columns = Array.from(wrap.querySelectorAll<HTMLElement>(".wp-day"));
    if (columns.length === 0) return;
    const todayRight = today.offsetLeft + today.offsetWidth;
    const start =
      columns.find(
        (column) => todayRight - column.offsetLeft <= wrap.clientWidth,
      ) ?? today;
    // Relative to the first column, so a padding offset cannot bias a
    // board that needs no scrolling at all.
    wrap.scrollTo({
      left: Math.max(0, start.offsetLeft - columns[0].offsetLeft),
      behavior: "auto",
    });
  }, [data, todayKey]);

  // P-15 4.1 — NEVER A HALF COLUMN. The seven 210px-floor columns (the
  // owner rejected squeezing them twice) cannot all fit at 1440 with
  // the sidebar open, so the board scrolls — but the visible area now
  // ends on a COLUMN BOUNDARY: the scroller's width snaps down to the
  // largest whole number of columns that fits, so the right edge shows
  // a flush column and the scrollbar + W24-FX1 edge shadows (not a
  // clipped Saturday) say there is more. Recomputed on resize; phones
  // keep their single-column layout untouched.
  useEffect(() => {
    const wrap = weekScrollRef.current;
    if (!wrap || !data) return;
    const fit = () => {
      const grid = wrap.querySelector<HTMLElement>(".agenda-week-grid");
      const column = wrap.querySelector<HTMLElement>(".wp-day");
      if (!grid || !column) return;
      if (window.innerWidth < 768) {
        wrap.style.maxWidth = "";
        return;
      }
      const gap = parseFloat(getComputedStyle(grid).columnGap || "10") || 10;
      const step = column.offsetWidth + gap;
      const available = wrap.parentElement?.clientWidth ?? wrap.clientWidth;
      const whole = Math.max(1, Math.floor((available + gap) / step));
      wrap.style.maxWidth =
        whole >= 7 ? "" : `${Math.round(whole * step - gap)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
      wrap.style.maxWidth = "";
    };
  }, [data]);

  const filtered = useMemo(
    () =>
      entries.filter((entry) => {
        if (!matchesChip(entry, chip)) return false;
        // W-VIEWER — "Ticket" as a SOURCE covers both ticket shapes: the
        // JOB card a manager gets and the SLOT card a worker gets are the
        // same source seen from two sides, and a filter that dropped one
        // of them would empty the board for whichever reader is on the
        // other side.
        if (
          kindFilter === "TICKET_SLOT" &&
          entry.kind !== "TICKET_SLOT" &&
          entry.kind !== "TICKET"
        ) {
          return false;
        }
        if (kindFilter === "EXTRA_WORK" && entry.kind !== "EXTRA_WORK") {
          return false;
        }
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

  /** W-LATE §3b — a part with a window renders as its chip inside its
   *  day(s) under its ticket. The ticket's card hangs on one day; on
   *  every other day one of its parts covers, the column gets a HOST
   *  card (`WorkPlanCard hostParts`). Built here, once, from the same
   *  filtered list the columns render. */
  const groups = useMemo(() => {
    const hosts = new Map<string, { entry: WorkPlanEntry; parts: WorkPlanPart[] }[]>();
    // W-VIEWER §3 — HOST CARDS ARE THE WORKER'S SURFACE ONLY. A part's
    // window is a staffing fact, and spreading a job across the week by
    // its parts' days is exactly what the ruling forbids on the general
    // board: "assignment creation dates, manager assignment dates and
    // individual staff slot dates must never move the SA/PA/Manager job
    // card to another day". The parts still show, as chips, on the job's
    // own card.
    if (!teamWeek) {
      for (const entry of filtered) {
        for (const [day, parts] of partHostDays(entry, dayKeys)) {
          const bucket = hosts.get(day) ?? [];
          bucket.push({ entry, parts });
          hosts.set(day, bucket);
        }
      }
    }
    return dayKeys.map((key) => ({
      key,
      items: filtered.filter((entry) => entry.day === key),
      hosts: hosts.get(key) ?? [],
    }));
  }, [dayKeys, filtered, teamWeek]);

  /** The open day's CURRENT rows. Derived from `groups` rather than
   *  captured when the header was clicked, so a filter changed behind
   *  the modal is reflected in it — and a day filtered down to nothing
   *  closes it rather than showing rows that are no longer in scope. */
  const dayGroup = useMemo(
    () => (dayModal === null ? undefined : groups.find((g) => g.key === dayModal)),
    [dayModal, groups],
  );

  /** Nothing anywhere — not "nothing this week". The week's own
   *  emptiness is said by the seven day markers. */
  const planIsEmpty =
    counts !== null &&
    counts.total === 0 &&
    counts.overdue_all === 0 &&
    counts.upcoming === 0 &&
    counts.undated === 0 &&
    counts.late === 0;

  /** P-9 §A.1 — what the Filter fold holds that narrows the board, so
   *  a narrowed board never looks like a short one. */
  const activeFilterCount =
    (chip !== "" ? 1 : 0) + (kindFilter !== "" ? 1 : 0) + (needle ? 1 : 0);

  const weekRangeLabel = useMemo(() => {
    // P-14 (findings) — the LANGUAGE is a real dependency: i18n can
    // resolve NL after the first render, and this memo then kept
    // "Aug 31 – Sep 6" on a Dutch header until the week changed.
    const locale = i18n.language === "nl" ? "nl-NL" : "en-US";
    const days = isoWeekDays(week);
    return `${formatDate(toDateString(days[0]), locale)} – ${formatDate(
      toDateString(days[6]),
      locale,
    )}`;
  }, [week, i18n.language]);

  async function handleUnableConfirm(reason: string) {
    const entry = unableTarget;
    if (!entry || entry.ticket_id === null) return;
    // Treatment 1 — the dialog is dismissed only once the write LANDS.
    // It used to close on line two, before the await, so a rejected
    // "can't complete" threw away the reason the worker had just typed
    // and answered from a toast over a board that had not changed.
    setUnableError("");
    try {
      await updateStaffSlot(entry.ticket_id, entry.source_id, {
        slot_status: "UNABLE_TO_COMPLETE",
        unable_to_complete_reason: reason,
      });
      setUnableTarget(null);
      reload();
      push({ variant: "success", title: t("unable.toast_done") });
    } catch (err) {
      // `RejectReasonDialog` is shared and has no error slot; its
      // `description` IS in the open modal, which is where this belongs.
      setUnableError(getApiError(err));
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
        /* P-15 (P-14's S4 finding) — the title stops calling the whole
           team's week "My schedule" for a management reader; the
           subtitle already branched, the title now does too. */
        title={
          teamWeek ? t("agenda.page_title_team") : t("agenda.page_title")
        }
        subtitle={
          teamWeek ? t("agenda.page_subtitle_team") : t("agenda.page_subtitle")
        }
        /* P-13 W6 — the standing weekly pattern lost its toggle on the
           Hours page; its door for the people who manage it lives
           here, beside the week they are reading. P-14 A1 — it is the
           Agreed hours tab now. SA / CA only — the same gate the
           /admin/hours route enforces. */
        actions={
          canManageTimesheets(me?.role) ? (
            <Link
              to="/admin/hours/agreed"
              className="btn btn-ghost btn-sm"
              data-testid="agenda-schedule-link"
            >
              {t("common:contract_hours.tab")}
            </Link>
          ) : undefined
        }
      />

      {loading && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
          {/* P-15 (P-14's S3 finding) — the banner offers the way out;
              `reload()` is the machinery the page always had. */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginLeft: 12 }}
            onClick={reload}
            data-testid="agenda-retry"
          >
            {t("agenda.retry")}
          </button>
        </div>
      )}

      {/* P-10 A3 — THE PAGE IS THE BOARD; THE ZONES FOLD ABOVE IT. Every
          zone is a strip (`ZoneStrip`): one row, closed by default, the
          zone's colour, count · title · one summary sentence. A strip
          with count 0 does not render (§D.6 rule 13). Nothing renders
          before the server has answered (rule 10). Order: Not planned
          yet (amber) · Waiting for a manager's check (teal) · Waiting for
          the customer (violet) · Stuck (red) · the board. */}
      {data && undatedShown > 0 && (
        <ZoneStrip
          id="unplanned"
          tone="amber"
          count={undatedShown}
          title={t("common:phase.ew.WAITING_PLANNING")}
          summary={
            undatedOldest !== null && undatedOldest > 0
              ? t("agenda.strip_unplanned_summary", { count: undatedOldest })
              : t("agenda.strip_unplanned_summary_fresh")
          }
          testId="agenda-undated-lane"
          actions={
            <>
              {data.can_plan && undatedJobs.length > 0 && !triageMode && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setTriageMode(true)}
                  disabled={triageBusy}
                  data-testid="agenda-triage-toggle"
                >
                  {t("agenda.strip_select")}
                </button>
              )}
              {!triageMode && undatedJobs.length > STRIP_ROWS && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => toggleStripAll("unplanned")}
                  data-testid="agenda-undated-show-all"
                >
                  {stripAll.unplanned
                    ? t("agenda.strip_show_fewer")
                    : t("agenda.strip_show_all", { count: undatedShown })}
                </button>
              )}
            </>
          }
        >
          {/* P-10 A5 — Select → "N selected: Plan N · Put on hold · Close
              · Done". Selection exists only while the bar is up; every
              row is reachable while selecting. */}
          {triageMode && (
            <MultiSelectToolbar
              selectedCount={triageSelected.size}
              onSelectAll={() => setTriageSelected(new Set(undatedJobs.map((entry) => entry.key)))}
              onClearAll={() => setTriageSelected(new Set())}
              disabled={triageBusy}
              countLabel={t("agenda.select_count", { count: triageSelected.size })}
              actions={[
                {
                  key: "plan",
                  label: t("agenda.plan_n", { count: triageSelected.size }),
                  onClick: () =>
                    setPlanMany(undatedJobs.filter((entry) => triageSelected.has(entry.key))),
                  disabled: triageSelected.size === 0,
                  title: triageSelected.size === 0 ? t("agenda.triage_pick_first") : undefined,
                },
                {
                  key: "park",
                  label: t("agenda.triage_park"),
                  onClick: () => setTriageAction("park"),
                  disabled: triageSelected.size === 0,
                  title: triageSelected.size === 0 ? t("agenda.triage_pick_first") : t("agenda.triage_park_hint"),
                },
                ...(me?.role === "SUPER_ADMIN"
                  ? [
                      {
                        key: "close",
                        label: t("agenda.triage_close"),
                        onClick: () => setTriageAction("close"),
                        destructive: true,
                        disabled: triageSelected.size === 0,
                        title: triageSelected.size === 0 ? t("agenda.triage_pick_first") : t("agenda.triage_close_hint"),
                      },
                    ]
                  : []),
                {
                  key: "done",
                  label: t("agenda.select_done"),
                  onClick: triageExit,
                },
              ]}
              testIdPrefix="agenda-triage"
            />
          )}
          {triageReport && (
            <div
              className={triageReport.failed.length > 0 ? "alert-warning" : "alert-info"}
              role="status"
              data-testid="agenda-triage-report"
            >
              {t("agenda.triage_done", { ok: triageReport.ok, failed: triageReport.failed.length })}
              {triageReport.skipped > 0 && (
                <> {t("agenda.triage_skipped_ew", { count: triageReport.skipped })}</>
              )}
              {triageReport.failed.length > 0 && (
                <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {triageReport.failed.map((row) => (
                    <li key={`${row.label}-${row.error}`}>
                      {row.label} — {t([`agenda.triage_error_${row.error}`, "agenda.triage_error_generic"])}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }} data-testid="agenda-undated-rows">
            {(triageMode || stripAll.unplanned
              ? undatedJobs
              : undatedJobs.slice(0, STRIP_ROWS)
            ).map((entry) => (
              <ZoneRow
                key={entry.key}
                entry={entry}
                today={todayKey}
                role={role}
                testPrefix="agenda-undated"
                selectable={triageMode}
                selected={triageSelected.has(entry.key)}
                onToggleSelect={() => triageToggle(entry.key)}
                action={
                  data.can_plan ? (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => {
                        setPlanError("");
                        setPlanTarget(entry);
                      }}
                      data-testid={`agenda-undated-plan-${entry.key}`}
                    >
                      {t("agenda.plan_it")}
                    </button>
                  ) : null
                }
              />
            ))}
          </ul>
          {data.truncated.undated_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", { count: data.limits.undated_entries })}
            </p>
          )}
        </ZoneStrip>
      )}

      {/* P-10 A2 — reported done, waiting for a manager's check. For SA,
          a provider admin and a manager who is NOT responsible: this
          strip, its summary naming the managers it waits on. For the
          worker: "Reported done, waiting for the check" — never a
          column. The responsible manager's own rows are not here: they
          hang on their today as "Check: …" cards. */}
      {data && reviewShown > 0 && (
        <ZoneStrip
          id="review"
          tone="teal"
          count={reviewShown}
          title={teamWeek ? t("agenda.strip_review_title") : t("agenda.strip_review_worker_title")}
          summary={reviewSummary}
          testId="agenda-review-lane"
          actions={
            reviewJobs.length > STRIP_ROWS ? (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => toggleStripAll("review")}
                data-testid="agenda-review-show-all"
              >
                {stripAll.review
                  ? t("agenda.strip_show_fewer")
                  : t("agenda.strip_show_all", { count: reviewShown })}
              </button>
            ) : undefined
          }
        >
          <ul className={`wp-strip-list${stripAll.review ? " wp-strip-list-all" : ""}`}>
            {(stripAll.review ? reviewJobs : reviewJobs.slice(0, STRIP_ROWS)).map((entry) => (
              <ZoneRow key={entry.key} entry={entry} today={todayKey} role={role} testPrefix="agenda-review" />
            ))}
          </ul>
          {data.truncated.review_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", { count: data.limits.review_entries })}
            </p>
          )}
        </ZoneStrip>
      )}

      {/* P-9 §A.1 zone 2 → P-10 A3 strip — Waiting for the customer: one
          row per job, no action except Open; the reminder lives on the
          request. In no column of ANY week (rule 9). */}
      {data && waitingShown > 0 && (
        <ZoneStrip
          id="customer"
          tone="violet"
          count={waitingShown}
          title={t("agenda.strip_customer_title")}
          summary={t("agenda.strip_customer_summary")}
          testId="agenda-waiting-lane"
          actions={
            waitingJobs.length > STRIP_ROWS ? (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => toggleStripAll("customer")}
                data-testid="agenda-waiting-show-all"
              >
                {stripAll.customer
                  ? t("agenda.strip_show_fewer")
                  : t("agenda.strip_show_all", { count: waitingShown })}
              </button>
            ) : undefined
          }
        >
          <ul className={`wp-strip-list${stripAll.customer ? " wp-strip-list-all" : ""}`}>
            {(stripAll.customer ? waitingJobs : waitingJobs.slice(0, STRIP_ROWS)).map((entry) => (
              <ZoneRow key={entry.key} entry={entry} today={todayKey} role={role} testPrefix="agenda-waiting" />
            ))}
          </ul>
          {data.truncated.waiting_customer_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", { count: data.limits.waiting_customer_entries })}
            </p>
          )}
        </ZoneStrip>
      )}

      {/* WP-1 G1 — "Stuck — action needed", as a strip. Work that stopped
          without being done; a row leaves only when a human reschedules,
          reassigns or cancels through the existing actions on the record
          the title opens. Renders only when it holds something.
          P-14 A5 — the sentence is per VIEWER (the P-10 A2 rule): a
          worker can replan, reassign or cancel nothing, so their strip
          says who decides instead of listing verbs they do not have. */}
      {data && stuckJobs.length > 0 && (
        <ZoneStrip
          id="stuck"
          tone="red"
          count={data.counts.stuck}
          /* P-15 (P-14's S4 finding) — the worker's strip title stops
             pointing "actie nodig" at a reader whose body says the
             manager decides. */
          title={
            role === "STAFF"
              ? t("agenda.stuck_title_worker")
              : t("agenda.stuck_title")
          }
          summary={
            role === "STAFF"
              ? t("agenda.stuck_desc_worker")
              : t("agenda.stuck_desc")
          }
          testId="agenda-stuck-list"
        >
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {stuckJobs.slice(0, STRIP_ROWS).map((entry) => (
              <ZoneRow
                key={entry.key}
                entry={entry}
                today={todayKey}
                role={role}
                testPrefix="agenda-stuck"
                facts={false}
                action={
                  <span className="wp-stuck-age" data-testid={`agenda-stuck-age-${entry.key}`}>
                    {(entry.stuck_age_days ?? 0) === 0
                      ? t("agenda.stuck_age_today")
                      : t("agenda.stuck_age", { count: entry.stuck_age_days ?? 0 })}
                  </span>
                }
              />
            ))}
          </ul>
          {data.truncated.stuck_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", { count: data.limits.stuck_entries })}
            </p>
          )}
        </ZoneStrip>
      )}

      {/* P-9 §A.1 zone 3 / P-10 A3 — the week board is the first thing
          after the strips. Its header row holds the week stepper and ONE
          Filter button (P-2's fold rule): the counted status chips, the
          source select, the search box and the two "elsewhere" doors
          (late any week, planned later) live inside it. */}
      <div className="wp-board-head">
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
          data-testid="agenda-week-stepper"
        >
          <span className="hours-tiles-title">{t("agenda.week_title")}</span>
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
        </div>
      </div>
      <details
        className="filter-fold wp-filter"
        open={activeFilterCount > 0}
        data-testid="agenda-filter-fold"
      >
        <summary className="filter-fold-summary" data-testid="agenda-filter-toggle">
          <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
          {t("agenda.filter_label")}
          {activeFilterCount > 0 && (
            <span className="filter-fold-count">
              {t("agenda.filter_active", { count: activeFilterCount })}
            </span>
          )}
        </summary>
        <div className="filter-fold-body">
          {/* Sprint 183 §4 — the counted strip. Every number is the
              SERVER's, over the whole scope, and every chip filters. */}
          <WorkPlanStrip counts={counts} active={chip} onChange={setChip} />
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
              // FE-4 — the three status buckets that left the strip live
              // here, beside the source. One control: a status pick clears
              // the source and vice versa, and the strip's own three tiles
              // keep their server counts.
              value={
                FOLDED_KEYS.includes(chip) ? `status:${chip}` : kindFilter
              }
              onChange={(e) => {
                const value = e.target.value;
                if (value.startsWith("status:")) {
                  setKindFilter("");
                  setChip(value.slice("status:".length) as ChipKey);
                } else {
                  if (FOLDED_KEYS.includes(chip)) setChip("");
                  setKindFilter(value as "" | WorkPlanKind);
                }
              }}
              data-testid="agenda-filter-kind"
            >
              <option value="">{t("agenda.all_sources")}</option>
              <option value="TICKET_SLOT">{t("agenda.source_ticket")}</option>
              <option value="EXTRA_WORK">{t("agenda.source_extra_work")}</option>
              <optgroup label={t("agenda.filter_status_group")}>
                {CHIPS.filter((c) => FOLDED_KEYS.includes(c.key)).map((c) => (
                  <option key={c.key} value={`status:${c.key}`}>
                    {t(`agenda.${c.label}`)}
                    {counts ? ` (${c.count(counts)})` : ""}
                  </option>
                ))}
              </optgroup>
            </select>
          </div>
          {/* Two questions the WEEK cannot answer, so they get their own
              doors: "what is late, anywhere" and "what is coming after
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
      </details>

      {/* A list that silently stops is the same defect as a count that
          describes one page — so when the bound bites, it says so. */}
      {data?.truncated.entries && (
        <p className="wp-notice" role="status" data-testid="agenda-truncated">
          {t("agenda.truncated_note", { count: data.limits.entries })}
        </p>
      )}

      {/* P-6 V4 — one reason for every selected item; it lands in each
          item's history. */}
      <RejectReasonDialog
        open={triageAction !== null}
        title={
          triageAction === "close"
            ? t("agenda.triage_reason_title_close", { count: triageSelected.size })
            : t("agenda.triage_reason_title_park", { count: triageSelected.size })
        }
        description={t("agenda.triage_reason_desc")}
        placeholder={t("agenda.triage_reason_placeholder")}
        confirmLabel={
          triageBusy
            ? t("common:admin_form.saving")
            : triageAction === "close"
              ? t("agenda.triage_close")
              : t("agenda.triage_park")
        }
        cancelLabel={t("common:cancel")}
        onCancel={() => setTriageAction(null)}
        onConfirm={(reason) => void runTriage(reason)}
      />

      {/* The empty state is about the whole PLAN, not about this week:
          a week with nothing in it is a normal week and gets seven
          empty columns, which is information. "No work assigned" is
          only true when there is nothing anywhere. */}
      {!loading && !error && planIsEmpty ? (
        <EmptyState
          icon={CalendarClock}
          /* P-15 (P-14's S4 finding) — the TEAM week's empty state
             speaks team scope, not "when a manager assigns YOU…". */
          title={
            teamWeek ? t("agenda.empty_title_team") : t("agenda.empty_title")
          }
          description={
            teamWeek ? t("agenda.empty_desc_team") : t("agenda.empty_desc")
          }
          testId="agenda-empty"
        />
      ) : !data ? (
        /* P-4 (Part D) — THE FIRST PAINT IS HONEST. Before the week has
           answered, the board used to draw seven "Nothing planned"
           columns and em-dash tiles, and the "Waiting for customer"
           chip appeared only when the answer landed a second later —
           which the owner read as "missing until a second click"
           (probed on crmtest: the request is in flight, the board is
           lying). A loading week says it is loading; nothing claims
           to be empty until the server said so (§D.6 rule 10).

           P-15 (P-14's S3 finding) — and a FAILED load stops saying
           "Loading the week…" forever: the columns state the failure
           and hold the Retry door; nothing is in flight behind them. */
        <div className="agenda-week-scroll">
          <div
            className="agenda-week-grid"
            data-testid={error ? "agenda-week-failed" : "agenda-week-loading"}
          >
            {isoWeekDays(week).map((day) => (
              <div
                key={toDateString(day)}
                className="wp-day wp-day-loading"
                aria-busy={error ? undefined : true}
              >
                <div className="wp-day-head">
                  <span className="wp-day-name">
                    {day.toLocaleDateString(i18n.language, { weekday: "short" })}
                  </span>
                  <span className="wp-day-number">{day.getDate()}</span>
                </div>
                <div className="wp-day-body">
                  <div className="wp-day-empty muted small">
                    {error ? t("agenda.week_failed") : t("agenda.loading_week")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="agenda-week-scroll" ref={weekScrollRef}>
          <div className="agenda-week-grid" data-testid="agenda-week-grid">
          {groups.map((group) => (
            <WorkPlanDayColumn
              key={group.key}
              iso={group.key}
              isToday={group.key === todayKey}
              count={group.items.length + group.hosts.length}
              onOpen={
                group.items.length > 0
                  ? () => setDayModal(group.key)
                  : undefined
              }
            >
              {group.items.map((entry) => (
                <WorkPlanCard
                  key={entry.key}
                  entry={entry}
                  role={role}
                  today={todayKey}
                  onComplete={() => setCompletionTarget(entry)}
                  onUnable={() => setUnableTarget(entry)}
                />
              ))}
              {group.hosts.map((host) => (
                <WorkPlanCard
                  key={`host-${host.entry.key}`}
                  entry={host.entry}
                  role={role}
                  today={todayKey}
                  onComplete={() => setCompletionTarget(host.entry)}
                  onUnable={() => setUnableTarget(host.entry)}
                  hostParts={host.parts}
                />
              ))}
            </WorkPlanDayColumn>
          ))}
          </div>
        </div>
      )}

      {/* W-PLANTRUTH §1c — ONE late surface: three severity chips, each
          opening its group's modal. Under the board since P-10 A3 (the
          board is the first thing after the stepper); the numbers and
          the modals are unchanged. */}
      {data && (
        <LateStrip
          entries={lateEntries}
          truncated={data.truncated.late_entries}
          limit={data.limits.late_entries}
          role={role}
          onChanged={reload}
        />
      )}

      {/* P-7 S8 / P-10 A5 — "On hold (N)": the work somebody put on hold,
          quiet, with its reasons, under the board. `ticket_status.on_hold`'s
          own word; the page does not invent a second one. */}
      {data && parkedShown > 0 && (
        <details className="form-fold agenda-parked" data-testid="agenda-parked-fold">
          <summary className="form-fold-summary">
            {t("agenda.parked_title", { count: parkedShown })}
            <span className="form-fold-summary-value">{t("agenda.parked_hint")}</span>
          </summary>
          <BoundedList
            size="md"
            count={parkedJobs.length}
            ariaLabel={t("agenda.parked_title", { count: parkedShown })}
            testIdPrefix="agenda-parked"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {parkedJobs.map((entry) => (
                <li
                  key={entry.key}
                  className="wp-undated-row wp-undated-row--parked"
                  data-testid={`agenda-parked-row-${entry.key}`}
                >
                  <div className="wp-undated-row-main">
                    <Link to={`/tickets/${entry.ticket_id}`}>
                      {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
                      {entry.title}
                    </Link>
                    <span className="muted small">
                      {[entry.building_name, entry.customer_name].filter(Boolean).join(" · ")}
                    </span>
                    <span className="muted small" data-testid={`agenda-parked-reason-${entry.key}`}>
                      {entry.parked_reason
                        ? t("agenda.parked_reason", { reason: entry.parked_reason })
                        : t("agenda.parked_no_reason")}
                    </span>
                  </div>
                  <span className="wp-undated-row-actions">
                    <span className="cell-tag cell-tag-closed">
                      <i />
                      {t("agenda.parked_tag")}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </BoundedList>
          {data.truncated.parked_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", { count: data.limits.parked_entries })}
            </p>
          )}
        </details>
      )}

      {/* T2-3 — the day, full-width. Deliberately the SAME
          `EntryTableModal` the Overdue button already opens: the owner
          asked for the same rows, roomier, and a second modal
          implementation would be a second set of columns to keep in step
          with this one. Its date column is "Planned for" rather than
          "Deadline", and it never shows an overdue-by column, because
          within one day that number is the same for every row. */}
      {dayModal !== null && dayGroup !== undefined && (
        <EntryTableModal
          title={formatDay(dayModal)}
          description={t("agenda.day_count", { count: dayGroup.items.length })}
          rows={dayGroup.items}
          truncated={false}
          limit={0}
          emptyLabel={t("agenda.day_empty")}
          dateColumnLabel={t("agenda.col_planned")}
          showOverdueBy={false}
          role={role}
          onClose={() => setDayModal(null)}
          testId="agenda-day"
          // W-LATE §1b — TODAY's modal splits "planned today" from
          // "late": the late half is the strip's own rows, through the
          // same helper, so the two never disagree. Any other day has no
          // late half — the LAW says late work sits on today, not on the
          // day it was planned.
          lateRows={dayModal === todayKey ? lateEntries : undefined}
        />
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

      {/* P-9 §A.1 — "Plan it", keyed by the row so its state is that
          row's. Mounted only while open (a plain overlay, no <dialog>). */}
      {planTarget && (
        <PlanItDialog
          key={planTarget.key}
          entry={planTarget}
          todayIso={todayKey}
          busy={planBusy}
          error={planError}
          onCancel={() => {
            if (!planBusy) setPlanTarget(null);
          }}
          onSave={(choice) => void planEntry(planTarget, choice)}
        />
      )}

      {/* P-10 A5 — "Plan N": one dialog for the selection, keyed by it. */}
      {planMany && (
        <PlanManyDialog
          key={planMany.map((entry) => entry.key).join("|")}
          entries={planMany}
          todayIso={todayKey}
          onCancel={() => setPlanMany(null)}
          onSaved={handlePlanManySaved}
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
        description={unableError || t("unable.dialog_desc")}
        placeholder={t("unable.dialog_placeholder")}
        confirmLabel={t("unable.dialog_confirm")}
        cancelLabel={t("common:cancel")}
        onCancel={() => {
          setUnableError("");
          setUnableTarget(null);
        }}
        onConfirm={handleUnableConfirm}
      />
    </div>
  );
}

// The card, the placement marker and `detailPath` now live in
// `components/workplan/WorkPlanCard.tsx` — see Sprint 183 §3.

/**
 * P-10 A3/A4 — one row of a strip. What it is, where it is, the three
 * facts of its state (`cardFacts`, the same table the board's cards
 * read), and ONE action: Plan it on a "Not planned yet" row, Open
 * elsewhere, the stuck age on a stuck row. Deliberately not
 * `WorkPlanCard`: a row is read across, a card is read down.
 */
function ZoneRow({
  entry,
  today,
  role,
  testPrefix,
  action,
  facts = true,
  selectable = false,
  selected = false,
  onToggleSelect,
}: {
  entry: WorkPlanEntry;
  /** The server's today, the day the facts are decided against. */
  today: string;
  role: Role | null;
  testPrefix: string;
  /** The row's one action; `undefined` renders Open, `null` nothing. */
  action?: React.ReactNode;
  /** The stuck strip says its age instead of the facts. */
  facts?: boolean;
  /** P-6 V4 / P-10 A5 — selection, shown only while the bar is up. */
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const to = detailPath(entry, role);
  const where = [
    entry.building_name,
    entry.customer_name,
    entry.kind === "EXTRA_WORK" ? t("agenda.source_extra_work") : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const heading = entryLabel(entry);
  const lines = facts ? cardFacts(entry, today, t).lines : [];
  return (
    <li className="wp-undated-row" data-testid={`${testPrefix}-row-${entry.key}`}>
      {selectable && (
        <input
          type="checkbox"
          className="wp-undated-select"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={entry.ticket_no ?? entry.title}
          data-testid={`agenda-triage-select-${entry.key}`}
        />
      )}
      <div className="wp-undated-row-main">
        {to ? <Link to={to}>{heading}</Link> : <span>{heading}</span>}
        {/* P-11 A1 — where the job stands, under the title, on strip
            rows exactly as on cards. */}
        <EntryStatusBadge
          entry={entry}
          testId={`${testPrefix}-badge-${entry.key}`}
          className="wp-row-badge"
        />
        {where && <span className="muted small">{where}</span>}
        {lines.length > 0 && <FactsList lines={lines} testId={`${testPrefix}-facts-${entry.key}`} />}
      </div>
      <span className="wp-undated-row-actions">
        {action === undefined
          ? to && (
              <Link className="btn btn-ghost btn-sm" to={to} data-testid={`${testPrefix}-open-${entry.key}`}>
                {t("agenda.open")}
              </Link>
            )
          : action}
      </span>
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
  lateRows,
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
  /** W-LATE §1b — today's late half. Rendered as a second section under
   *  the day's own rows, each with the rung badge. Absent on any other
   *  day and on the Overdue / Upcoming tables. */
  lateRows?: WorkPlanEntry[];
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
        {lateRows !== undefined && (
          <div className="section-head-title" data-testid={`${testId}-planned-title`}>
            {t("late.day_planned_section", { count: rows.length })}
          </div>
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
                      {/* W-N1 §3 — the same chips the week card carries,
                          under the title rather than beside it: the day
                          modal's Item column is already the widest thing
                          in the row and a second inline run would push
                          the date column off a 1366 screen. */}
                      {entry.parts.length > 0 && (
                        <PartChips
                          parts={entry.parts}
                          testId={`${testId}-row-part`}
                        />
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
                      {/* W-VIEWER — three kinds, three status
                          vocabularies. A JOB row carries the TICKET's
                          status; a SLOT row the slot's. P-11 A1 — the
                          extra-work row's word is the list's phase, not
                          the old machine status ("Busy" and friends are
                          banned since P-10 B1). */}
                      {entry.kind === "EXTRA_WORK" ? (
                        <EntryStatusBadge entry={entry} />
                      ) : entry.kind === "TICKET" ? (
                        <StatusBadge
                          status={{ kind: "ticket", value: entry.status }}
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

        {/* W-LATE §1b — today's LATE half. The same helper that colours
            the strip decides the badge here, so the modal and the strip
            cannot disagree about a job. */}
        {lateRows !== undefined && (
          <div data-testid={`${testId}-late`} style={{ marginTop: 16 }}>
            <div className="section-head-title">
              {t("late.day_section", { count: lateRows.length })}
            </div>
            {lateRows.length === 0 ? (
              <p className="muted" data-testid={`${testId}-late-empty`}>
                {t("late.day_none")}
              </p>
            ) : (
              <BoundedList
                size="lg"
                count={lateRows.length}
                ariaLabel={t("late.strip_title")}
                testIdPrefix={`${testId}-late`}
                className="table-wrap"
              >
                <table className="data-table data-table-dense">
                  <thead>
                    <tr>
                      <th>{t("agenda.col_item")}</th>
                      <th>{t("common:building")}</th>
                      <th>{t("agenda.col_planned")}</th>
                      <th>{t("late.col_how_late")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lateRows.map((entry) => {
                      const to = detailPath(entry, role);
                      const facts = latenessOf(entry);
                      return (
                        <tr key={entry.key} data-testid={`${testId}-late-row`}>
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
                            {entry.parts.length > 0 && (
                              <PartChips
                                parts={entry.parts}
                                testId={`${testId}-late-row-part`}
                              />
                            )}
                          </td>
                          <td>{entry.building_name ?? "—"}</td>
                          <td className="td-date">
                            {facts?.plannedDate ? formatDay(facts.plannedDate) : "—"}
                          </td>
                          <td>
                            {facts && (
                              <LateBadge
                                facts={facts}
                                testId={`${testId}-late-row-badge`}
                              />
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </BoundedList>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
