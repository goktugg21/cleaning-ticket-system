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
import { Link } from "react-router-dom";
import axios from "axios";

import { getApiError } from "../../api/client";
import { setTicketSchedule, clearTicketSchedule } from "../../api/admin";
import { formatDate, formatDateTime } from "../../lib/intl";
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
// throughout, mirroring StaffSlotEditor's round-trip: the day the
// operator picked is the day stored and the day read back.
// ---------------------------------------------------------------------
function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function isoToTimeInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  // Midnight is what a date with no time looks like once it is stored
  // in a datetime column, so it reads back as an empty time box rather
  // than as "00:00" — which would be a time nobody typed.
  if (d.getHours() === 0 && d.getMinutes() === 0) return "";
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function inputsToIso(date: string, time: string): string | null {
  if (!date) return null;
  const d = new Date(`${date}T${time || "00:00"}:00`);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

/** A stored datetime shows its time only when somebody set one. */
function formatMoment(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.getHours() === 0 && d.getMinutes() === 0
    ? formatDate(iso)
    : formatDateTime(iso);
}

/** A plain ISO date ("2026-09-03") as the reader's date. */
function formatPlainDate(value: string | null | undefined): string {
  if (!value) return "";
  return formatDate(`${value}T00:00:00`);
}

/** Whole calendar days from start to end, both counted. */
function dayCount(startIso: string | null, endIso: string | null): number {
  if (!startIso || !endIso) return 0;
  const a = new Date(startIso);
  const b = new Date(endIso);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 0;
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((day(b) - day(a)) / 86_400_000);
  return diff < 0 ? 0 : diff + 1;
}

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
  const days = dayCount(ticket.scheduled_start_at, ticket.scheduled_end_at);

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
          return t("schedule.error_terminal");
        case "schedule_forbidden_scope":
          return t("schedule.error_forbidden_scope");
        case "schedule_forbidden_for_role":
          return t("schedule.error_forbidden_role");
        case "schedule_invalid":
          return t("schedule.error_invalid");
        default:
          break;
      }
    }
    return getApiError(err);
  }

  function openModal() {
    setStartDate(isoToDateInput(ticket.scheduled_start_at));
    setStartTime(isoToTimeInput(ticket.scheduled_start_at));
    setEndDate(isoToDateInput(ticket.scheduled_end_at));
    setEndTime(isoToTimeInput(ticket.scheduled_end_at));
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
    const movedFrom = ticket.scheduled_start_at;
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
      setResult(
        isPlanned && movedFrom
          ? t("schedule.result_moved", {
              from: formatMoment(movedFrom),
              to: formatMoment(startIso),
            })
          : endIso
            ? t("schedule.result_planned", {
                from: formatMoment(startIso),
                to: formatMoment(endIso),
              })
            : t("schedule.result_planned_single", {
                from: formatMoment(startIso),
              }),
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
  const hasAsked = Boolean(
    wantedDate || askedStart || askedEnd || deadline || committedStart,
  );

  const renderAsked = (testId: string) =>
    hasAsked ? (
      <div className="plan-asked" data-testid={testId}>
        <div className="plan-asked-head">{t("schedule.asked_heading")}</div>
        <div className="detail-kv-list">
          {wantedDate && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.asked_wanted_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-wanted">
                {formatPlainDate(wantedDate)}
              </span>
            </div>
          )}
          {askedStart && (
            <div className="detail-kv-row">
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
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.asked_deadline_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-deadline">
                {formatPlainDate(deadline)}
              </span>
            </div>
          )}
          {committedStart && origin && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.asked_committed_label")}
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
                <Link
                  to={`/extra-work/${origin.extra_work_request_id}`}
                  className="plan-asked-link"
                  data-testid="ticket-schedule-committed-link"
                >
                  {origin.extra_work_request_title}
                </Link>
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
        ticket.scheduled_start_at
          ? ticket.scheduled_end_at
            ? t("schedule.range", {
                from: formatMoment(ticket.scheduled_start_at),
                to: formatMoment(ticket.scheduled_end_at),
              })
            : formatMoment(ticket.scheduled_start_at)
          : t("schedule.not_scheduled")
      }
      // #110 Part A — default COLLAPSED like the other right-column
      // cards. No persistKey; remounts per ticket via the keyed wrapper.
      defaultOpen={false}
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
              {ticket.scheduled_start_at
                ? formatMoment(ticket.scheduled_start_at)
                : t("schedule.not_scheduled")}
            </span>
          </div>
          {ticket.scheduled_end_at && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.ends_label")}
              </span>
              <span className="detail-kv-val" data-testid="ticket-schedule-end">
                {formatMoment(ticket.scheduled_end_at)}
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
          {ticket.rescheduled_from && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.moved_from_label")}
              </span>
              <span
                className="detail-kv-val"
                data-testid="ticket-schedule-moved-from"
              >
                {formatMoment(ticket.rescheduled_from)}
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
