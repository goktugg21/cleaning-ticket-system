import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { setTicketSchedule } from "../../api/admin";
import { api, getApiError } from "../../api/client";
import { transitionExtraWork } from "../../api/extraWork";
import type { Role, TicketStatusChangePayload } from "../../api/types";
import { planExtraWorkForDate } from "../../api/workPlan";
import type { WorkPlanEntry } from "../../api/workPlan";
import { canAccessExtraWork } from "../../auth/permissions";
import { toDateString } from "../../lib/isoWeek";
import { RejectReasonDialog } from "../RejectReasonDialog";
import { useToast } from "../ToastProvider";
import { detailPath, formatDay } from "./entryHelpers";
import { escalationStep, latenessOf, notifiedSentence } from "./lateness";

/**
 * W-LATE §1c — the quarantine bar.
 *
 * Renders ONLY when at least one job has crossed the L3 threshold:
 * thirty days past its anchor (the deadline, else the planned date) with
 * not one worked hour booked against it. There is no empty shell — a
 * bordeaux bar reading "nothing in quarantine" would be the banner
 * problem the week spent three sprints removing.
 *
 * Each row states the facts and nothing else: the planned date, how many
 * days past the anchor, "zonder één gewerkt uur", and WHEN the provider
 * admin was told, by name — pulled from the recipients the phase-2 sweep
 * actually reached, rendered "—" until it has. The name is a display
 * name resolved at render time; nothing here, and nothing on the server,
 * carries a person by id, name or address in code.
 *
 * Three actions. OPEN goes to the record. RESCHEDULE asks for the new
 * day and the reason and writes the ticket's schedule (or the extra
 * work's provider-planned day) through the same doors the undated lane
 * and the schedule card already use. CANCEL asks for a reason and closes
 * the job: an extra work through its own CANCELLED transition, a ticket
 * through the state machine's out-of-machine jump to CLOSED, which is a
 * SUPER_ADMIN-only override recorded with its reason — so the button is
 * offered to exactly the role the server admits, and to nobody else.
 */
export function QuarantineBar({
  entries,
  role,
  onChanged,
}: {
  /** ONLY the quarantined (L3) entries; the caller filters. */
  entries: WorkPlanEntry[];
  role: Role | null;
  onChanged: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();
  const [rescheduling, setRescheduling] = useState<WorkPlanEntry | null>(null);
  const [cancelling, setCancelling] = useState<WorkPlanEntry | null>(null);
  const [cancelError, setCancelError] = useState("");

  if (entries.length === 0) return null;

  function canCancel(entry: WorkPlanEntry): boolean {
    if (entry.kind === "EXTRA_WORK") return canAccessExtraWork(role);
    return role === "SUPER_ADMIN";
  }

  async function handleCancel(reason: string) {
    const entry = cancelling;
    if (!entry) return;
    setCancelError("");
    try {
      if (entry.kind === "EXTRA_WORK" && entry.extra_work_id !== null) {
        await transitionExtraWork(entry.extra_work_id, {
          to_status: "CANCELLED",
          note: reason,
        });
      } else if (entry.ticket_id !== null) {
        const payload: TicketStatusChangePayload = {
          to_status: "CLOSED",
          note: reason,
          is_override: true,
          override_reason: reason,
        };
        await api.post(`/tickets/${entry.ticket_id}/status/`, payload);
      } else {
        return;
      }
      setCancelling(null);
      push({ variant: "success", title: t("late.cancel_done") });
      onChanged();
    } catch (err) {
      // The dialog stays open with the refusal inside it, so the reason
      // already typed survives — the same rule the "can't complete"
      // dialog on this page follows.
      setCancelError(getApiError(err));
    }
  }

  return (
    <section
      className="wp-quarantine"
      data-testid="agenda-quarantine"
      aria-label={t("late.quarantine_title")}
    >
      <div className="wp-quarantine-head">
        <ShieldAlert size={16} strokeWidth={2.4} aria-hidden="true" />
        <span>{t("late.quarantine_title")}</span>
        <span className="wp-quarantine-count" data-testid="agenda-quarantine-count">
          {entries.length}
        </span>
        <span className="wp-quarantine-desc">{t("late.quarantine_desc")}</span>
      </div>
      <ul className="wp-quarantine-rows">
        {entries.map((entry) => {
          const facts = latenessOf(entry);
          if (!facts) return null;
          const to = detailPath(entry, role);
          const step = escalationStep(facts, "L3_QUARANTINE");
          const notified = step ? notifiedSentence(step.names, t) : "";
          const heading = `${entry.ticket_no ? `${entry.ticket_no} · ` : ""}${entry.title}`;
          const where = [entry.building_name, entry.customer_name]
            .filter(Boolean)
            .join(" · ");
          return (
            <li
              key={entry.key}
              className="wp-quarantine-row"
              data-testid="agenda-quarantine-row"
              data-job={
                entry.ticket_id !== null ? `ticket-${entry.ticket_id}` : entry.key
              }
            >
              <div className="wp-quarantine-main">
                {to ? <Link to={to}>{heading}</Link> : <span>{heading}</span>}
                {where && <span className="muted small">{where}</span>}
              </div>
              <div className="wp-quarantine-facts" data-testid="agenda-quarantine-facts">
                <span>
                  {facts.plannedDate
                    ? t("late.q_planned", { date: formatDay(facts.plannedDate) })
                    : t("late.badge_undated")}
                </span>
                {facts.deadline && (
                  <span>{t("late.q_deadline", { date: formatDay(facts.deadline) })}</span>
                )}
                <span>{t("late.q_days", { count: facts.anchorDays ?? 0 })}</span>
                <span className="wp-quarantine-nohours">{t("late.q_no_hours")}</span>
                <span data-testid="agenda-quarantine-notified">
                  {t("late.q_notified", {
                    who: notified || t("late.q_notified_none"),
                  })}
                  {step && (
                    <span className="muted"> · {formatDay(step.notified_at.slice(0, 10))}</span>
                  )}
                </span>
              </div>
              <div className="wp-quarantine-actions">
                {to && (
                  <Link
                    to={to}
                    className="btn btn-secondary btn-sm"
                    data-testid="agenda-quarantine-open"
                  >
                    {t("late.action_open")}
                  </Link>
                )}
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setRescheduling(entry)}
                  data-testid="agenda-quarantine-reschedule"
                >
                  {t("late.action_reschedule")}
                </button>
                {canCancel(entry) && (
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    onClick={() => {
                      setCancelError("");
                      setCancelling(entry);
                    }}
                    data-testid="agenda-quarantine-cancel"
                  >
                    {t("late.action_cancel")}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {rescheduling && (
        <RescheduleDialog
          key={rescheduling.key}
          entry={rescheduling}
          onCancel={() => setRescheduling(null)}
          onDone={() => {
            setRescheduling(null);
            push({ variant: "success", title: t("late.reschedule_done") });
            onChanged();
          }}
        />
      )}

      {/* Rendered unconditionally and driven by `open` — the shared
          dialog's own contract, and CLAUDE.md's rule for dialogs. */}
      <RejectReasonDialog
        open={cancelling !== null}
        title={t("late.cancel_title")}
        description={cancelError || t("late.cancel_desc")}
        placeholder={t("late.cancel_placeholder")}
        confirmLabel={t("late.cancel_confirm")}
        cancelLabel={t("common:cancel")}
        onCancel={() => {
          setCancelError("");
          setCancelling(null);
        }}
        onConfirm={handleCancel}
      />
    </section>
  );
}

/**
 * The reschedule door: a day and, for a ticket that already has a
 * schedule, the reason the schedule endpoint has required since Sprint
 * 9B. A plain overlay, conditionally mounted, like the assign dialog —
 * not a native `<dialog>`.
 */
function RescheduleDialog({
  entry,
  onCancel,
  onDone,
}: {
  entry: WorkPlanEntry;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [date, setDate] = useState(() => toDateString(new Date()));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isTicket = entry.ticket_id !== null;
  const ready = date !== "" && (!isTicket || reason.trim() !== "");

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      if (isTicket && entry.ticket_id !== null) {
        // Local noon, for the reason the undated lane's "plan for today"
        // gives: midnight is the one value that lands on the previous
        // day once it is stored in UTC.
        const [year, month, day] = date.split("-").map(Number);
        const at = new Date(year, month - 1, day, 12, 0, 0, 0);
        await setTicketSchedule(entry.ticket_id, {
          scheduled_start_at: at.toISOString(),
          reschedule_reason: reason.trim(),
        });
      } else if (entry.extra_work_id !== null) {
        await planExtraWorkForDate(entry.extra_work_id, date);
      }
      onDone();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("late.reschedule_title")}
      data-testid="agenda-reschedule-dialog"
    >
      <div className="card ew-plan-dialog">
        <h3 className="section-title ew-plan-dialog-title">
          {t("late.reschedule_title")}
        </h3>
        <p className="muted small">
          {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
          {entry.title}
        </p>
        <p className="muted small">{t("late.reschedule_desc")}</p>
        <div className="field">
          <label className="field-label" htmlFor="agenda-reschedule-date">
            {t("late.reschedule_date")}
          </label>
          <input
            id="agenda-reschedule-date"
            type="date"
            className="filter-control"
            value={date}
            disabled={busy}
            onChange={(event) => setDate(event.target.value)}
            data-testid="agenda-reschedule-date"
          />
        </div>
        {isTicket && (
          <div className="field">
            <label className="field-label" htmlFor="agenda-reschedule-reason">
              {t("late.reschedule_reason")}
            </label>
            <textarea
              id="agenda-reschedule-reason"
              className="filter-control"
              rows={3}
              value={reason}
              disabled={busy}
              onChange={(event) => setReason(event.target.value)}
              data-testid="agenda-reschedule-reason"
            />
          </div>
        )}
        {error && (
          <div className="alert-error" role="alert" data-testid="agenda-reschedule-error">
            {error}
          </div>
        )}
        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid="agenda-reschedule-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={busy || !ready}
            data-testid="agenda-reschedule-confirm"
          >
            {t("late.reschedule_confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
