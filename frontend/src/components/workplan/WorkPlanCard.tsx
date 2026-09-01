import {
  CalendarClock,
  CheckCircle2,
  Hourglass,
  Users,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { Role } from "../../api/types";
import type { WorkPlanEntry, WorkPlanPart } from "../../api/workPlan";
import { formatPlannedWindow } from "../../lib/plannedWindow";
import { toDateString } from "../../lib/isoWeek";
import { cardFactLine, cardFactState } from "./cardFact";
import { detailPath, formatDay } from "./entryHelpers";
import { PartChips } from "./PartChips";

/**
 * Sprint 183 §3 — one job on the plan, dense.
 *
 * The reference's card, top to bottom: a coloured kind tag, the title, a
 * grey `building · <where>` line, a status chip. Ours had grown to a
 * heading row, a full-width red overdue banner, a window line, a kind
 * tag, an assignee line, a note and two buttons — 140px tall for one
 * job, which is why four of them filled a column and the week read as a
 * wall.
 *
 * P-3 §A.2 — ONE CARD, ONE VOICE. After FE-4 and P-1 a card could still
 * carry a placement marker, a due chip, a never-done note AND a status
 * badge in its foot — four things saying "where this stands", in four
 * vocabularies, on a 210px card. The owner's own screenshot of the
 * "final test" ticket showed three of them at once. So the card now
 * has exactly:
 *
 *   ONE STATUS LINE   `StatusLine`: the settled sentence, or the reason
 *                     it is a visitor on this column, or — for a live
 *                     card at home — the plain status badge. Never two.
 *   AT MOST ONE       `TimeChip`: a clock (only when a REAL time exists
 *   TIME CHIP         — the server says so through `start_time`), else
 *                     "planned after the deadline", else the deadline
 *                     countdown, else the planned window. Never two.
 *
 * The couldn't-complete reason is not on the card at all: the card says
 * "Niet gelukt op 26 aug", the reason lives on the detail. The
 * never-done hours moved to the late strip's own modal, where the rung
 * is explained.
 */

/**
 * FE-4 (Addendum D §D.12 item 4) — WORK THAT IS OVER, IN THE PAST TENSE.
 *
 * A settled card applies no pressure: no red, no "te laat", nothing that
 * implies action. It says when it was finished and — quietly — that the
 * finish came after the due date, as history. Work sitting with the
 * customer or with the manager wears a neutral "waiting" chip: it is
 * settled for THIS reader, and never late-styled against them.
 *
 * P-3 §A.9 (the matrix) — every closed shape has its OWN words now. A
 * rejected ticket used to read "Afgerond op", a converted one and a
 * cancelled extra work "Niet gelukt", and a slot somebody was taken off
 * "Niet gelukt" too. The words are the app's existing phase and slot
 * vocabulary, not a second set.
 */
export function SettledLine({ entry }: { entry: WorkPlanEntry }) {
  const { t } = useTranslation(["staff_slots", "common"]);
  if (entry.ticket_status === "WAITING_CUSTOMER_APPROVAL") {
    return (
      <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="customer">
        {t("agenda.waiting_customer")}
      </span>
    );
  }
  if (entry.ticket_status === "WAITING_MANAGER_REVIEW") {
    return (
      <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="review">
        {t("agenda.waiting_review")}
      </span>
    );
  }
  if (entry.kind === "TICKET_SLOT" && entry.status === "CANCELLED") {
    return (
      <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="cancelled">
        {t("agenda.slot_cancelled")}
      </span>
    );
  }
  if (entry.state === "BLOCKED") {
    const closedWord =
      entry.kind === "EXTRA_WORK"
        ? entry.status === "CANCELLED"
          ? t("common:phase.ew.CANCELLED")
          : entry.status === "CUSTOMER_REJECTED"
            ? t("common:phase.ew.REJECTED")
            : null
        : entry.ticket_status === "REJECTED"
          ? t("common:phase.ticket.REJECTED")
          : entry.ticket_status === "CONVERTED_TO_EXTRA_WORK"
            ? t("common:phase.ticket.CONVERTED")
            : null;
    if (closedWord) {
      return (
        <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="closed">
          {closedWord}
        </span>
      );
    }
    // "Unable to complete" is not finished: the stuck list carries the
    // pressure; the card says WHEN it could not be done — the day the
    // slot was for — and nothing more. The reason is on the detail.
    const failedOn =
      entry.settled_at?.slice(0, 10) ?? entry.planned_end ?? entry.planned_start;
    return (
      <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="blocked">
        {failedOn
          ? t("agenda.blocked_on", { date: formatDay(failedOn) })
          : t("agenda.chip_blocked")}
      </span>
    );
  }
  const after = entry.settled_days_after_due;
  return (
    <span className="wp-settled" data-testid="agenda-card-settled">
      {entry.settled_at
        ? t("agenda.settled_on", { date: formatDay(entry.settled_at.slice(0, 10)) })
        : t("agenda.settled_plain")}
      {after !== null && after > 0 && (
        <span className="wp-settled-after">
          {" "}
          {t(
            entry.due_kind === "DEADLINE"
              ? "agenda.settled_after_deadline"
              : "agenda.settled_after_plan",
            { count: after },
          )}
        </span>
      )}
    </span>
  );
}

/** FE-3 — the chip itself, for surfaces that carry the two numbers
 *  without a work-plan entry (the ticket detail's fact block reads
 *  `days_until_due` / `due_kind` off the ticket). ONE chip vocabulary
 *  for one concept: the words, tones and testid are the agenda's. */
export function DueChipCore({
  days,
  hasDeadline,
  dueDate = null,
}: {
  days: number;
  hasDeadline: boolean;
  /** P-8R E — the deadline's own day; when given, the chip prints it
   *  beside the countdown. Surfaces without it keep the countdown only. */
  dueDate?: string | null;
}) {
  const { t } = useTranslation("staff_slots");
  const tone = days < 0 ? "over" : days === 0 ? "today" : "left";
  const over = Math.abs(days);
  const dated = hasDeadline && dueDate ? formatDay(dueDate) : null;
  const label = hasDeadline
    ? dated
      ? days < 0
        ? t("agenda.due_over_dated", { count: over, date: dated })
        : days === 0
          ? t("agenda.due_today_dated", { date: dated })
          : t("agenda.due_left_dated", { count: days, date: dated })
      : days < 0
        ? t("agenda.due_over", { count: over })
        : days === 0
          ? t("agenda.due_today")
          : t("agenda.due_left", { count: days })
    : days < 0
      ? t("agenda.plan_over", { count: over })
      : days === 0
        ? t("agenda.plan_today")
        : t("agenda.plan_in", { count: days });
  return (
    <span
      className={`wp-due wp-due-${tone}`}
      data-testid="agenda-card-due"
      data-tone={tone}
    >
      <Hourglass size={11} strokeWidth={2.5} />
      {label}
    </span>
  );
}

/** P-3 §A.5 — a real plan whose last day is past the deadline. Said in
 *  the deadline chip's own shape and tone; the plan dialog warned before
 *  the save, and the detail states the same fact. */
export function AfterDeadlineChip() {
  const { t } = useTranslation("staff_slots");
  return (
    <span className="wp-due wp-due-over" data-testid="agenda-card-after-deadline">
      <Hourglass size={11} strokeWidth={2.5} />
      {t("agenda.planned_after_deadline")}
    </span>
  );
}

/** The clock window as the server states it ("09:30–12:00"), else the
 *  slot's free-text window label; empty when the plan is a day and not
 *  a time. Never derived from the raw instant — see `start_time`. */
function clockText(entry: WorkPlanEntry): string {
  const parts: string[] = [];
  if (entry.start_time) {
    parts.push(
      entry.end_time ? `${entry.start_time}–${entry.end_time}` : entry.start_time,
    );
  }
  if (entry.kind === "TICKET_SLOT" && entry.time_window_label) {
    parts.push(entry.time_window_label);
  }
  return parts.join(" · ");
}

/** The planned DAY window, for a card whose plan is days rather than a
 *  time: a customer's wish is captioned as one; a multi-day window says
 *  where it ends. Empty for a one-day plan — the column IS the day. */
function dayWindowText(
  entry: WorkPlanEntry,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (entry.plan_source === "CUSTOMER_WISH" && entry.planned_start) {
    return t("agenda.wished_on", { date: formatDay(entry.planned_start) });
  }
  if (entry.planned_end && entry.planned_end !== entry.planned_start) {
    return formatPlannedWindow(entry.planned_start, entry.planned_end, formatDay, {
      empty: "",
      endOnly: (end) => t("agenda.until_date", { date: end }),
    });
  }
  return "";
}

/**
 * P-3 §A.2 — AT MOST ONE TIME CHIP.
 *
 * For the person holding a slot the clock is what they need ("09:00 –
 * 12:00"), so it wins. For a job or an extra work on a manager's board
 * the promise wins: "planned after the deadline" first (it is the fact
 * that needs a decision), then the deadline countdown, then a day
 * window when the plan spans days. A settled card carries none — its
 * settled line already holds its date.
 */
function TimeChip({ entry }: { entry: WorkPlanEntry }) {
  const { t } = useTranslation("staff_slots");
  if (entry.viewer_settled) return null;
  const clock = clockText(entry);
  const isSlot = entry.kind === "TICKET_SLOT";
  // P-9 §A.3 — the deadline (date AND countdown) is in the one fact
  // line now, so the due chip is not repeated here; the chip keeps
  // only what the line does not say: a real clock, "planned after the
  // deadline", a multi-day window.
  const order: (() => React.ReactNode)[] = isSlot
    ? [
        () => clock && <ClockChip text={clock} />,
        () => entry.planned_after_deadline && <AfterDeadlineChip />,
      ]
    : [
        () => entry.planned_after_deadline && <AfterDeadlineChip />,
        () => clock && <ClockChip text={clock} />,
        () => {
          const window = dayWindowText(entry, t);
          return window && <ClockChip text={window} />;
        },
      ];
  for (const pick of order) {
    const node = pick();
    if (node) return <>{node}</>;
  }
  return null;
}

function ClockChip({ text }: { text: string }) {
  return (
    <span className="wp-card-time" data-testid="agenda-card-time">
      <CalendarClock size={11} strokeWidth={2} />
      {text}
    </span>
  );
}

/**
 * P-3 §A.2 — THE ONE STATUS LINE. P-9 §A.3 — and it is the ONE card fact
 * sentence (`cardFact.ts`), the same words the zones and the detail
 * headers print for the same state: "planned Tue 2 Sep · 4 h · Ahmet ·
 * deadline 4 Sep (2 days left)", "planned Mon 19 Aug · 2 days late",
 * "reported done 21 Aug by Ahmet · waiting for your check 3 days",
 * "planned Mon 19 Aug · finished Wed 21 Aug (2 days after the plan)".
 * A blocked card (rejected, converted, cancelled, could not be done)
 * keeps its closed word from the settled line. Never two lines.
 */
function StatusLine({ entry, today }: { entry: WorkPlanEntry; today: string }) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const state = cardFactState(entry, today);
  if (state === "blocked") return <SettledLine entry={entry} />;
  return (
    <span
      className={`wp-fact wp-fact-${state}`}
      data-testid="agenda-card-fact"
      data-state={state}
    >
      {cardFactLine(entry, today, t)}
    </span>
  );
}

export function WorkPlanCard({
  entry,
  role,
  onComplete,
  onUnable,
  today,
  hostParts,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
  onComplete: () => void;
  onUnable: () => void;
  /** P-9 §A.3 — the server's today ("YYYY-MM-DD"), the day the fact
   *  line's "Today" and "planned/finished" words are decided against.
   *  Falls back to the browser's day for a caller without a payload. */
  today?: string;
  /** W-LATE §3b — when set, this is a HOST card: the ticket's heading
   *  over the parts windowed on THIS day, on a day that is not the
   *  card's own. No status, no time, no actions — the job's own card
   *  carries those, one column over. */
  hostParts?: WorkPlanPart[];
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const to = detailPath(entry, role);
  const isExtraWork = entry.kind === "EXTRA_WORK";
  const isHost = hostParts !== undefined;

  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const heading = (
    <>
      {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
      {entry.title}
    </>
  );

  if (isHost) {
    return (
      <li
        className="wp-card wp-card-host"
        data-testid="agenda-part-host-card"
        data-kind={entry.kind}
        data-job={entry.ticket_id !== null ? `ticket-${entry.ticket_id}` : entry.key}
      >
        <span className="wp-kind-tag wp-kind-tag-ticket" data-testid="agenda-card-kind">
          {t("agenda.part_host")}
        </span>
        {to ? (
          <Link to={to} className="wp-card-title">
            {heading}
          </Link>
        ) : (
          <span className="wp-card-title">{heading}</span>
        )}
        {where && <span className="wp-card-where">{where}</span>}
        <PartChips parts={hostParts} testId="agenda-card-part" />
      </li>
    );
  }

  return (
    <li
      // W-VIEWER §5 — a card with nothing left for THIS reader to do is
      // calm: it stays on the board (a manager may still withdraw a job
      // sitting with the customer) and stops demanding action.
      className={`wp-card${entry.viewer_settled ? " wp-card-settled" : ""}`}
      data-testid="agenda-slot-card"
      data-kind={entry.kind}
      data-placement={entry.placement}
      data-settled={entry.viewer_settled ? "1" : "0"}
    >
      <span
        className={`wp-kind-tag${isExtraWork ? "" : " wp-kind-tag-ticket"}`}
        data-testid="agenda-card-kind"
      >
        {isExtraWork ? t("agenda.source_extra_work") : t("agenda.source_ticket")}
      </span>

      {to ? (
        <Link to={to} className="wp-card-title">
          {heading}
        </Link>
      ) : (
        <span className="wp-card-title">{heading}</span>
      )}

      {where && <span className="wp-card-where">{where}</span>}

      <div className="wp-card-status" data-testid="agenda-card-status">
        <StatusLine entry={entry} today={today ?? toDateString(new Date())} />
      </div>

      {/* W-N1 §3 — WHICH half of the job is this person's. Reuses the
          Assignment section's own `.parts-chip` pair rather than a
          second chip style. Extra work carries an empty list, so this
          renders nothing there without a `kind` check. */}
      {entry.parts.length > 0 && (
        <PartChips parts={entry.parts} testId="agenda-card-part" />
      )}

      <div className="wp-card-foot">
        <TimeChip entry={entry} />
        {entry.assignee_count > 1 && (
          <span className="wp-card-time" data-testid="agenda-card-assignees">
            <Users size={11} strokeWidth={2} />
            {entry.assignee_count}
          </span>
        )}
      </div>

      {entry.can_complete && (
        <div className="wp-card-actions" data-testid="agenda-slot-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onComplete}
            data-testid="agenda-mark-done"
          >
            <CheckCircle2 size={13} strokeWidth={2} />
            {t("agenda.mark_done")}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onUnable}
            data-testid="agenda-mark-unable"
          >
            <XCircle size={13} strokeWidth={2} />
            {t("agenda.cant_complete")}
          </button>
        </div>
      )}
    </li>
  );
}
