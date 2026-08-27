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
import { detailPath, formatDay } from "./entryHelpers";
import { latenessOf } from "./lateness";
import { LateBadge } from "./LateStrip";
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
export function PlacementMarker({ entry }: { entry: WorkPlanEntry }) {
  const { t } = useTranslation("staff_slots");
  if (entry.placement === "PLANNED") return null;

  if (entry.placement === "ROLLED") {
    return (
      <div className="wp-why wp-why-rolled" data-testid="agenda-card-why">
        <History size={11} strokeWidth={2.5} />
        {entry.rolled_from
          ? t("agenda.why_rolled", {
              date: formatDay(entry.rolled_from),
              count: entry.rolled_days ?? 0,
            })
          : t("agenda.why_rolled_undated")}
      </div>
    );
  }

  if (entry.placement === "OVERDUE") {
    return (
      <div className="wp-why wp-why-overdue" data-testid="agenda-card-why">
        <AlarmClock size={11} strokeWidth={2.5} />
        {entry.due_date
          ? t("agenda.why_overdue", { date: formatDay(entry.due_date) })
          : t("agenda.why_overdue_undated")}
        {entry.overdue_days !== null && (
          <span>{t("agenda.overdue_days", { count: entry.overdue_days })}</span>
        )}
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
 * W-VIEWER §5 — HOW THIS READER STANDS AGAINST THE PROMISE.
 *
 * "Late" is a fact you learn one day after you could have acted on it.
 * The ruling asks every relevant card to say the time remaining until
 * the deadline OR how far past it, so somebody can read their standing
 * without opening the ticket. `due_in_days` is the signed number the
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
  const { t } = useTranslation("staff_slots");
  const days = entry.due_in_days;
  if (days === null) return null;
  const hasDeadline = entry.lateness.deadline !== null;
  if (!hasDeadline && entry.placement === "ROLLED") return null;
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

      {/* §12B — a card shown outside its planned week SAYS WHY, with its
          planned date on it. */}
      <PlacementMarker entry={entry} />
      {/* W-VIEWER — the marker above ALREADY printed "Planned <date> —
          N days late" on a rolled card, and that is word for word what
          this badge's first line says. `omitPlanned` hands the planned
          line to whichever of the two is already showing it; the badge
          keeps what it alone can add (the deadline line, the never-done
          line) and renders nothing when that is empty. */}
      {late && !entry.viewer_settled && (
        <LateBadge
          facts={late}
          testId="agenda-card-late"
          omitPlanned={entry.placement === "ROLLED"}
        />
      )}
      {/* W-VIEWER §5 — the countdown, on every card that has a promise
          to count against. It sits beside the rung rather than replacing
          it: one says how bad it already is, the other how long is
          left. */}
      <DueChip entry={entry} />

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
