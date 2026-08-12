// "My Work" — role-adaptive since Sprint 111. The `/agenda` route is
// auth-gated only, so this page dispatches on the caller's role:
//   - STAFF: the dated staff-slot agenda (unchanged). Caller-scoped: GET
//     /tickets/my-slots/ returns only the viewer's own dated slots. For
//     slots still ASSIGNED, staff can mark done (note/photo evidence) or
//     unable-to-complete (reason required). Staff never see schedule
//     editing here; rescheduling stays with managers, and slot completion
//     does NOT complete the ticket (manager double-check owns that).
//   - BUILDING_MANAGER: the caller's assigned tickets — the union of the
//     legacy primary-manager FK (Ticket.assigned_to) and the responsible-
//     manager M:N (TicketManagerAssignment) — via the ticket list
//     `?my_managed=1` filter. Read-only list; each row deep-links to the
//     ticket detail. Mirrors the CustomerTicketsPage table shape.
//   - SA / CA (and any role failing `canAccessAgenda`): a role-guard
//     empty state, NOT the staff-slot copy. The nav entry is already
//     hidden for them (permissions.ts::canAccessAgenda).
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CalendarClock,
  CheckCircle2,
  Lock,
  RefreshCw,
  Ticket,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { getMySlots, updateStaffSlot } from "../api/admin";
import type { MySlot } from "../api/admin";
import { getApiError } from "../api/client";
import { listAllTickets } from "../api/tickets";
import type { TicketList } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { agendaShowsTeamWeek, canAccessAgenda } from "../auth/permissions";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
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
  shiftIsoWeek,
  toDateString,
} from "../lib/isoWeek";
import type { IsoWeek } from "../lib/isoWeek";
import { SlotCompletionDialog } from "./SlotCompletionDialog";

const UNDATED = "__undated__";

function localDateKey(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

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
    return <ManagerTicketsAgenda />;
  }
  // canAccessAgenda guarantees the only remaining role here is STAFF.
  return <StaffSlotAgenda />;
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
// ---------------------------------------------------------------------------
function ManagerTicketsAgenda() {
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
    <div data-testid="agenda-manager-page">
      <PageHeader
        eyebrow={t("common:ops")}
        title={t("agenda.manager_title")}
        subtitle={t("agenda.manager_subtitle")}
      />

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

          <div className="table-wrap">
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
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// STAFF — the dated slot agenda. UNCHANGED from the pre-Sprint-111 page.
// ---------------------------------------------------------------------------
function StaffSlotAgenda() {
  const { t } = useTranslation(["staff_slots", "common", "create_ticket"]);
  const { me } = useAuth();
  const { push } = useToast();
  const locale = useLocaleCode();

  const [slots, setSlots] = useState<MySlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [chip, setChip] = useState<
    "" | "overdue" | "new" | "unable" | "completed"
  >("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [completionTarget, setCompletionTarget] = useState<MySlot | null>(null);
  const [unableTarget, setUnableTarget] = useState<MySlot | null>(null);

  async function reload() {
    const data = await getMySlots();
    setSlots(data);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        // A provider admin sees the TEAM's week; a worker sees
        // their own. The server decides whether to honour it.
        const data = await getMySlots(agendaShowsTeamWeek(me?.role));
        if (!cancelled) setSlots(data);
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
  }, [me?.role, refreshKey]);

  /**
   * Sprint 168 §7 — the Work Plan, built ON the agenda rather than
   * beside it.
   *
   * Sprint 167 measured this gap instead of guessing at it, and the
   * finding was that the agenda already had the CARDS, the actions and
   * the reason dialogs — what it did not have was a WEEK. So the cards
   * below are untouched; what is new is the frame around them, the
   * counts, and the filters.
   *
   * The day columns are Mon–Sun of the selected week AND they are
   * always all seven, empty ones included: a week with nothing on
   * Thursday must show an empty Thursday, not silently close the gap
   * and leave the reader counting columns.
   */
  const dayKeys = useMemo(
    () => isoWeekDays(week).map(toDateString),
    [week],
  );

  /** The week's slots, before any chip or filter narrows them. */
  const weekSlots = useMemo(
    () =>
      slots.filter((slot) => {
        const key = localDateKey(slot.scheduled_start_at);
        return key !== null && dayKeys.includes(key);
      }),
    [slots, dayKeys],
  );

  /** Undated slots belong to no week, so they are shown apart rather
   *  than dropped — a slot nobody has scheduled is exactly the one that
   *  most needs seeing. */
  const undatedSlots = useMemo(
    () => slots.filter((slot) => localDateKey(slot.scheduled_start_at) === null),
    [slots],
  );

  /** Overdue: a dated slot in the past that nobody has closed. The
   *  definition is stated here because everything on the screen keys
   *  off it — Sprint 167 flagged that it needed deciding before it
   *  was coded, and this is the decision. */
  const isOverdue = useMemo(() => {
    const today = toDateString(new Date());
    return (slot: MySlot) => {
      const key = localDateKey(slot.scheduled_start_at);
      if (key === null || key >= today) return false;
      return (
        slot.slot_status !== "COMPLETED" &&
        slot.slot_status !== "UNABLE_TO_COMPLETE"
      );
    };
  }, []);

  /** "10 – 16 aug 2026", the reference header's shape. */
  const todayKey = toDateString(new Date());

  /** How long a slot has been overdue, in whole days. The reference
   *  shows this and it is the only figure on the list that is not
   *  already on the card — "late" without "how late" does not rank. */
  function overdueByLabel(slot: MySlot): string {
    const key = localDateKey(slot.scheduled_start_at);
    if (key === null) return "—";
    const days = Math.round(
      (fromDateString(todayKey).getTime() - fromDateString(key).getTime()) /
        86_400_000,
    );
    return t("agenda.overdue_days", { count: Math.max(0, days) });
  }

  const weekRangeLabel = useMemo(() => {
    const days = isoWeekDays(week);
    return `${formatDate(toDateString(days[0]))} – ${formatDate(
      toDateString(days[6]),
    )}`;
  }, [week]);

  /** Every overdue slot the viewer holds, not only this week's — the
   *  Overdue button answers "what is late, anywhere", which is a
   *  different question from the week chip. */
  const overdueAll = useMemo(
    () => slots.filter(isOverdue),
    [slots, isOverdue],
  );

  const counts = useMemo(
    () => ({
      total: weekSlots.length,
      overdue: weekSlots.filter(isOverdue).length,
      new: weekSlots.filter((s) => s.slot_status === "ASSIGNED").length,
      // NOT "in progress": a staff slot has no such state. See the
      // note rendered under the chips.
      unable: weekSlots.filter((s) => s.slot_status === "UNABLE_TO_COMPLETE")
        .length,
      completed: weekSlots.filter((s) => s.slot_status === "COMPLETED").length,
    }),
    [weekSlots, isOverdue],
  );

  const filtered = useMemo(() => {
    let rows = weekSlots;
    if (chip === "overdue") rows = rows.filter(isOverdue);
    else if (chip === "new")
      rows = rows.filter((s) => s.slot_status === "ASSIGNED");
    else if (chip === "unable")
      rows = rows.filter((s) => s.slot_status === "UNABLE_TO_COMPLETE");
    else if (chip === "completed")
      rows = rows.filter((s) => s.slot_status === "COMPLETED");
    if (typeFilter) rows = rows.filter((s) => s.ticket_type === typeFilter);
    if (statusFilter) rows = rows.filter((s) => s.slot_status === statusFilter);
    return rows;
  }, [weekSlots, chip, typeFilter, statusFilter, isOverdue]);

  const groups = useMemo(
    () =>
      dayKeys.map((key) => ({
        key,
        items: filtered.filter(
          (slot) => localDateKey(slot.scheduled_start_at) === key,
        ),
      })),
    [dayKeys, filtered],
  );

  const ticketTypes = useMemo(
    () => [...new Set(slots.map((slot) => slot.ticket_type).filter(Boolean))],
    [slots],
  );

  function timeOnly(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  }

  function windowText(slot: MySlot): string {
    const parts: string[] = [];
    if (slot.scheduled_start_at) {
      parts.push(
        slot.scheduled_end_at
          ? `${timeOnly(slot.scheduled_start_at)}–${timeOnly(
              slot.scheduled_end_at,
            )}`
          : timeOnly(slot.scheduled_start_at),
      );
    }
    if (slot.time_window_label) parts.push(slot.time_window_label);
    return parts.length > 0 ? parts.join(" · ") : t("agenda.no_time");
  }

  function groupHeading(group: { key: string; items: MySlot[] }): string {
    if (group.key === UNDATED) return t("agenda.undated");
    // Sprint 168 §7 — from the COLUMN'S OWN date, not from its first
    // item. A day with nothing on it has no item to read a date from,
    // and every one of the seven columns is always rendered.
    return formatDate(`${group.key}T00:00:00`);
  }

  async function handleUnableConfirm(reason: string) {
    const slot = unableTarget;
    setUnableTarget(null);
    if (!slot || !me) return;
    try {
      await updateStaffSlot(slot.ticket_id, slot.id, {
        slot_status: "UNABLE_TO_COMPLETE",
        unable_to_complete_reason: reason,
      });
      await reload();
      push({ variant: "success", title: t("unable.toast_done") });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    }
  }

  async function handleCompletionDone() {
    setCompletionTarget(null);
    await reload();
    push({ variant: "success", title: t("complete.toast_done") });
  }

  return (
    <div data-testid="agenda-page">
      <PageHeader
        eyebrow={t("common:ops")}
        title={t("agenda.page_title")}
        subtitle={t("agenda.page_subtitle")}
      />

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

      {!loading && slots.length === 0 && !error && (
        <EmptyState
          icon={CalendarClock}
          title={t("agenda.empty_title")}
          description={t("agenda.empty_desc")}
          testId="agenda-empty"
        />
      )}

      {slots.length > 0 && (
        <>
          <div className="hours-tiles-head">
            <span className="hours-tiles-title">{t("agenda.week_title")}</span>
            <div
              style={{ display: "flex", alignItems: "center", gap: 8 }}
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
              {/* Sprint 171 §3 — the week RANGE, which is what the
                  reference header shows and what an operator reads.
                  "2026-W33" is precise and tells nobody which days. */}
              <span
                style={{ fontWeight: 600, minWidth: 210, textAlign: "center" }}
                data-testid="agenda-week-label"
              >
                {weekRangeLabel}
                <span className="muted small" style={{ marginLeft: 6 }}>
                  {formatIsoWeek(week)}
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
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setRefreshKey((n) => n + 1)}
                data-testid="agenda-refresh"
              >
                <RefreshCw size={14} strokeWidth={2.5} />
                {t("common:refresh")}
              </button>
              {/* Sprint 171 §3 — a separate Overdue BUTTON, as the
                  reference has, opening the list. The chip filters the
                  week; this answers "what is late, anywhere", which is
                  a different question and the reason the reference has
                  both. */}
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setOverdueOpen(true)}
                data-testid="agenda-overdue-open"
              >
                {t("agenda.overdue_button", { count: overdueAll.length })}
              </button>
            </div>
          </div>

          {/* The counts, and each one FILTERS when clicked — the Sprint
              163 status-strip behaviour, not a decorative badge row. */}
          <div className="composer-toggle" role="tablist" style={{ marginBottom: 12 }}>
            {(
              [
                ["", counts.total, "chip_total"],
                ["overdue", counts.overdue, "chip_overdue"],
                ["new", counts.new, "chip_new"],
                ["unable", counts.unable, "chip_unable"],
                ["completed", counts.completed, "chip_completed"],
              ] as const
            ).map(([key, value, label]) => (
              <button
                key={label}
                type="button"
                role="tab"
                aria-selected={chip === key}
                className={`composer-toggle-btn ${chip === key ? "active" : ""}`}
                onClick={() => setChip(key)}
                data-testid={`agenda-chip-${key || "total"}`}
              >
                {t(`agenda.${label}`)}
                <span className="mywork-chip-count">{value}</span>
              </button>
            ))}
          </div>

          <form className="filter-bar" onSubmit={(e) => e.preventDefault()}>
            <div className="filter-field">
              <span className="filter-label">{t("agenda.filter_type")}</span>
              <select
                className="filter-control"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                data-testid="agenda-filter-type"
              >
                <option value="">{t("agenda.all_types")}</option>
                {ticketTypes.map((value) => (
                  <option key={value} value={value}>
                    {TICKET_TYPE_KEYS[value as TicketTypeValue]
                      ? t(
                          `create_ticket:${TICKET_TYPE_KEYS[value as TicketTypeValue]}`,
                        )
                      : value}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">{t("agenda.filter_status")}</span>
              <select
                className="filter-control"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                data-testid="agenda-filter-status"
              >
                <option value="">{t("agenda.all_statuses")}</option>
                {["ASSIGNED", "COMPLETED", "UNABLE_TO_COMPLETE", "CANCELLED"].map(
                  (value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ),
                )}
              </select>
            </div>
          </form>

          {/* Said on screen rather than filled with an invented number:
              the reference's sixth chip is Archived, and a staff slot
              has no archived state in this system. */}
          <p className="muted small" data-testid="agenda-no-archived">
            {t("agenda.missing_chips_note")}
          </p>
        </>
      )}

      <div className="agenda-week-grid" data-testid="agenda-week-grid">
      {groups.map((group) => (
        <section
          key={group.key}
          /* Sprint 171 §3 — TODAY is marked, as the reference marks it.
             Seven identical columns give the reader nothing to anchor
             on, and "which one is today" is the first thing anybody
             looks for in a week view. */
          className={
            group.key === todayKey ? "agenda-day agenda-day-today" : "agenda-day"
          }
          data-testid={
            group.key === todayKey ? "agenda-day-today" : "agenda-day"
          }
          style={{ marginBottom: 18 }}
        >
          <h3
            className="section-head-title"
            style={{ marginBottom: 8 }}
            data-testid="agenda-group-heading"
          >
            {groupHeading(group)}
            {group.key === todayKey && (
              <span className="cell-tag cell-tag-open" style={{ marginLeft: 6 }}>
                {t("agenda.today")}
              </span>
            )}
          </h3>
          {/* An empty day gets a MARKER, not blank space: a column with
              nothing in it should say so, or the reader cannot tell it
              apart from one that failed to load. */}
          {group.items.length === 0 && (
            <p className="muted small" data-testid="agenda-day-empty">
              {t("agenda.day_empty")}
            </p>
          )}
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {group.items.map((slot) => (
              <li
                key={slot.id}
                className="card"
                data-testid="agenda-slot-card"
                style={{ padding: 12, marginBottom: 8 }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                  }}
                >
                  <Link
                    to={`/tickets/${slot.ticket_id}`}
                    className="td-subject"
                    style={{ fontWeight: 600 }}
                  >
                    {slot.ticket_no ? `#${slot.ticket_no} · ` : ""}
                    {slot.ticket_title}
                  </Link>
                  <SlotStatusBadge status={slot.slot_status} />
                </div>
                <div
                  className="muted small"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    marginTop: 4,
                  }}
                >
                  <CalendarClock size={13} strokeWidth={2} />
                  {windowText(slot)}
                  {slot.building_name ? ` · ${slot.building_name}` : ""}
                </div>
                {slot.assignment_note && (
                  <div className="small" style={{ marginTop: 4 }}>
                    {slot.assignment_note}
                  </div>
                )}
                {slot.slot_status === "COMPLETED" && slot.completion_note && (
                  <div className="muted small" style={{ marginTop: 4 }}>
                    {slot.completion_note}
                  </div>
                )}
                {slot.slot_status === "UNABLE_TO_COMPLETE" &&
                  slot.unable_to_complete_reason && (
                    <div className="muted small" style={{ marginTop: 4 }}>
                      {t("editor.unable_reason", {
                        reason: slot.unable_to_complete_reason,
                      })}
                    </div>
                  )}

                {slot.slot_status === "ASSIGNED" && (
                  <div
                    style={{ display: "flex", gap: 8, marginTop: 10 }}
                    data-testid="agenda-slot-actions"
                  >
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => setCompletionTarget(slot)}
                      data-testid="agenda-mark-done"
                    >
                      <CheckCircle2 size={14} strokeWidth={2} />
                      {t("agenda.mark_done")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setUnableTarget(slot)}
                      data-testid="agenda-mark-unable"
                    >
                      <XCircle size={14} strokeWidth={2} />
                      {t("agenda.cant_complete")}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      </div>

      {/* Undated slots belong to no week, so they sit below the grid
          rather than being dropped: a slot nobody has scheduled is the
          one that most needs seeing. */}
      {undatedSlots.length > 0 && (
        <p className="muted small" data-testid="agenda-undated-note">
          {t("agenda.undated_count", { count: undatedSlots.length })}
        </p>
      )}

      {/* Sprint 171 §3 — the overdue LIST, as the reference has it:
          per item the title, customer, building, the deadline, HOW LONG
          it has been overdue, its status and its type. */}
      {overdueOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("agenda.overdue_title")}
          data-testid="agenda-overdue-modal"
          onClick={(event) => {
            if (event.target === event.currentTarget) setOverdueOpen(false);
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
              width: "min(96vw, 980px)",
              padding: 24,
              maxHeight: "85vh",
              overflowY: "auto",
            }}
          >
            <div className="section-head" style={{ marginBottom: 12 }}>
              <span className="section-head-title">
                {t("agenda.overdue_title")}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setOverdueOpen(false)}
                data-testid="agenda-overdue-close"
              >
                {t("common:cancel")}
              </button>
            </div>
            <div className="table-wrap">
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("agenda.col_item")}</th>
                    <th>{t("common:customer")}</th>
                    <th>{t("common:building")}</th>
                    <th>{t("agenda.col_deadline")}</th>
                    <th>{t("agenda.col_overdue_by")}</th>
                    <th>{t("common:status")}</th>
                    <th>{t("agenda.filter_type")}</th>
                  </tr>
                </thead>
                <tbody>
                  {overdueAll.map((slot) => (
                    <tr key={slot.id} data-testid="agenda-overdue-row">
                      <td className="td-subject">
                        <Link to={`/tickets/${slot.ticket_id}`}>
                          #{slot.ticket_no} · {slot.ticket_title}
                        </Link>
                      </td>
                      <td>{slot.ticket_customer_name ?? "—"}</td>
                      <td>{slot.building_name}</td>
                      <td className="td-date">
                        {formatDate(slot.scheduled_start_at)}
                      </td>
                      <td>{overdueByLabel(slot)}</td>
                      <td>
                        <SlotStatusBadge status={slot.slot_status} />
                      </td>
                      <td>
                        {TICKET_TYPE_KEYS[slot.ticket_type as TicketTypeValue]
                          ? t(
                              `create_ticket:${TICKET_TYPE_KEYS[slot.ticket_type as TicketTypeValue]}`,
                            )
                          : slot.ticket_type}
                      </td>
                    </tr>
                  ))}
                  {overdueAll.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted">
                        {t("agenda.overdue_none")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {completionTarget && me && (
        <SlotCompletionDialog
          slot={completionTarget}
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
