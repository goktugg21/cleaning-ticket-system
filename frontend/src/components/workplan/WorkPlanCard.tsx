import { CheckCircle2, ClipboardCheck, Hourglass, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { Role } from "../../api/types";
import type { WorkPlanEntry, WorkPlanPart } from "../../api/workPlan";
import { toDateString } from "../../lib/isoWeek";
import { PhaseBadge } from "../customer/PhaseBadge";
import { StatusBadge } from "../StatusBadge";
import { cardFacts } from "./cardFacts";
import type { CardFactLine } from "./cardFacts";
import { detailPath, formatDay } from "./entryHelpers";
import { useRowLink } from "../../lib/useRowLink";
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

/**
 * P-10 A4 — THE FACTS LIST. Three lines, one fact per line: a faint
 * label and a value (`cardFacts.ts` is the table). Lines wrap inside
 * the card; nothing overflows a column. Shared by the board's cards
 * and the strips' rows, so the same state reads the same everywhere.
 */
export function FactsList({
  lines,
  testId,
}: {
  lines: CardFactLine[];
  testId: string;
}) {
  return (
    <ul className="wp-facts" data-testid={testId}>
      {lines.map((row) => (
        <li key={row.key} className="wp-facts-row" data-fact={row.key}>
          <span className="wp-facts-label">{row.label}</span>
          <span className="wp-facts-value" data-tone={row.tone ?? "plain"}>
            {row.value}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * P-10 A4 — "Details": a fold on the card with the FULL list (the three
 * lines and the rest) and one link to the record. Native <details>; the
 * panel is a popover anchored to the card on a desk and a bottom sheet
 * on a phone (CSS decides, `workplan-zones.css`). Mounted only when the
 * state has more to say than the card shows.
 */
function CardDetails({
  lines,
  details,
  to,
  isExtraWork,
}: {
  lines: CardFactLine[];
  details: CardFactLine[];
  to: string | null;
  isExtraWork: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <details className="wp-details" data-testid="agenda-card-details">
      <summary className="wp-details-toggle">{t("agenda.details")}</summary>
      <div className="wp-details-panel">
        <FactsList lines={[...lines, ...details]} testId="agenda-card-details-list" />
        {to && (
          <Link to={to} className="btn btn-secondary btn-sm wp-details-open">
            {isExtraWork ? t("agenda.details_open_extra_work") : t("agenda.details_open_ticket")}
          </Link>
        )}
      </div>
    </details>
  );
}

/**
 * P-11 A1 — the job's status, under the title, on every card and strip
 * row. The owner: "I see the deadline, I don't see where the job is."
 * One word, one colour, from the vocabularies the rest of the app
 * already uses: the ticket's own `ticket_status.*` for ticket and slot
 * rows, the Extra work list's `display_phase` for an extra-work row —
 * both server-decided, never inferred here.
 */
export function EntryStatusBadge({
  entry,
  testId,
  className,
}: {
  entry: WorkPlanEntry;
  testId?: string;
  /** Wrapper class; the wrapper renders only when the badge does. */
  className?: string;
}) {
  const badge =
    entry.kind === "EXTRA_WORK" ? (
      entry.display_phase ? (
        <PhaseBadge kind="ew" phase={entry.display_phase} testId={testId} />
      ) : null
    ) : entry.ticket_status ? (
      <StatusBadge
        status={{ kind: "ticket", value: entry.ticket_status }}
        variant="cell"
        testId={testId}
      />
    ) : null;
  if (badge === null) return null;
  if (!className) return badge;
  return <span className={className}>{badge}</span>;
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
  // P-13 D (O3, §D.22 rule 9) — the WHOLE card opens the job; the
  // title stays a real link for middle-click and the card's buttons
  // stop the click through the shared inner-control guard.
  const { interactive, rowProps } = useRowLink({ to: to ?? undefined });
  const isExtraWork = entry.kind === "EXTRA_WORK";
  const isHost = hostParts !== undefined;
  const todayIso = today ?? toDateString(new Date());
  const facts = cardFacts(entry, todayIso, t);
  // P-10 A2 — the responsible manager's today card asks for a check:
  // teal, titled "Check: …", one button.
  const isCheck = facts.state === "check";

  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const heading = (
    <>
      {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
      {isCheck ? t("agenda.check_title", { title: entry.title }) : entry.title}
    </>
  );

  if (isHost) {
    return (
      <li
        className={`wp-card wp-card-host${interactive ? " clickable-row" : ""}`}
        data-testid="agenda-part-host-card"
        data-kind={entry.kind}
        data-job={entry.ticket_id !== null ? `ticket-${entry.ticket_id}` : entry.key}
        {...rowProps}
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
      className={`wp-card${entry.viewer_settled ? " wp-card-settled" : ""}${isCheck ? " wp-card-check" : ""}${interactive ? " clickable-row" : ""}`}
      data-testid="agenda-slot-card"
      data-kind={entry.kind}
      data-placement={entry.placement}
      data-settled={entry.viewer_settled ? "1" : "0"}
      data-state={facts.state}
      {...rowProps}
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

      {/* P-11 A1 — where the job stands, under the title. */}
      <EntryStatusBadge
        entry={entry}
        testId="agenda-card-badge"
        className="wp-card-badge"
      />

      {where && <span className="wp-card-where">{where}</span>}

      {/* P-10 A4 — three facts, one per line; the rest behind Details.
          A blocked card keeps its closed word (the settled line). */}
      <div className="wp-card-status" data-testid="agenda-card-status" data-state={facts.state}>
        {facts.state === "blocked" ? (
          <SettledLine entry={entry} />
        ) : (
          <FactsList lines={facts.lines} testId="agenda-card-facts" />
        )}
      </div>
      {facts.details.length > 0 && (
        <CardDetails lines={facts.lines} details={facts.details} to={to} isExtraWork={isExtraWork} />
      )}

      {/* W-N1 §3 — WHICH half of the job is this person's. Reuses the
          Assignment section's own `.parts-chip` pair rather than a
          second chip style. Extra work carries an empty list, so this
          renders nothing there without a `kind` check. */}
      {entry.parts.length > 0 && (
        <PartChips parts={entry.parts} testId="agenda-card-part" />
      )}

      {/* P-3 §A.5 — the one chip the facts do not say: a real plan whose
          last day is past the deadline. */}
      {!entry.viewer_settled && entry.planned_after_deadline && (
        <div className="wp-card-foot">
          <AfterDeadlineChip />
        </div>
      )}

      {isCheck && to && (
        <div className="wp-card-actions" data-testid="agenda-check-actions">
          <Link to={to} className="btn btn-primary btn-sm" data-testid="agenda-check-work">
            <ClipboardCheck size={13} strokeWidth={2} />
            {t("agenda.check_button")}
          </Link>
        </div>
      )}

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
