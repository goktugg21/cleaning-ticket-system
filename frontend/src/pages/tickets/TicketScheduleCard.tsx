// Sprint 1 (frontend) — operational "Scheduled date" control on the
// ticket detail. Surfaces the existing POST/DELETE
// /tickets/<id>/schedule/ action (Sprint 9B backend) as a
// set / change / clear control, for ALL ticket types.
//
// Provider-management ONLY (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER,
// `canManage`). STAFF + customer roles see the scheduled date READ-ONLY —
// no control, no network call (the backend would 403 them). The schedule
// itself is operational (no amounts) and visible to every role that sees
// the ticket detail; for a CUSTOMER_USER the backend already redacts the
// provider-internal reschedule audit fields.
//
// The backend is additive: scheduling never changes the workflow `status`
// and never disturbs SLA. `scheduled_start_at` is a DateTimeField on the
// wire — we send the picked calendar day as a full ISO-8601 datetime at
// local midnight (mirroring StaffSlotEditor's local-tz round-trip) rather
// than a bare date, which DateTimeField would reject. Changing an existing
// schedule REQUIRES a reason (backend stable code
// `reschedule_reason_required`); the first set does not.
import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Pencil, Plus, Trash2, X } from "lucide-react";
import axios from "axios";

import { getApiError } from "../../api/client";
import { setTicketSchedule, clearTicketSchedule } from "../../api/admin";
import type { TicketDetail, TicketStatus } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";

// Frontend mirror of the backend `_SCHEDULE_TERMINAL_STATUSES`. The
// schedule endpoint 400s (`schedule_not_allowed_terminal`) on these, so
// we hide the management affordances (the read-only date still renders).
const TERMINAL_SCHEDULE_STATUSES: ReadonlySet<TicketStatus> = new Set<
  TicketStatus
>(["APPROVED", "REJECTED", "CLOSED", "CONVERTED_TO_EXTRA_WORK"]);

// Read an ISO datetime back into a <input type="date"> value (local
// calendar day), so the prefill round-trips with `dateInputToIso`.
function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Convert a date-input value ("YYYY-MM-DD") to a full ISO-8601 datetime.
// Appending "T00:00:00" (no trailing Z) makes the Date constructor use
// the browser's local timezone, so the day the operator picked is the
// day stored — and is the same day `isoToDateInput` reads back.
function dateInputToIso(date: string): string | null {
  if (!date) return null;
  const d = new Date(`${date}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

// Date-only display (the time component is a fixed local midnight, so we
// never surface it). Locale-agnostic to match the page's other dates.
function formatScheduledDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
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

  const [editing, setEditing] = useState(false);
  const [dateValue, setDateValue] = useState("");
  const [windowLabel, setWindowLabel] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearRef = useRef<ConfirmDialogHandle>(null);
  const [clearBusy, setClearBusy] = useState(false);

  const isReschedule = ticket.schedule_status !== "UNSCHEDULED";
  const isTerminal = TERMINAL_SCHEDULE_STATUSES.has(ticket.status);
  const canEdit = canManage && !isTerminal;

  const statusLabel =
    ticket.schedule_status === "RESCHEDULED"
      ? t("schedule.status_rescheduled")
      : ticket.schedule_status === "SCHEDULED"
        ? t("schedule.status_scheduled")
        : t("schedule.status_unscheduled");

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

  function openEdit() {
    setDateValue(isoToDateInput(ticket.scheduled_start_at));
    setWindowLabel(ticket.time_window_label);
    setReason("");
    setError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setError(null);
  }

  async function handleSave() {
    const iso = dateInputToIso(dateValue);
    if (!iso) {
      setError(t("schedule.error_required"));
      return;
    }
    // Mirror the backend: changing an existing schedule needs a reason.
    if (isReschedule && !reason.trim()) {
      setError(t("schedule.error_reason_required"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setTicketSchedule(ticket.id, {
        scheduled_start_at: iso,
        time_window_label: windowLabel.trim(),
        reschedule_reason: isReschedule ? reason.trim() : "",
      });
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(mapError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleClearConfirm() {
    setClearBusy(true);
    setError(null);
    try {
      await clearTicketSchedule(ticket.id);
      clearRef.current?.close();
      await onChanged();
    } catch (err) {
      setError(mapError(err));
      clearRef.current?.close();
    } finally {
      setClearBusy(false);
    }
  }

  const saveDisabled =
    busy || !dateValue || (isReschedule && !reason.trim());

  return (
    <div className="card" data-testid="ticket-schedule-card">
      <div className="section-head">
        <div
          className="section-head-title"
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--text-faint)",
          }}
        >
          {t("schedule.card_title")}
        </div>
      </div>

      <div style={{ padding: "14px 18px 16px" }}>
        {/* Current value (read-only for everyone). */}
        <div
          className="detail-kv-list"
          data-testid="ticket-schedule-current"
          data-schedule-status={ticket.schedule_status}
        >
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("schedule.current_date_label")}
            </span>
            <span className="detail-kv-val" data-testid="ticket-schedule-date">
              <CalendarClock size={14} strokeWidth={2} />
              {ticket.scheduled_start_at
                ? formatScheduledDate(ticket.scheduled_start_at)
                : t("schedule.not_scheduled")}
            </span>
          </div>
          {ticket.time_window_label && (
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("schedule.window_label")}
              </span>
              <span className="detail-kv-val">{ticket.time_window_label}</span>
            </div>
          )}
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("schedule.status_label")}
            </span>
            <span
              className="detail-kv-val"
              data-testid="ticket-schedule-status"
            >
              {statusLabel}
            </span>
          </div>
        </div>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="ticket-schedule-error"
            style={{ marginTop: 10 }}
          >
            {error}
          </div>
        )}

        {/* Management affordances — provider-management only, and only
            while the ticket is not in a terminal status (the backend
            rejects scheduling a terminal ticket). STAFF / customer roles
            fall through to the read-only display above. */}
        {canEdit && !editing && (
          <div
            style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}
          >
            {isReschedule ? (
              <>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={openEdit}
                  data-testid="ticket-schedule-change-button"
                >
                  <Pencil size={13} strokeWidth={2} />
                  {t("schedule.change_button")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setError(null);
                    clearRef.current?.open();
                  }}
                  data-testid="ticket-schedule-clear-button"
                >
                  <Trash2 size={13} strokeWidth={2} />
                  {t("schedule.clear_button")}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={openEdit}
                data-testid="ticket-schedule-set-button"
              >
                <Plus size={14} strokeWidth={2.2} />
                {t("schedule.set_button")}
              </button>
            )}
          </div>
        )}

        {canEdit && editing && (
          <form
            data-testid="ticket-schedule-form"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSave();
            }}
            style={{ marginTop: 12 }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <strong className="small">
                {isReschedule
                  ? t("schedule.change_button")
                  : t("schedule.set_button")}
              </strong>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                aria-label={t("schedule.cancel_button")}
                onClick={cancelEdit}
                disabled={busy}
              >
                <X size={14} strokeWidth={2.2} />
              </button>
            </div>

            <div className="field" style={{ marginTop: 6 }}>
              <label className="field-label" htmlFor="ticket-schedule-date">
                {t("schedule.date_field_label")}
              </label>
              <input
                id="ticket-schedule-date"
                className="field-input"
                type="date"
                value={dateValue}
                onChange={(event) => setDateValue(event.target.value)}
                disabled={busy}
                data-testid="ticket-schedule-date-input"
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ticket-schedule-window">
                {t("schedule.window_field_label")}
              </label>
              <input
                id="ticket-schedule-window"
                className="field-input"
                type="text"
                maxLength={64}
                placeholder={t("schedule.window_field_placeholder")}
                value={windowLabel}
                onChange={(event) => setWindowLabel(event.target.value)}
                disabled={busy}
                data-testid="ticket-schedule-window-input"
              />
            </div>

            {/* Reason is mandatory only when changing an existing
                schedule — the backend enforces the same rule. */}
            {isReschedule && (
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
                  placeholder={t("schedule.reason_field_placeholder")}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  disabled={busy}
                  data-testid="ticket-schedule-reason-input"
                  required
                />
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={saveDisabled}
                data-testid="ticket-schedule-save-button"
              >
                {busy ? t("schedule.saving") : t("schedule.save_button")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={cancelEdit}
                disabled={busy}
                data-testid="ticket-schedule-cancel-button"
              >
                {t("schedule.cancel_button")}
              </button>
            </div>
          </form>
        )}
      </div>

      <ConfirmDialog
        ref={clearRef}
        title={t("schedule.clear_dialog_title")}
        body={t("schedule.clear_dialog_body")}
        confirmLabel={t("schedule.clear_confirm")}
        busyLabel={t("schedule.clearing")}
        onConfirm={handleClearConfirm}
        busy={clearBusy}
        destructive
      />
    </div>
  );
}
