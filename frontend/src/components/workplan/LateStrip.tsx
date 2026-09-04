import { useState } from "react";
import { AlarmClock, ShieldAlert, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { setTicketSchedule } from "../../api/admin";
import { api, getApiError } from "../../api/client";
import { transitionExtraWork } from "../../api/extraWork";
import type { Role, TicketStatusChangePayload } from "../../api/types";
import { planExtraWorkForDate } from "../../api/workPlan";
import type { LateLevel, WorkPlanEntry } from "../../api/workPlan";
import { canAccessExtraWork } from "../../auth/permissions";
import { BoundedList } from "../BoundedList";
import { RejectReasonDialog } from "../RejectReasonDialog";
import { useToast } from "../ToastProvider";
import { plannedDayIso, toDateString } from "../../lib/isoWeek";
import { detailPath, formatDay } from "./entryHelpers";
import {
  LATE_GROUPS,
  LATE_LEVEL_CLASS,
  escalationStep,
  latenessOf,
  notifiedSentence,
  sortLate,
} from "./lateness";
import type { LateFacts } from "./lateness";
import { PartChips } from "./PartChips";

/**
 * W-PLANTRUTH §1c — THE LATE SURFACE, AS THREE CHIPS.
 *
 * What this replaces, and why. W-LATE shipped two things above the week:
 * a WRAPPING ROW OF CARDS, one per late job, and — when an L3 job
 * existed — a second full-width bordeaux BAR listing those jobs again
 * with their actions. On real data the card row is the whole backlog
 * rendered as cards: it pushed the week grid below the fold, and the
 * bar said a subset of it a second time. Two surfaces, one fact.
 *
 * So the row becomes a SUMMARY: three compact chips, one per rung,
 * each carrying its count.
 *
 *     Plan passed · 12    Deadline passed · 4    Never done · 2
 *        (orange)              (red)               (bordeaux)
 *
 * Clicking one opens a modal listing that group's jobs — the same
 * `BoundedList` day-modal pattern the Overdue button and the day header
 * already open, so there is one modal vocabulary on this page rather
 * than a third. The severity ladder, its colours and its left-to-right
 * order are unchanged: they are read from `LATE_GROUPS`, the one
 * exported ordered constant, which `sortLate` sorts by.
 *
 * THE QUARANTINE BAR IS GONE. Its three actions were the only thing it
 * had that the cards did not, so they moved into the NEVER DONE modal's
 * rows, unchanged: Open goes to the record; Reschedule writes the new
 * day (and, for a ticket, the reason the schedule endpoint has demanded
 * since Sprint 9B) through the doors the undated lane already uses;
 * Cancel closes the job — an extra work through its own CANCELLED
 * transition, a ticket through the SUPER_ADMIN-only out-of-machine jump
 * to CLOSED, recorded with its reason. The button is offered to exactly
 * the role the server admits, and to nobody else.
 *
 * THE LAW OF THE WAVE is unchanged and is what the badges print: a job
 * is here because it is unfinished, not because anything moved. Its
 * planned date is the date it always had.
 *
 * Zero-count chips STAY. A chip that vanishes at zero makes the strip's
 * shape change under the reader, and "0 never done" is information
 * somebody came here for — the same rule `WorkPlanStrip` states for the
 * status chips it sits above.
 */

export function LateStrip({
  entries,
  truncated,
  limit,
  role,
  onChanged,
}: {
  entries: WorkPlanEntry[];
  truncated: boolean;
  limit: number;
  role: Role | null;
  /** Reload the plan after a reschedule / cancel from the modal. */
  onChanged: () => void;
}) {
  const { t } = useTranslation("staff_slots");
  /** Which rung's modal is open, or null. The LEVEL rather than the row
   *  set: `entries` is rebuilt on every reload, and holding the rows
   *  would pin a stale list open behind the user's own actions. */
  const [openLevel, setOpenLevel] = useState<LateLevel | null>(null);

  const sorted = sortLate(entries);
  if (sorted.length === 0) return null;

  const byLevel = (level: LateLevel) =>
    sorted.filter((entry) => latenessOf(entry)?.level === level);
  const openRows = openLevel === null ? [] : byLevel(openLevel);

  return (
    <section
      className="wp-late"
      data-testid="agenda-late-strip"
      aria-label={t("late.strip_title")}
    >
      <div className="wp-late-head">
        <span className="section-head-title wp-late-title">
          <AlarmClock size={15} strokeWidth={2.4} aria-hidden="true" />
          {t("late.strip_title")}
          <span className="wp-late-count" data-testid="agenda-late-count">
            {t("late.count", { count: sorted.length })}
          </span>
        </span>
        {/* P-2 — the sentence lives in the board's "How does this board
            work?" popover (AgendaPage); here it is the count's tooltip. */}
        <span className="visually-hidden">{t("late.strip_desc")}</span>
      </div>

      {/* The three severity chips. Ascending severity, left to right —
          the approved ladder's own order, read from `LATE_GROUPS` so a
          rung cannot be half-added. */}
      <div className="wp-late-chips" data-testid="agenda-late-chips">
        {LATE_GROUPS.map((group) => {
          const count = byLevel(group.level).length;
          return (
            <button
              key={group.level}
              type="button"
              className={`wp-late-chip ${group.className}`}
              data-testid={`agenda-late-chip-${group.level}`}
              data-level={group.level}
              disabled={count === 0}
              aria-haspopup="dialog"
              onClick={() => setOpenLevel(group.level)}
            >
              {group.level === 3 && (
                <ShieldAlert size={13} strokeWidth={2.4} aria-hidden="true" />
              )}
              <span className="wp-late-chip-label">{t(group.labelKey)}</span>
              <span className="wp-late-chip-count">{count}</span>
            </button>
          );
        })}
      </div>

      {truncated && (
        <p className="wp-notice" role="status" data-testid="agenda-late-truncated">
          {t("agenda.truncated_note", { count: limit })}
        </p>
      )}

      {openLevel !== null && (
        <LateGroupModal
          level={openLevel}
          rows={openRows}
          role={role}
          onClose={() => setOpenLevel(null)}
          onChanged={onChanged}
        />
      )}
    </section>
  );
}

/**
 * The badge every late surface prints — the week card, the group
 * modal's rows, the day modal's late half. One function so "Gepland 25
 * aug — 1 dag te laat" is spelled once.
 */
export function LateBadge({
  facts,
  testId = "agenda-late-badge",
  omitPlanned = false,
}: {
  facts: LateFacts;
  testId?: string;
  /** W-VIEWER — the caller already printed the planned-day line, so
   *  this badge must not print it again. See the note below; returns
   *  null when that line was the badge's only one. */
  omitPlanned?: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  const lines: string[] = [];
  if (omitPlanned) {
    // W-VIEWER — SAID ONCE.
    //
    // `late.badge_planned` and `agenda.why_rolled` are two keys holding
    // the SAME sentence: "Planned 25 Aug — 2 days late". A ROLLED card
    // renders the placement marker (which must say why it is on today's
    // column) and then this badge, so it printed that sentence twice.
    //
    // It was invisible until the viewer-aware board landed. Before it,
    // the marker printed the SLOT's day and the badge printed the
    // ladder's widest window, so the two usually differed and read as
    // two facts. Now both read the job's one date, and the repetition is
    // the whole line, twice, on a 150px card.
    //
    // So the caller owns the planned line and this badge carries what it
    // adds: the deadline line, and the never-done line. When it adds
    // nothing, it renders nothing — the marker already wears the L1
    // colour, so no severity is lost.
  } else if (facts.plannedDate && facts.plannedDaysLate !== null) {
    lines.push(
      t("late.badge_planned", {
        date: formatDay(facts.plannedDate),
        count: facts.plannedDaysLate,
      }),
    );
  } else if (facts.plannedDate) {
    lines.push(t("late.q_planned", { date: formatDay(facts.plannedDate) }));
  } else {
    lines.push(t("late.badge_undated"));
  }
  if (facts.deadline && facts.deadlineDaysLate !== null) {
    lines.push(
      t("late.badge_deadline", {
        date: formatDay(facts.deadline),
        count: facts.deadlineDaysLate,
      }),
    );
  }
  if (facts.level === 3 && facts.anchorDays !== null) {
    lines.push(t("late.badge_never_done", { count: facts.anchorDays }));
  }
  if (lines.length === 0) return null;
  return (
    <span
      className={`wp-late-badge wp-late-badge-l${facts.level}`}
      data-testid={testId}
      data-level={facts.level}
      title={t(`late.level_${facts.level}`)}
    >
      {lines.map((line, index) => (
        <span key={index} className="wp-late-badge-line">
          {line}
        </span>
      ))}
    </span>
  );
}

/**
 * One rung's jobs, full-width. The day-modal pattern: a fixed overlay
 * that closes on its own backdrop, a `.card` with a bounded list inside.
 *
 * The NEVER DONE rung (3) additionally carries the actions the
 * quarantine bar used to own, and the line saying who was told and
 * when. The other two rungs are a read: a job whose plan has slipped by
 * a day does not need a Cancel button next to it.
 */
function LateGroupModal({
  level,
  rows,
  role,
  onClose,
  onChanged,
}: {
  level: LateLevel;
  rows: WorkPlanEntry[];
  role: Role | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();
  const [rescheduling, setRescheduling] = useState<WorkPlanEntry | null>(null);
  const [cancelling, setCancelling] = useState<WorkPlanEntry | null>(null);
  const [cancelError, setCancelError] = useState("");

  const group = LATE_GROUPS.find((entry) => entry.level === level);
  const title = t(group ? group.labelKey : "late.strip_title");
  const withActions = level === 3;

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
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="agenda-late-group-modal"
      data-level={level}
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
            <div className="section-head-sub">
              {level === 3
                ? t("late.never_done_desc")
                : t("late.group_desc", { count: rows.length })}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            data-testid="agenda-late-group-close"
          >
            {t("common:cancel")}
          </button>
        </div>

        <BoundedList
          size="lg"
          count={rows.length}
          ariaLabel={title}
          testIdPrefix="agenda-late-group"
          emptyState={<p className="muted">{t("late.day_none")}</p>}
        >
          <ul className="wp-nd-rows">
            {rows.map((entry) => {
              const facts = latenessOf(entry);
              if (!facts) return null;
              const to = detailPath(entry, role);
              const step = escalationStep(facts, "L3_QUARANTINE");
              const notified = step ? notifiedSentence(step.names, t) : "";
              const heading = `${entry.ticket_no ? `${entry.ticket_no} · ` : ""}${entry.title}`;
              const where = [entry.building_name, entry.customer_name]
                .filter(Boolean)
                .join(" · ");
              const crew =
                entry.assignee_names.length > 0
                  ? entry.assignee_names.join(", ") +
                    (entry.assignee_count > entry.assignee_names.length
                      ? ` +${entry.assignee_count - entry.assignee_names.length}`
                      : "")
                  : t("late.crew_none");
              return (
                <li
                  key={entry.key}
                  className={`wp-nd-row ${LATE_LEVEL_CLASS[facts.level]}`}
                  data-testid="agenda-late-group-row"
                  data-job={
                    entry.ticket_id !== null
                      ? `ticket-${entry.ticket_id}`
                      : entry.key
                  }
                >
                  <div className="wp-nd-main">
                    {to ? <Link to={to}>{heading}</Link> : <span>{heading}</span>}
                    {where && <span className="muted small">{where}</span>}
                    <span className="wp-nd-crew">
                      <Users size={11} strokeWidth={2} aria-hidden="true" />
                      {crew}
                    </span>
                    {entry.parts.length > 0 && (
                      <PartChips
                        parts={entry.parts}
                        testId="agenda-late-group-part"
                      />
                    )}
                  </div>

                  <div className="wp-nd-facts" data-testid="agenda-late-group-facts">
                    <LateBadge facts={facts} testId="agenda-late-group-badge" />
                    {withActions && (
                      <>
                        <span className="wp-nd-nohours">
                          {t("late.q_no_hours")}
                        </span>
                        {/* The sentence names the person and says they
                            were told; the "Notified:" label is only for
                            the row that has nobody to name yet. */}
                        <span data-testid="agenda-late-group-notified">
                          {notified ||
                            t("late.q_notified", {
                              who: t("late.q_notified_none"),
                            })}
                          {step && (
                            <span className="muted">
                              {" · "}
                              {formatDay(step.notified_at.slice(0, 10))}
                            </span>
                          )}
                        </span>
                      </>
                    )}
                  </div>

                  {withActions && (
                    <div className="wp-nd-actions">
                      {to && (
                        <Link
                          to={to}
                          className="btn btn-secondary btn-sm"
                          data-testid="agenda-late-group-open"
                        >
                          {t("late.action_open")}
                        </Link>
                      )}
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setRescheduling(entry)}
                        data-testid="agenda-late-group-reschedule"
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
                          data-testid="agenda-late-group-cancel"
                        >
                          {t("late.action_cancel")}
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </BoundedList>

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
      </div>
    </div>
  );
}

/**
 * The reschedule door: a day and, for a ticket that already has a
 * schedule, the reason the schedule endpoint has required since Sprint
 * 9B. A plain overlay, conditionally mounted, like the assign dialog —
 * not a native `<dialog>`.
 *
 * W-PLANTRUTH §1a — `apply_to_slots`. "Reschedule" means the JOB moves,
 * and the board reads the planned day of the WORK (the slots'), not the
 * ticket's own date. So this door writes both together; without the
 * flag the operator would move the ticket's date and watch the card
 * stay exactly where it was.
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
        // P-3 §A.3 — a DAY, not a moment. Sent as a naive local
        // datetime at midnight (`plannedDayIso`): the server reads it in
        // ITS zone, so the day is the day whatever zone the browser is
        // in, and midnight is the convention every reader treats as
        // "no time" — noon here used to hand every rescheduled job a
        // 12:00 clock nobody chose.
        await setTicketSchedule(entry.ticket_id, {
          scheduled_start_at: plannedDayIso(date),
          reschedule_reason: reason.trim(),
          apply_to_slots: true,
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
