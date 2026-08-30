// W-H — the Scheduling card.
//
// It used to hold four things: a single `Scheduled date`, a `Status`
// repeating what that date already said, a FREE-TEXT `Time window
// (optional)` and a `Reason for change`. Asked when a job starts, when
// it ends, how long it runs and who planned it, it could answer the
// first one.
//
// The other three answers were already in the response and unread:
//
//   * `scheduled_end_at` has been on the Ticket model, in the schedule
//     serializer and in the POST body since Sprint 9B. The form never
//     offered it, so the column was null on every ticket in the system.
//   * The parent Extra Work's dates have ridden on `extra_work_origin`
//     since Sprint 184 §1 — and `TicketExtraWorkOrigin` never declared
//     them, so no screen could read them.
//   * Who set the schedule has been on the `TicketStatusHistory`
//     annotation row since Sprint 9B, with no way to recognise the row.
//
// So nothing here is copied onto the ticket. The Extra Work owns the
// asked-for and committed dates and this card borrows them through the
// link the ticket already has; the ticket owns its own operational
// window; the history row owns who set it.
//
// THE FREE-TEXT WINDOW IS GONE. "Morning, 09:00-12:00" typed as prose
// could not be reported on, compared against worked hours, or handed to
// a worker in any structured form. `scheduled_start_at` and
// `scheduled_end_at` are DateTimeFields, so the window is now the times
// on the dates that already own them — no new column, and one fact in
// one place. A legacy label still shows while it exists, and the next
// save replaces it with real times.
//
// Provider-management ONLY (`canManage`) may set anything. STAFF and
// customer roles read the window; the backend redacts the
// provider-internal fields (`reschedule_reason`, `rescheduled_from`,
// `schedule_planned_by_name`) for a CUSTOMER_USER, and a role with no
// button gets no button at all rather than a disabled one.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, CalendarPlus, Pencil } from "lucide-react";
import axios from "axios";

import { getApiError } from "../../api/client";
import { setTicketSchedule, clearTicketSchedule } from "../../api/admin";
import { formatDate, formatDateTime } from "../../lib/intl";
import { plannedDayIso } from "../../lib/isoWeek";
import type { TicketDetail, TicketStatus } from "../../api/types";
import { CollapsibleCard } from "../../components/CollapsibleCard";

// Frontend mirror of the backend `_SCHEDULE_TERMINAL_STATUSES`. The
// schedule endpoint 400s (`schedule_not_allowed_terminal`) on these, so
// the button is absent (the read-out still renders).
const TERMINAL_SCHEDULE_STATUSES: ReadonlySet<TicketStatus> = new Set<
  TicketStatus
>(["APPROVED", "REJECTED", "CLOSED", "CONVERTED_TO_EXTRA_WORK"]);

// ---------------------------------------------------------------------
// Date <-> input plumbing.
//
// The stored value is a DateTimeField. The form splits it into a
// calendar day and a clock time so the operator picks each with the
// control built for it, and joins them back on save. Local time
// throughout, mirroring StaffAssignmentSection's round-trip: the day the
// operator picked is the day stored and the day read back.
// ---------------------------------------------------------------------
/* P-3 §A.3 — THE SERVER OWNS THE DAY AND THE CLOCK.
   The card used to take both off the stored instant in the BROWSER's
   zone: a date-only plan (stored as Amsterdam midnight) read as
   "01:00" from a browser three hours east, and as the previous day
   from one west of Greenwich. The detail now carries the day
   (`scheduled_start_day`, ISO) and the clock (`scheduled_start_time`,
   "HH:MM" or null) as the server states them, and the dialog sends a
   NAIVE local datetime back (`plannedDayIso`), which the server reads
   in its own zone. No `Date` arithmetic on either side. */

function inputsToIso(date: string, time: string): string | null {
  if (!date) return null;
  return plannedDayIso(date, time);
}

/** "27 aug 2026" or "27 aug 2026 09:30": a day, plus its clock only
 *  when the server says one exists. */
function momentText(day: string | null, clock: string | null): string {
  if (!day) return "";
  const date = formatPlainDate(day);
  return clock ? `${date} ${clock}` : date;
}

/** A plain ISO date ("2026-09-03") as the reader's date. */
/** Whole days from `from` to `to`, both YYYY-MM-DD, in local time. */
function daysAfter(from: string, to: string): number {
  const [fy, fm, fd] = from.split("-").map(Number);
  const [ty, tm, td] = to.split("-").map(Number);
  const a = new Date(fy, fm - 1, fd).getTime();
  const b = new Date(ty, tm - 1, td).getTime();
  return Math.max(0, Math.round((b - a) / 86400000));
}

function formatPlainDate(value: string | null | undefined): string {
  if (!value) return "";
  return formatDate(`${value}T00:00:00`);
}

/** Whole calendar days from start to end, both counted. */

export function TicketScheduleCard({
  ticket,
  canManage,
  onChanged,
}: {
  ticket: TicketDetail;
  canManage: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const { t } = useTranslation("ticket_detail");

  const [open, setOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Rule 4 — every action answers, in words. Cleared when the next one
  // starts, so it always describes the change the operator just made.
  const [result, setResult] = useState<string | null>(null);

  const isPlanned = ticket.schedule_status !== "UNSCHEDULED";
  const isTerminal = TERMINAL_SCHEDULE_STATUSES.has(ticket.status);
  const canEdit = canManage && !isTerminal;

  const origin = ticket.extra_work_origin;
  // P-5 S1.4 — meerwerk words on a meerwerk job.
  const kindContext = ticket.kind === "MEERWERK" ? "meerwerk" : undefined;
  // P-5 S1.2 — ONE STORY. The job's window is the resolved one
  // (`job_start_day` / `job_end_day`: the ticket's own days when a
  // person set them, else the meerwerk plan's first/last work day). A
  // customer's WISH is not a plan, so with `plan_source` CUSTOMER_WISH
  // the job reads "not planned yet" and the wish stays in "asked for".
  const fromMeerwerkPlan =
    !ticket.scheduled_start_day && ticket.plan_source === "PROVIDER_PLAN";
  const planStart = fromMeerwerkPlan
    ? ticket.job_start_day
    : (ticket.scheduled_start_day ?? null);
  const planEnd = fromMeerwerkPlan
    ? ticket.job_end_day
    : (ticket.scheduled_end_day ?? null);
  const planStartTime = ticket.scheduled_start_day ? ticket.scheduled_start_time : null;
  const planEndTime = ticket.scheduled_end_day ? ticket.scheduled_end_time : null;
  const days = planStart && planEnd ? daysAfter(planStart, planEnd) + 1 : 0;

  // Map the backend's stable schedule error codes to friendly i18n
  // copy; fall back to the generic API error otherwise. We match the
  // `code` field, never the human-readable `detail` string.
  function mapError(err: unknown): string {
    if (axios.isAxiosError(err)) {
      const code = (err.response?.data as { code?: string } | undefined)?.code;
      switch (code) {
        case "reschedule_reason_required":
          return t("schedule.error_reason_required");
        case "schedule_not_allowed_terminal":
          return t("schedule.error_terminal", { context: kindContext });
        case "schedule_forbidden_scope":
          return t("schedule.error_forbidden_scope", { context: kindContext });
        case "schedule_forbidden_for_role":
          return t("schedule.error_forbidden_role", { context: kindContext });
        case "schedule_invalid":
          return t("schedule.error_invalid");
        default:
          break;
      }
    }
    return getApiError(err);
  }

  function openModal() {
    // P-5 S1.1 — editing the meerwerk-derived window edits the SAME
    // plan: the dialog opens on it, and the save lands on both records
    // (`tickets/schedule.py` mirrors the window onto the meerwerk).
    setStartDate(planStart ?? "");
    setStartTime(planStartTime ?? "");
    setEndDate(planEnd ?? "");
    setEndTime(planEndTime ?? "");
    setReason("");
    setError(null);
    setResult(null);
    setConfirmClear(false);
    setOpen(true);
  }

  function closeModal() {
    setOpen(false);
    setConfirmClear(false);
    setError(null);
  }

  async function handleSave() {
    const startIso = inputsToIso(startDate, startTime);
    if (!startIso) {
      setError(t("schedule.error_required"));
      return;
    }
    const endIso = inputsToIso(endDate, endTime);
    // The server refuses an end before its start, and says so as a bare
    // English sentence rather than through the stable-code channel the
    // other five schedule errors use. Catching it here is what keeps
    // that sentence off a Dutch operator's screen; the server check is
    // still the one that decides.
    if (endIso && endIso < startIso) {
      setError(t("schedule.error_invalid"));
      return;
    }
    // Mirror the backend: changing an existing plan needs a reason.
    if (isPlanned && !reason.trim()) {
      setError(t("schedule.error_reason_required"));
      return;
    }
    const movedFrom = momentText(
      ticket.scheduled_start_day,
      ticket.scheduled_start_time,
    );
    setBusy(true);
    setError(null);
    try {
      await setTicketSchedule(ticket.id, {
        scheduled_start_at: startIso,
        scheduled_end_at: endIso,
        // The window is the times now. Sending it empty is what retires
        // a legacy label, in the same save that replaces it.
        time_window_label: "",
        reschedule_reason: isPlanned ? reason.trim() : "",
      });
      setOpen(false);
      const toText = momentText(startDate, startTime.trim() || null);
      const endText = momentText(endDate || null, endTime.trim() || null);
      setResult(
        isPlanned && movedFrom
          ? t("schedule.result_moved", { from: movedFrom, to: toText })
          : endIso
            ? t("schedule.result_planned", { from: toText, to: endText })
            : t("schedule.result_planned_single", { from: toText }),
      );
      await onChanged();
    } catch (err) {
      setError(mapError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setBusy(true);
    setError(null);
    try {
      await clearTicketSchedule(ticket.id);
      setOpen(false);
      setConfirmClear(false);
      setResult(t("schedule.result_cleared"));
      await onChanged();
    } catch (err) {
      setError(mapError(err));
    } finally {
      setBusy(false);
    }
  }

  // -------------------------------------------------------------------
  // What was asked for, and what was committed on the parent work.
  //
  // ONE renderer, used by the card and by the modal — rule 3 of this
  // wave is that the operator sees the customer's date exactly where
  // they set their own, and two copies of this block would be two
  // places to keep in step. Rows with no value do not render.
  // -------------------------------------------------------------------
  const wantedDate = ticket.customer_wanted_date;
  const askedStart = origin?.preferred_date ?? null;
  const askedEnd = origin?.planned_end_date ?? null;
  const deadline = origin?.deadline ?? null;
  const committedStart = origin?.provider_planned_date ?? null;
  const committedEnd = origin?.provider_planned_end_date ?? null;
  // P-5 S1.2 — a fact that only repeats the plan is not a second fact.
  // The wish and the requested period render only when they differ
  // from the plan; the meerwerk's committed window only when THIS job
  // holds a different date of its own (it kept it on a plan move) —
  // then it says what it is, in words.
  const sameAsPlan = (from: string | null, to: string | null) =>
    !!planStart && from === planStart && (to ?? from) === (planEnd ?? planStart);
  const showWanted = Boolean(wantedDate) && wantedDate !== planStart;
  const showAskedWindow = Boolean(askedStart) && !sameAsPlan(askedStart, askedEnd);
  const showCommitted =
    Boolean(committedStart && origin) && !sameAsPlan(committedStart, committedEnd);
  const hasAsked = Boolean(
    showWanted || showAskedWindow || deadline || showCommitted,
  );

  // W21 §3 — every row STACKS: label on its own line, value on its own
  // line, at every width. The kv grid puts label and value side by side
  // above 1100px, and a date range in the rail's narrow value column
  // wrapped mid-range (the owner's screenshot); an inline style wins
  // over the media query without touching the shared class. The title
  // link that shared the committed cell is DELETED, not restyled — the
  // job page needs no door to the request page, and the work's title
  // already heads this very page.
  const stackedRow = {
    display: "flex",
    flexDirection: "column",
    gap: 2,
  } as const;

  const renderAsked = (testId: string) =>
    hasAsked ? (
      <div className="plan-asked" data-testid={testId}>
        <div className="plan-asked-head">{t("schedule.asked_heading")}</div>
        <div className="detail-kv-list">
          {showWanted && (
            <div className="detail-kv-row" style={stackedRow}>
              <span className="detail-kv-label">
                {t("schedule.asked_wanted_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-wanted">
                {formatPlainDate(wantedDate)}
              </span>
            </div>
          )}
          {showAskedWindow && (
            <div className="detail-kv-row" style={stackedRow}>
              <span className="detail-kv-label">
                {t("schedule.asked_window_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-asked-window">
                {askedEnd
                  ? t("schedule.range", {
                      from: formatPlainDate(askedStart),
                      to: formatPlainDate(askedEnd),
                    })
                  : formatPlainDate(askedStart)}
              </span>
            </div>
          )}
          {deadline && (
            <div className="detail-kv-row" style={stackedRow}>
              <span className="detail-kv-label">
                {t("schedule.asked_deadline_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-deadline">
                {formatPlainDate(deadline)}
              </span>
            </div>
          )}
          {showCommitted && (
            <div className="detail-kv-row" style={stackedRow}>
              <span className="detail-kv-label">
                {t("schedule.meerwerk_plan_differs_label")}
              </span>
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-committed"
              >
                {committedEnd
                  ? t("schedule.range", {
                      from: formatPlainDate(committedStart),
                      to: formatPlainDate(committedEnd),
                    })
                  : formatPlainDate(committedStart)}
              </span>
              {/* W-FIX1 B3 (audit F15) — a commitment that ends after the
                  customer's deadline is allowed and FLAGGED, in the warn
                  tone; ticket 373 showed Aug 25–28 under "must be
                  finished by Aug 26" with nothing said. */}
              <span className="muted small">
                {t("schedule.meerwerk_plan_differs_hint")}
              </span>
            </div>
          )}
        </div>
      </div>
    ) : null;

  return (
    <CollapsibleCard
      title={t("schedule.card_title")}
      meta={
        planStart
          ? planEnd
            ? t("schedule.range", {
                from: momentText(planStart, planStartTime),
                to: momentText(planEnd, planEndTime),
              })
            : momentText(planStart, planStartTime)
          : t("schedule.not_scheduled")
      }
      // #110 Part A — default COLLAPSED like the other right-column
      // cards. No persistKey; remounts per ticket via the keyed wrapper.
      // W-PLAN2 Task 2 — open by default (Details + Activity are the
      // only cards that stay collapsed).
      defaultOpen
      testId="ticket-schedule-card"
    >
      <div style={{ padding: "14px 18px 16px" }}>
        <div
          className="detail-kv-list"
          data-testid="ticket-schedule-current"
          data-schedule-status={ticket.schedule_status}
        >
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("schedule.starts_label")}
            </span>
            <span className="detail-kv-val" data-testid="ticket-schedule-date">
              <CalendarClock size={14} strokeWidth={2} />
              {planStart
                ? momentText(planStart, planStartTime)
                : t("schedule.not_scheduled")}
            </span>
          </div>
          {/* P-5 S1.2 — where the window came from, when it is not the
              ticket's own: the meerwerk plan. One plan, said once. */}
          {fromMeerwerkPlan && planStart && (
            <div className="detail-kv-row">
              <span
                className="muted small"
                data-testid="ticket-schedule-source-meerwerk"
              >
                {t("schedule.source_meerwerk_plan")}
              </span>
            </div>
          )}
          {/* P-3 §A.5 — the plan's last day is past the deadline: stated,
              in the same tone the after-deadline commitment uses. */}
          {(ticket.planned_after_deadline ||
            (deadline && planEnd && planEnd > deadline)) && (
            <div className="detail-kv-row">
              <span
                className="detail-kv-val ew-hours-tone-over"
                data-testid="ticket-schedule-planned-after-deadline"
              >
                {t("facts.planned_after_deadline")}
                {deadline && planEnd && planEnd > deadline
                  ? ` — ${t("schedule.committed_after_deadline", {
                      count: daysAfter(deadline, planEnd),
                    })}`
                  : ""}
              </span>
            </div>
          )}
          {planEnd && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.ends_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-end">
                {momentText(planEnd, planEndTime)}
              </span>
            </div>
          )}
          {days > 0 && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.duration_label")}
              </span>
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-duration"
              >
                {t("schedule.duration_days", { count: days })}
              </span>
            </div>
          )}
          {ticket.schedule_planned_by_name && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.planned_by_label")}
              </span>
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-planned-by"
              >
                {ticket.schedule_planned_at
                  ? t("schedule.planned_by_value", {
                      name: ticket.schedule_planned_by_name,
                      when: formatDateTime(ticket.schedule_planned_at),
                    })
                  : ticket.schedule_planned_by_name}
              </span>
            </div>
          )}
          {ticket.rescheduled_from_day && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.moved_from_label")}
              </span>
              {/* P-5 S9.2 — the DAY, as the server states it (P-3 §A.3);
                  the raw instant read as the wrong day east of Greenwich. */}
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-moved-from"
              >
                {formatPlainDate(ticket.rescheduled_from_day)}
              </span>
            </div>
          )}
          {ticket.reschedule_reason && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.moved_reason_label")}
              </span>
              <span className="detail-kv-val">{ticket.reschedule_reason}</span>
            </div>
          )}
          {/* The retired free-text window, while a ticket still carries
              one. The next save writes real times and this row stops
              existing. */}
          {ticket.time_window_label && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.window_label")}
              </span>
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-legacy-window"
              >
                {ticket.time_window_label}
              </span>
            </div>
          )}
        </div>

        {renderAsked("ticket-schedule-asked")}

        {result && (
          <div
            className="alert-info"
            role="status"
            data-testid="ticket-schedule-result"
            style={{ marginTop: 10 }}
          >
            {result}
          </div>
        )}

        {error && !open && (
          <div
            className="alert-error"
            role="alert"
            data-testid="ticket-schedule-error"
            style={{ marginTop: 10 }}
          >
            {error}
          </div>
        )}

        {canEdit && (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={openModal}
              data-testid={
                isPlanned
                  ? "ticket-schedule-change-button"
                  : "ticket-schedule-set-button"
              }
            >
              {isPlanned ? (
                <Pencil size={13} strokeWidth={2} />
              ) : (
                <CalendarPlus size={14} strokeWidth={2.2} />
              )}
              {isPlanned
                ? t("schedule.change_button")
                : t("schedule.set_button")}
            </button>
          </div>
        )}
      </div>

      {/* The transition asks for what it needs before it happens, and
          the server enforces all three rules it asks about: a start is
          required, an end may not precede it (`schedule_invalid`), and
          changing an existing plan needs a reason
          (`reschedule_reason_required`).

          A plain overlay rather than a native <dialog>: this card lives
          inside a collapsible that unmounts, and an open <dialog> torn
          out of the DOM leaves the page inert (the Sprint 118
          frozen-screen bug). `open` gates the whole subtree, so closed
          means not rendered. */}
      {open && (
        <div
          className="plan-modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="ticket-schedule-modal"
        >
          <div className="plan-modal">
            {confirmClear ? (
              <>
                <h3 className="plan-modal-title">
                  {t("schedule.clear_dialog_title")}
                </h3>
                <div className="plan-modal-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setConfirmClear(false)}
                    disabled={busy}
                    data-testid="ticket-schedule-clear-back"
                  >
                    {t("schedule.clear_keep")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    onClick={() => void handleClear()}
                    disabled={busy}
                    data-testid="ticket-schedule-clear-confirm"
                  >
                    {busy ? t("schedule.clearing") : t("schedule.clear_confirm")}
                  </button>
                </div>
                {error && (
                  <div
                    className="alert-error"
                    role="alert"
                    data-testid="ticket-schedule-modal-error"
                  >
                    {error}
                  </div>
                )}
              </>
            ) : (
              <form
                data-testid="ticket-schedule-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleSave();
                }}
              >
                <h3 className="plan-modal-title">
                  {isPlanned
                    ? t("schedule.change_button")
                    : t("schedule.set_button")}
                </h3>

                {/* Rule 3 — the customer's date sits where the operator
                    sets theirs, so there is nothing to remember and
                    nothing to go and look up. */}
                {renderAsked("ticket-schedule-modal-asked")}

                <div className="plan-modal-grid">
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="ticket-schedule-start-date"
                    >
                      {t("schedule.starts_label")}
                    </label>
                    <input
                      id="ticket-schedule-start-date"
                      className="field-input"
                      type="date"
                      value={startDate}
                      onChange={(event) => setStartDate(event.target.value)}
                      disabled={busy}
                      data-testid="ticket-schedule-date-input"
                      required
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="ticket-schedule-start-time"
                    >
                      {t("schedule.start_time_label")}
                    </label>
                    <input
                      id="ticket-schedule-start-time"
                      className="field-input"
                      type="time"
                      value={startTime}
                      onChange={(event) => setStartTime(event.target.value)}
                      disabled={busy}
                      data-testid="ticket-schedule-start-time-input"
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="ticket-schedule-end-date"
                    >
                      {t("schedule.ends_label")}
                    </label>
                    <input
                      id="ticket-schedule-end-date"
                      className="field-input"
                      type="date"
                      value={endDate}
                      min={startDate || undefined}
                      onChange={(event) => setEndDate(event.target.value)}
                      disabled={busy}
                      data-testid="ticket-schedule-end-date-input"
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="ticket-schedule-end-time"
                    >
                      {t("schedule.end_time_label")}
                    </label>
                    <input
                      id="ticket-schedule-end-time"
                      className="field-input"
                      type="time"
                      value={endTime}
                      onChange={(event) => setEndTime(event.target.value)}
                      disabled={busy}
                      data-testid="ticket-schedule-end-time-input"
                    />
                  </div>
                </div>

                {/* P-3 §A.5 — PLAN-AFTER-DEADLINE WARNS, in plain words,
                    the moment the chosen day passes the deadline. Nothing
                    is blocked: the operator may know better, and the card
                    and the detail will say "planned after the deadline". */}
                {deadline && (endDate || startDate) > deadline && (
                  <div
                    className="alert-info"
                    role="status"
                    data-testid="ticket-schedule-deadline-warning"
                  >
                    {t("schedule.after_deadline_warning", {
                      date: formatPlainDate(deadline),
                    })}
                  </div>
                )}

                {isPlanned && (
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="ticket-schedule-reason"
                    >
                      {t("schedule.reason_field_label")}
                    </label>
                    <textarea
                      id="ticket-schedule-reason"
                      className="field-textarea"
                      rows={3}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      disabled={busy}
                      data-testid="ticket-schedule-reason-input"
                      required
                    />
                  </div>
                )}

                {error && (
                  <div
                    className="alert-error"
                    role="alert"
                    data-testid="ticket-schedule-modal-error"
                  >
                    {error}
                  </div>
                )}

                <div className="plan-modal-actions">
                  {isPlanned && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm plan-modal-clear"
                      onClick={() => {
                        setError(null);
                        setConfirmClear(true);
                      }}
                      disabled={busy}
                      data-testid="ticket-schedule-clear-button"
                    >
                      {t("schedule.clear_button")}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={closeModal}
                    disabled={busy}
                    data-testid="ticket-schedule-cancel-button"
                  >
                    {t("schedule.cancel_button")}
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={
                      busy || !startDate || (isPlanned && !reason.trim())
                    }
                    data-testid="ticket-schedule-save-button"
                  >
                    {busy ? t("schedule.saving") : t("schedule.save_button")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </CollapsibleCard>
  );
}
