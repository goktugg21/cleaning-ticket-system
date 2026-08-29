import {
  AlarmClock,
  CalendarClock,
  CheckCircle2,
  History,
  Hourglass,
  PlayCircle,
  Users,
  XCircle,
  ClipboardCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { SlotStatus } from "../../api/admin";
import type { Role } from "../../api/types";
import type { WorkPlanEntry, WorkPlanPart } from "../../api/workPlan";
import { SlotStatusBadge } from "../SlotStatusBadge";
import { StatusBadge } from "../StatusBadge";
import { formatPlannedWindow } from "../../lib/plannedWindow";
import { detailPath, formatDay, formatPlannedDay } from "./entryHelpers";
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
 * Why this card is in a week that is not its planned one.
 *
 * §12B, verbatim: "A card shown outside its planned week must say why —
 * a short marker reading started early or overdue, with its planned date
 * on the card. Otherwise the operator meets the same job in two weeks
 * and cannot tell why."
 *
 * A card at HOME renders nothing here — which is the point. The marker
 * means "this is a visitor", so putting one on every card would tell the
 * reader nothing.
 *
 * W-PLANTRUTH §1b — ROLLED is the visitor this wave adds, and the one
 * the LAW is about. The card is on TODAY's column because its work is
 * not done; the marker prints the day it was PLANNED for and how far
 * past that we are, because that date is the fact and it never moved.
 * Driven by `rolled_from` / `rolled_days` and NOT by the late ladder:
 * a slot whose own day has passed can sit on a ticket whose widest
 * window has not (a colleague works it on Friday), so the card rolls
 * while the JOB is not yet late. Two different questions, two fields.
 */
export function PlacementMarker({
  entry,
  deadlineIsHeadline = false,
}: {
  entry: WorkPlanEntry;
  /** FE-4 — a real deadline is the ONE headline (the due chip); the
   *  marker then says only where the card came from, without a second
   *  "te laat" count. */
  deadlineIsHeadline?: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  if (entry.placement === "PLANNED") return null;

  /* FE-4 (Addendum D §D.12 item 2) — HONEST DATE WORDS. "Gepland <date>"
     only when somebody planned it (`plan_source` TICKET / PROVIDER_PLAN);
     a customer's wish says it is a wish; a card with no window at all
     says when it was created and that it is not planned yet. */
  const originDate = entry.rolled_from ?? entry.planned_start;
  const origin = (count: number | null) => {
    if (entry.plan_source === "CUSTOMER_WISH" && originDate) {
      return t("agenda.wished_on", { date: formatPlannedDay(originDate) });
    }
    // P-1 — a date is a plan only if a PERSON made it: a seeded date
    // (`has_real_plan` false) reads exactly like no date at all, with
    // who created it. Never "Gepland", never "te laat".
    if (entry.plan_source === null || !originDate || !entry.has_real_plan) {
      if (!entry.created_at) return t("agenda.not_planned_yet");
      const created = formatDay(entry.created_at.slice(0, 10));
      const line = entry.created_by_name
        ? t("agenda.created_by_on", { date: created, name: entry.created_by_name })
        : t("agenda.created_on", { date: created });
      return `${line} · ${t("agenda.not_planned_yet")}`;
    }
    if (deadlineIsHeadline || count === null) {
      return t("agenda.planned_on", { date: formatPlannedDay(originDate) });
    }
    return t("agenda.why_rolled", { date: formatPlannedDay(originDate), count });
  };

  if (entry.placement === "ROLLED") {
    return (
      <div
        className={deadlineIsHeadline ? "wp-why wp-why-origin" : "wp-why wp-why-rolled"}
        data-testid="agenda-card-why"
      >
        <History size={11} strokeWidth={2.5} />
        {origin(entry.rolled_days)}
      </div>
    );
  }

  if (entry.placement === "REVIEW") {
    // P-1 §3 / P-3 §A.4 — the worker reported it done; THIS reader has
    // to check it. The manager reads the truth, with the waiting age.
    return (
      <div className="wp-why wp-why-review" data-testid="agenda-card-why">
        <ClipboardCheck size={11} strokeWidth={2.5} />
        {t("agenda.why_review", { count: entry.stuck_age_days ?? 0 })}
      </div>
    );
  }

  if (entry.placement === "OVERDUE") {
    // WP-1 G0 — the same-week carry: the card is a marked visitor on
    // today's column. With a real deadline the due chip is the alarm and
    // this line is only the origin; without one, this line is the alarm.
    return (
      <div
        className={deadlineIsHeadline ? "wp-why wp-why-origin" : "wp-why wp-why-overdue"}
        data-testid="agenda-card-why"
      >
        <AlarmClock size={11} strokeWidth={2.5} />
        {entry.plan_source !== null && originDate
          ? origin(entry.overdue_days)
          : entry.due_date && !deadlineIsHeadline
            ? t("agenda.why_overdue", { date: formatDay(entry.due_date) })
            : origin(null)}
      </div>
    );
  }

  const key =
    entry.placement === "STARTED_EARLY" ? "why_started_early" : "why_started";
  return (
    <div className="wp-why wp-why-started" data-testid="agenda-card-why">
      <PlayCircle size={11} strokeWidth={2.5} />
      {entry.planned_start
        ? t(`agenda.${key}`, { date: formatDay(entry.planned_start) })
        : t("agenda.why_started_undated")}
    </div>
  );
}

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

/**
 * W-VIEWER §5 — HOW THIS READER STANDS AGAINST THE PROMISE.
 *
 * "Late" is a fact you learn one day after you could have acted on it.
 * The ruling asks every relevant card to say the time remaining until
 * the deadline OR how far past it, so somebody can read their standing
 * without opening the ticket. `days_until_due` is the signed number the
 * server computes from the same `due` the placement rule uses — days
 * left when positive, days over when negative, today at zero.
 *
 * TWO WORDINGS, and the difference matters. `lateness.deadline` is the
 * extra work's own PROMISE; `due_date` falls back to the last planned
 * day for a job nobody promised anything about. Counting down to the
 * second one under the word "deadline" would be inventing a promise, so
 * a job with no deadline counts down to its PLAN and says so.
 *
 * Suppressed on a rolled card with no deadline: the placement marker
 * there already prints "Planned <date> — N days late", and this would be
 * that same fact a second time. Where a real deadline exists it is shown
 * even on a rolled card, because the plan and the promise are then two
 * different dates and the reader needs both.
 */
export function DueChip({ entry }: { entry: WorkPlanEntry }) {
  const days = entry.days_until_due;
  if (days === null) return null;
  // FE-4 — the SERVER's word for what the number counts against; the
  // detail page reads the same field, so card and detail agree.
  const hasDeadline = entry.due_kind === "DEADLINE";
  // WP-1 G0 — an OVERDUE-placed card's marker already prints
  // "Gepland <day> — N dagen te laat"; without a real deadline the chip
  // would be that same fact a second time, exactly like on ROLLED.
  if (
    !hasDeadline &&
    (entry.placement === "ROLLED" || entry.placement === "OVERDUE")
  )
    return null;
  return <DueChipCore days={days} hasDeadline={hasDeadline} />;
}

/** FE-3 — the chip itself, for surfaces that carry the two numbers
 *  without a work-plan entry (the ticket detail's fact block reads
 *  `days_until_due` / `due_kind` off the ticket). ONE chip vocabulary
 *  for one concept: the words, tones and testid are the agenda's. */
export function DueChipCore({
  days,
  hasDeadline,
}: {
  days: number;
  hasDeadline: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  const tone = days < 0 ? "over" : days === 0 ? "today" : "left";
  const over = Math.abs(days);
  const label = hasDeadline
    ? days < 0
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
  const order: (() => React.ReactNode)[] = isSlot
    ? [
        () => clock && <ClockChip text={clock} />,
        () => entry.planned_after_deadline && <AfterDeadlineChip />,
        () => <DueChip entry={entry} />,
      ]
    : [
        () => entry.planned_after_deadline && <AfterDeadlineChip />,
        () => <DueChip entry={entry} />,
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
 * P-3 §A.2 — THE ONE STATUS LINE.
 *
 * Settled: the past-tense sentence. A visitor on this column: the reason
 * it is here (the placement marker). A live card at home: the plain
 * status badge. Exactly one of the three, never a badge under a marker.
 */
function StatusLine({ entry }: { entry: WorkPlanEntry }) {
  if (entry.viewer_settled) return <SettledLine entry={entry} />;
  if (entry.placement !== "PLANNED") {
    return (
      <PlacementMarker
        entry={entry}
        deadlineIsHeadline={entry.due_kind === "DEADLINE" && entry.days_until_due !== null}
      />
    );
  }
  if (entry.kind === "EXTRA_WORK") {
    return <StatusBadge status={{ kind: "extra-work", value: entry.status }} variant="cell" />;
  }
  if (entry.kind === "TICKET") {
    return <StatusBadge status={{ kind: "ticket", value: entry.status }} variant="cell" />;
  }
  return <SlotStatusBadge status={entry.status as SlotStatus} />;
}

export function WorkPlanCard({
  entry,
  role,
  onComplete,
  onUnable,
  hostParts,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
  onComplete: () => void;
  onUnable: () => void;
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
        <StatusLine entry={entry} />
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
