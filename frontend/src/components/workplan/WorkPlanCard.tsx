import {
  AlarmClock,
  CalendarClock,
  CheckCircle2,
  History,
  Hourglass,
  PlayCircle,
  Users,
  XCircle,
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
import { latenessOf } from "./lateness";
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
 * What each line had to earn:
 *
 *   kind tag    kept, and now on BOTH kinds. Tagging only extra work
 *               left "no tag" meaning ticket, and an absence is not a
 *               label.
 *   title       kept. It is the card.
 *   where       `building · customer`. The reference prints
 *               `building · department`; this payload carries no
 *               department, and a cleaning operator reads the customer.
 *   status      kept, through the app's existing badges.
 *   time        kept, but only when there IS one. A slot with no clock
 *               window used to print "No time", which is a sentence
 *               saying nothing.
 *   why         kept as a MARKER — see `PlacementMarker`. §12B requires
 *               a card outside its planned week to say why; it does not
 *               require a banner.
 *   assignees   kept only when there is more than one, as before.
 *   notes       DROPPED from the card. An assignment note, a completion
 *               note and an unable-reason are three more paragraphs on
 *               a card in a 230px column, and all three are on the
 *               detail page one click away. The card is a plan, not a
 *               record.
 *   actions     kept, and only for the person holding the slot.
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
    if (entry.plan_source === null || !originDate) {
      return entry.created_at
        ? `${t("agenda.created_on", { date: formatDay(entry.created_at.slice(0, 10)) })} · ${t("agenda.not_planned_yet")}`
        : t("agenda.not_planned_yet");
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
 */
export function SettledLine({ entry }: { entry: WorkPlanEntry }) {
  const { t } = useTranslation("staff_slots");
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
  if (entry.state === "BLOCKED" && !entry.settled_at) {
    // "Unable to complete" is not finished: the stuck list carries the
    // pressure; the card says what happened, in the chip's own words.
    return (
      <span className="wp-wait" data-testid="agenda-card-waiting" data-waiting="blocked">
        {t("agenda.chip_blocked")}
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

export function WorkPlanCard({
  entry,
  role,
  locale,
  onComplete,
  onUnable,
  hostParts,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
  locale: string;
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
  // W-VIEWER — the JOB card. One per ticket, carrying a TICKET status
  // and the ticket's own scheduled window; never a staff slot's clock.
  const isJob = entry.kind === "TICKET";
  const isHost = hostParts !== undefined;

  function timeOnly(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  }

  /** The clock window for a slot; the planned DAY window for extra work,
   *  which has no dated slot and never has had one. Empty string when
   *  there is nothing to say — the caller renders nothing rather than a
   *  line reading "No time". */
  function windowText(): string {
    if (isJob) {
      // The TICKET's own scheduled window — the fact that placed this
      // card. §3 of the ruling: the general board does not re-publish
      // each staff member's working hours; the ticket's Scheduling
      // section does, to anybody who opens it.
      if (!entry.scheduled_start_at) {
        // FE-4 — a window borrowed from the customer's WISH is a wish,
        // and the foot says so instead of printing it as a plan.
        if (entry.plan_source === "CUSTOMER_WISH" && entry.planned_start) {
          return t("agenda.wished_on", { date: formatDay(entry.planned_start) });
        }
        return formatPlannedWindow(entry.planned_start, entry.planned_end, formatDay, {
          empty: "",
          endOnly: (end) => t("agenda.until_date", { date: end }),
        });
      }
      return entry.scheduled_end_at
        ? `${timeOnly(entry.scheduled_start_at)}–${timeOnly(entry.scheduled_end_at)}`
        : timeOnly(entry.scheduled_start_at);
    }
    if (isExtraWork) {
      return formatPlannedWindow(entry.planned_start, entry.planned_end, formatDay, {
        empty: "",
        endOnly: (end) => t("agenda.until_date", { date: end }),
      });
    }
    const parts: string[] = [];
    if (entry.scheduled_start_at) {
      parts.push(
        entry.scheduled_end_at
          ? `${timeOnly(entry.scheduled_start_at)}–${timeOnly(entry.scheduled_end_at)}`
          : timeOnly(entry.scheduled_start_at),
      );
    }
    if (entry.time_window_label) parts.push(entry.time_window_label);
    return parts.join(" · ");
  }

  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const window = windowText();
  // W-LATE §1b — the same rung the strip shows, on the week card, so a
  // job on Tuesday's column and its card in the strip agree.
  const late = latenessOf(entry);
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

      {/* FE-4 (Addendum D §D.12 items 3-4) — ONE HEADLINE LATENESS, AND
          NONE ON SETTLED WORK.
          Live card: the deadline when one exists (the due chip), else
          the planned day (the placement marker's "Gepland <day> — N
          dagen te laat"). Never both as alarms: with a deadline the
          marker says only where the card came from. Every other
          time-fact is secondary and says what it is: the never-done
          fact ("87 dagen zonder gewerkte uren") is a quiet note under
          the facts, not a second red badge.
          Settled card: past tense, neutral, nothing implying action. */}
      {entry.viewer_settled ? (
        <SettledLine entry={entry} />
      ) : (
        <>
          <PlacementMarker
            entry={entry}
            deadlineIsHeadline={entry.due_kind === "DEADLINE" && entry.days_until_due !== null}
          />
          <DueChip entry={entry} />
          {late && late.level === 3 && late.anchorDays !== null && (
            <span className="wp-card-note" data-testid="agenda-card-never-done">
              {t("agenda.never_done_hours", { count: late.anchorDays })}
            </span>
          )}
        </>
      )}

      {/* W-N1 §3 — WHICH half of the job is this person's. Reuses the
          Assignment section's own `.parts-chip` pair rather than a
          second chip style: it is the same fact in a smaller place, and
          two chip vocabularies for one concept is how a design language
          stops being one. Extra work carries an empty list, so this
          renders nothing there without a `kind` check.
          W-LATE §3b — through `PartChips`, which also carries each
          part's state (done / last day / missed). */}
      {entry.parts.length > 0 && (
        <PartChips parts={entry.parts} testId="agenda-card-part" />
      )}

      <div className="wp-card-foot">
        {isExtraWork ? (
          <StatusBadge
            status={{ kind: "extra-work", value: entry.status }}
            variant="cell"
          />
        ) : isJob ? (
          <StatusBadge
            status={{ kind: "ticket", value: entry.status }}
            variant="cell"
          />
        ) : (
          <SlotStatusBadge status={entry.status as SlotStatus} />
        )}
        {window && (
          <span className="wp-card-time">
            <CalendarClock size={11} strokeWidth={2} />
            {window}
          </span>
        )}
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
