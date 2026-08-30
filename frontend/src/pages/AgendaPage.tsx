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
  Hourglass,
  Lock,
  Ticket,
  Info,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { setTicketSchedule, updateStaffSlot } from "../api/admin";
import type { SlotStatus } from "../api/admin";
import { api, getApiError } from "../api/client";
import { listAllTickets } from "../api/tickets";
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
import {
  dedupeByJob,
  detailPath,
  formatDay,
  partHostDays,
} from "../components/workplan/entryHelpers";
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
import { formatDate } from "../lib/intl";
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

// WP-1 G2 — how old dateless work must be before the "Nog niet gepland"
// row starts saying so out loud (Addendum D §D.11.2: threshold 3 days).
const UNPLANNED_AGE_THRESHOLD_DAYS = 3;


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
  // Sprint 181 §8 — which undated row is being planned, and why the
  // last attempt failed. Keyed by entry rather than a bare boolean so
  // only the pressed button goes busy.
  const [planningKey, setPlanningKey] = useState<string | null>(null);
  const [planError, setPlanError] = useState("");
  /** FE-4 (Addendum D §D.12 item 5) — "Nog niet gepland" is a count-with-
   *  age BUTTON that opens the drawer; closed by default so it does not
   *  dominate the page. */
  const [undatedOpen, setUndatedOpen] = useState(false);
  /** P-3 §A.1 — the "Wacht op klant" drawer, the same door pattern as
   *  "Nog niet gepland": closed by default, one chip with the count. */
  const [waitingOpen, setWaitingOpen] = useState(false);
  /* P-4 (Part E) — the drawer acts. The row whose customer decision is
     being answered on their behalf, and the EXISTING override flow
     behind it: a required reason, `is_override`, the audit row —
     the same POST the ticket detail's Advanced fold sends. Offered
     only where the server said `can_override_customer_decision`. */
  const [approveTarget, setApproveTarget] = useState<WorkPlanEntry | null>(null);
  const [approveBusy, setApproveBusy] = useState(false);

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

  async function approveOnBehalf(entry: WorkPlanEntry, reason: string) {
    if (entry.ticket_id === null || approveBusy) return;
    setApproveBusy(true);
    try {
      await api.post(`/tickets/${entry.ticket_id}/status/`, {
        to_status: "APPROVED",
        is_override: true,
        override_reason: reason,
      });
      setApproveTarget(null);
      push({
        title: t("agenda.approve_on_behalf_done", { ticket: entry.ticket_no ?? entry.title }),
        variant: "success",
      });
      reload();
    } catch (err) {
      push({ title: getApiError(err), variant: "error" });
    } finally {
      setApproveBusy(false);
    }
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
      const today = new Date();
      if (entry.ticket_id !== null) {
        // P-3 §A.3 — a DAY, not a moment: a naive local midnight the
        // server reads in ITS zone (`plannedDayIso`). Noon used to hand
        // every job planned from here a "12:00" clock nobody chose.
        await setTicketSchedule(entry.ticket_id, {
          scheduled_start_at: plannedDayIso(toDateString(today)),
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
  // carried late job hung on the invisible Saturday column. After each
  // load of the current week the wrap scrolls so today's column is in
  // view (centred when the wrap is narrower than the week).
  const weekScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const wrap = weekScrollRef.current;
    if (!wrap || !data) return;
    const today = wrap.querySelector<HTMLElement>('[data-testid="agenda-day-today"]');
    if (!today) return;
    const left = today.offsetLeft - Math.max(0, (wrap.clientWidth - today.offsetWidth) / 2);
    wrap.scrollTo({ left: Math.max(0, left), behavior: "auto" });
  }, [data, todayKey]);

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

  const weekRangeLabel = useMemo(() => {
    const days = isoWeekDays(week);
    return `${formatDate(toDateString(days[0]))} – ${formatDate(
      toDateString(days[6]),
    )}`;
  }, [week]);

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
          {/* W24-FX1 §2b — the same number the lane below renders, not a
              second one. `counts.undated` is COUNT(*) over the server's
              slot rows, which are per-person, so it says 2 where the lane
              shows one two-person job. The server count stays the
              authority when the lane is TRUNCATED, because then the lane
              is a page and cannot answer "how many are there". */}
          {undatedShown > 0 && (
            <> · {t("agenda.overview_unplanned", { count: undatedShown })}</>
          )}
          {counts.overdue_all > 0 && (
            <> · {t("agenda.overview_overdue", { count: counts.overdue_all })}</>
          )}
          {/* W-LATE §1a — the strip's own number, said in the sentence
              that describes the plan. A late job is the one thing this
              line must not leave to be inferred. */}
          {counts.late > 0 && (
            <> · {t("agenda.overview_late", { count: counts.late })}</>
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
      {data && undatedJobs.length > 0 && (
        <div className="wp-undated-toggle-row" data-testid="agenda-undated-toggle-row">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            aria-expanded={undatedOpen}
            onClick={() => setUndatedOpen((open) => !open)}
            data-testid="agenda-undated-toggle"
          >
            <CalendarClock size={14} strokeWidth={2.5} />
            {t("agenda.undated_toggle", { count: undatedShown })}
            {undatedOldest !== null && undatedOldest >= UNPLANNED_AGE_THRESHOLD_DAYS && (
              <span className="wp-undated-toggle-age">
                {" · "}
                {t("agenda.undated_oldest", { count: undatedOldest })}
              </span>
            )}
          </button>
        </div>
      )}
      {data && undatedJobs.length > 0 && undatedOpen && (
        <section
          className="card"
          data-testid="agenda-undated-lane"
          style={{ marginBottom: 18, padding: "16px 18px" }}
        >
          <div className="section-head" style={{ marginBottom: 4 }}>
            <div className="section-head-title">{t("agenda.undated_title")}</div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setUndatedOpen(false)}
              data-testid="agenda-undated-hide"
            >
              {t("agenda.undated_hide")}
            </button>
          </div>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t(data.can_plan ? "agenda.undated_desc" : "agenda.undated_desc_readonly")}
          </p>
          <BoundedList
            size="lg"
            count={undatedJobs.length}
            ariaLabel={t("agenda.undated_title")}
            testIdPrefix="agenda-undated"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {undatedJobs.map((entry) => (
                <UndatedRow
                  key={entry.key}
                  entry={entry}
                  busy={planningKey === entry.key}
                  canPlan={data.can_plan}
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

      {/* P-3 §A.1 — "Wacht op klant". Sent to the customer, waiting on
          their answer: nothing for this reader to do, so not in a day
          column of the working week (a calm card in Tuesday's column
          read as "something is wrong with Tuesday"). One chip in its
          own calm colour, the same door as "Nog niet gepland". */}
      {data && data.week.is_current && waitingJobs.length > 0 && (
        <div className="wp-waiting-toggle-row" data-testid="agenda-waiting-toggle-row">
          <button
            type="button"
            className="btn btn-secondary btn-sm wp-waiting-toggle"
            aria-expanded={waitingOpen}
            onClick={() => setWaitingOpen((open) => !open)}
            data-testid="agenda-waiting-toggle"
          >
            <Hourglass size={14} strokeWidth={2.5} />
            {t("agenda.waiting_toggle", { count: waitingShown })}
          </button>
        </div>
      )}
      {data && data.week.is_current && waitingJobs.length > 0 && waitingOpen && (
        <section
          className="card"
          data-testid="agenda-waiting-lane"
          style={{ marginBottom: 18, padding: "16px 18px" }}
        >
          <div className="section-head" style={{ marginBottom: 4 }}>
            <div className="section-head-title">{t("agenda.waiting_title")}</div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setWaitingOpen(false)}
              data-testid="agenda-waiting-hide"
            >
              {t("agenda.waiting_hide")}
            </button>
          </div>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("agenda.waiting_desc")}
          </p>
          <BoundedList
            size="lg"
            count={waitingJobs.length}
            ariaLabel={t("agenda.waiting_title")}
            testIdPrefix="agenda-waiting"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {waitingJobs.map((entry) => (
                <WaitingRow
                  key={entry.key}
                  entry={entry}
                  role={role}
                  onApprove={entry.can_override_customer_decision ? setApproveTarget : undefined}
                />
              ))}
            </ul>
          </BoundedList>
          {data.truncated.waiting_customer_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", {
                count: data.limits.waiting_customer_entries,
              })}
            </p>
          )}
        </section>
      )}

      {/* WP-1 G1 — "Vastgelopen — actie nodig". Work that stopped
          without being done: somebody said "unable" and nobody is
          assigned any more, or an extra work whose ticket ended
          blocked. Blocked is not done — a row leaves this list only
          when a human reschedules, reassigns or cancels through the
          existing actions, which live one click away on the record
          itself. */}
      {data && stuckJobs.length > 0 && (
        <section
          className="card"
          data-testid="agenda-stuck-list"
          style={{ marginBottom: 18, padding: "16px 18px" }}
        >
          <div className="section-head-title" style={{ marginBottom: 4 }}>
            {t("agenda.stuck_title")}
          </div>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("agenda.stuck_desc")}
          </p>
          <BoundedList
            size="lg"
            count={stuckJobs.length}
            ariaLabel={t("agenda.stuck_title")}
            testIdPrefix="agenda-stuck"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {stuckJobs.map((entry) => (
                <StuckRow key={entry.key} entry={entry} role={role} />
              ))}
            </ul>
          </BoundedList>
          {data.truncated.stuck_entries && (
            <p className="wp-notice" role="status">
              {t("agenda.truncated_note", {
                count: data.limits.stuck_entries,
              })}
            </p>
          )}
        </section>
      )}

      {/* W-VIEWER §3 — WHAT THIS BOARD IS, said once, where it is read.
          The general plan places every job on the ticket's own scheduled
          date and shows it once however many people are on it. Each of
          those people may have been given a different working day, and
          those days are real — they are just not this board's subject.
          Saying so here is what stops the next reader concluding the
          board has lost somebody's assignment. */}
      {/* P-2 §1 — ONE short line is the page subtitle; the rest is one
          click away in a popover, not three stacked paragraphs. */}
      {teamWeek && (
        <details className="wp-info" data-testid="agenda-job-board-hint">
          <summary className="wp-info-summary">
            <Info size={14} strokeWidth={2.4} aria-hidden="true" />
            {t("agenda.info_toggle")}
          </summary>
          {/* P-3 §C.4 — ONE teaching line; the late strip's own sentence
              is its tooltip, not a second paragraph here. */}
          <div className="wp-info-body">
            <p>{t("agenda.job_board_hint")}</p>
          </div>
        </details>
      )}

      {/* A list that silently stops is the same defect as a count that
          describes one page — so when the bound bites, it says so. */}
      {data?.truncated.entries && (
        <p className="wp-notice" role="status" data-testid="agenda-truncated">
          {t("agenda.truncated_note", { count: data.limits.entries })}
        </p>
      )}

      {/* W-PLANTRUTH §1c — ONE late surface: three severity chips above
          the week grid, each opening its group's modal. The separate
          quarantine bar is gone — its three actions live on the NEVER
          DONE modal's rows, which is the only place they were ever
          needed. Nothing here scrolls sideways and the grid below keeps
          its own dimensions untouched. */}
      <RejectReasonDialog
        open={approveTarget !== null}
        onCancel={() => setApproveTarget(null)}
        onConfirm={(reason) => {
          if (approveTarget) void approveOnBehalf(approveTarget, reason);
        }}
        title={t("agenda.approve_on_behalf_title", {
          ticket: approveTarget?.ticket_no ?? approveTarget?.title ?? "",
        })}
        description={t("agenda.approve_on_behalf_desc")}
        placeholder={t("agenda.approve_on_behalf_placeholder")}
        confirmLabel={approveBusy ? t("common:admin_form.saving") : t("agenda.approve_on_behalf_confirm")}
        cancelLabel={t("common:cancel")}
      />
      {data && (
        <LateStrip
          entries={lateEntries}
          truncated={data.truncated.late_entries}
          limit={data.limits.late_entries}
          role={role}
          onChanged={reload}
        />
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
      ) : !data ? (
        /* P-4 (Part D) — THE FIRST PAINT IS HONEST. Before the week has
           answered, the board used to draw seven "Nothing planned"
           columns and em-dash tiles, and the "Waiting for customer"
           chip appeared only when the answer landed a second later —
           which the owner read as "missing until a second click"
           (probed on crmtest: the request is in flight, the board is
           lying). A loading week says it is loading; nothing claims
           to be empty until the server said so (§D.6 rule 10). */
        <div className="agenda-week-scroll">
          <div className="agenda-week-grid" data-testid="agenda-week-loading">
            {isoWeekDays(week).map((day) => (
              <div key={toDateString(day)} className="wp-day wp-day-loading" aria-busy="true">
                <div className="wp-day-head">
                  <span className="wp-day-name">
                    {day.toLocaleDateString(i18n.language, { weekday: "short" })}
                  </span>
                  <span className="wp-day-number">{day.getDate()}</span>
                </div>
                <div className="wp-day-body">
                  <div className="wp-day-empty muted small">{t("agenda.loading_week")}</div>
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
                  onComplete={() => setCompletionTarget(entry)}
                  onUnable={() => setUnableTarget(entry)}
                />
              ))}
              {group.hosts.map((host) => (
                <WorkPlanCard
                  key={`host-${host.entry.key}`}
                  entry={host.entry}
                  role={role}
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
  canPlan,
  onPlanToday,
}: {
  entry: WorkPlanEntry;
  busy: boolean;
  /** FE-5 step 0 — the server's `can_plan`. A viewer the schedule
   *  endpoints would refuse gets no button: a refusal in raw backend
   *  English can no longer be clicked into existence. */
  canPlan: boolean;
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
        {/* FE-4 (Addendum D §D.12 item 2) — the honest words: when it was
            created, and that it is not planned yet. Never "Gepland". */}
        {entry.created_at && (
          <span className="muted small" data-testid={`agenda-undated-created-${entry.key}`}>
            {/* P-1 — and WHO created it: nobody guesses who opened a ticket. */}
            {entry.created_by_name
              ? t("agenda.created_by_on", {
                  date: formatDay(entry.created_at.slice(0, 10)),
                  name: entry.created_by_name,
                })
              : t("agenda.created_on", { date: formatDay(entry.created_at.slice(0, 10)) })}
            {" · "}
            {t("agenda.not_planned_yet")}
          </span>
        )}
        {/* WP-1 G2 — dateless work never becomes overdue by design, so
            this is its only nag: how long it has sat here, said out
            loud once it is older than the threshold. */}
        {entry.unplanned_age_days !== null &&
          entry.unplanned_age_days >= UNPLANNED_AGE_THRESHOLD_DAYS && (
            <span
              className="wp-undated-age"
              data-testid={`agenda-undated-age-${entry.key}`}
            >
              {t("agenda.unplanned_age", {
                count: entry.unplanned_age_days,
              })}
            </span>
          )}
      </div>
      {/* Sprint 182 §3 — the SAME action on both kinds. A ticket writes
          its schedule, an extra work writes the provider's planned day;
          the row does not make the reader care which. */}
      {canPlan && (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onPlanToday}
          disabled={busy}
          data-testid={`agenda-undated-plan-${entry.key}`}
        >
          {busy ? t("agenda.undated_planning") : t("agenda.undated_plan_today")}
        </button>
      )}
    </li>
  );
}

/** WP-1 G1 — one stuck job. A READ row: the actions that empty this
 *  list (reschedule, reassign, cancel) are the existing ones on the
 *  record the title opens. */
function StuckRow({
  entry,
  role,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const to = detailPath(entry, role);
  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const heading = `${entry.ticket_no ? `${entry.ticket_no} · ` : ""}${entry.title}`;
  const age = entry.stuck_age_days ?? 0;
  return (
    <li className="wp-undated-row" data-testid={`agenda-stuck-row-${entry.key}`}>
      <div className="wp-undated-row-main">
        {to ? <Link to={to}>{heading}</Link> : <span>{heading}</span>}
        <span className="muted small">{where}</span>
        {/* P-3 §A.2 — the couldn't-complete reason is on the detail the
            title opens, not on the row: a raw "rrr" beside the job told
            the reader nothing and looked like a defect. */}
      </div>
      <span
        className="wp-stuck-age"
        data-testid={`agenda-stuck-age-${entry.key}`}
      >
        {age === 0
          ? t("agenda.stuck_age_today")
          : t("agenda.stuck_age", { count: age })}
      </span>
    </li>
  );
}

/** P-3 §A.1 — one job waiting on the customer. A READ row: what it is,
 *  where, when it went to the customer. The customer's answer is the
 *  only thing that moves it, and that is not this reader's button. */
function WaitingRow({
  entry,
  role,
  onApprove,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
  /** P-4 (Part E) — present only for a reader the server says may
   *  answer on the customer's behalf. One amber button; the existing
   *  override flow (reason, `is_override`, audit) behind it. */
  onApprove?: (entry: WorkPlanEntry) => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const to = detailPath(entry, role);
  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const heading = `${entry.ticket_no ? `${entry.ticket_no} · ` : ""}${entry.title}`;
  const since = entry.settled_at?.slice(0, 10) ?? entry.planned_end ?? entry.planned_start;
  return (
    <li className="wp-undated-row" data-testid={`agenda-waiting-row-${entry.key}`}>
      <div className="wp-undated-row-main">
        {to ? <Link to={to}>{heading}</Link> : <span>{heading}</span>}
        <span className="muted small">{where}</span>
        {since && (
          <span className="muted small" data-testid={`agenda-waiting-since-${entry.key}`}>
            {t("agenda.waiting_since", { date: formatDay(since) })}
          </span>
        )}
      </div>
      <span className="wp-undated-row-actions">
        <span className="wp-wait" data-waiting="customer">
          {t("agenda.waiting_customer")}
        </span>
        {/* P-5 S3.1 — a BUTTON, not a second pill: the amber
            `btn-warning` read as a status next to the waiting chip. */}
        {onApprove && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => onApprove(entry)}
            data-testid={`agenda-waiting-approve-${entry.key}`}
          >
            {t("agenda.approve_on_behalf")}
          </button>
        )}
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
                          status; a SLOT row the slot's. */}
                      {entry.kind === "EXTRA_WORK" ? (
                        <StatusBadge
                          status={{ kind: "extra-work", value: entry.status }}
                          variant="cell"
                        />
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
