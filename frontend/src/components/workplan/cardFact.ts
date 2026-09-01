/**
 * P-9 §A.3 (Addendum D §D.21) — THE ONE CARD FACT LINE.
 *
 * One sentence per state, the same sentence everywhere a job is shown:
 * the board's cards, the "Not planned yet" and "Waiting for the
 * customer" zones, and the detail headers. No surface writes its own
 * version. The table, in the owner's words:
 *
 *   not planned        created {date} by {who} · deadline {date}
 *                      ({n} days left / over) — or "no deadline"
 *   planned, future    planned {weekday date} · {n} h · {people} ·
 *                      deadline {date} ({relative})
 *   planned, today     the same, first word "Today"
 *   rolled onto today  planned {weekday date} · {n} days late · deadline
 *   reported done,     reported done {date} by {who} · waiting for your
 *   manager check      check {n} days
 *   waiting customer   reported done {date} · sent to {contact} ·
 *                      waiting {n} days
 *   finished           planned {date} · finished {date} ({n} days after
 *                      the plan / on the day) · approved {date} when later
 *
 * A deadline is always date AND relative. "Planned" is only ever a day a
 * person chose (P-1's provenance rule): a customer's wish reads as a
 * wish, a seeded date as no plan. Every day printed here is one the
 * SERVER decided in its own zone (`*_day` fields), never a slice of an
 * instant (P-3 §A.3).
 *
 * A plain .ts on purpose: the page, the card and the rows import it,
 * and a helper exported beside a component costs that file its fast
 * refresh.
 */
import type { TFunction } from "i18next";

import type { WorkPlanEntry } from "../../api/workPlan";
import { formatDay, formatPlannedDay } from "./entryHelpers";

export type CardFactState =
  | "not_planned"
  | "planned"
  | "planned_today"
  | "rolled"
  | "review"
  | "waiting_customer"
  | "finished"
  | "blocked";

/** Which row of the table this entry is on. */
export function cardFactState(entry: WorkPlanEntry, todayIso: string): CardFactState {
  if (entry.ticket_status === "WAITING_CUSTOMER_APPROVAL") return "waiting_customer";
  if (entry.placement === "REVIEW" || entry.ticket_status === "WAITING_MANAGER_REVIEW") {
    return "review";
  }
  if (entry.state === "BLOCKED") return "blocked";
  if (entry.state === "DONE") return "finished";
  if (entry.placement === "ROLLED") return "rolled";
  const planned =
    entry.has_real_plan &&
    entry.plan_source !== null &&
    entry.plan_source !== "CUSTOMER_WISH" &&
    entry.planned_start !== null;
  if (!planned || entry.planned_start === null) return "not_planned";
  const end = entry.planned_end ?? entry.planned_start;
  if (entry.planned_start <= todayIso && todayIso <= end) return "planned_today";
  return "planned";
}

/** "deadline 4 Sep 2026 (2 days left)" — date AND relative, or null when
 *  the job carries no real deadline (a planned day is never called one). */
function deadlineText(entry: WorkPlanEntry, t: TFunction): string | null {
  if (entry.due_kind !== "DEADLINE" || !entry.due_date) return null;
  const date = formatDay(entry.due_date);
  const days = entry.days_until_due;
  if (days === null) return t("agenda.fact_deadline", { date });
  if (days < 0) return t("agenda.fact_deadline_over", { date, count: -days });
  if (days === 0) return t("agenda.fact_deadline_today", { date });
  return t("agenda.fact_deadline_left", { date, count: days });
}

/** "4.00" -> "4", "4.50" -> "4.5". */
function hoursText(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

/** The sentence. Empty for a blocked (rejected / converted / cancelled /
 *  could-not-do) card, whose closed word the settled line already says. */
export function cardFactLine(entry: WorkPlanEntry, todayIso: string, t: TFunction): string {
  const state = cardFactState(entry, todayIso);
  const parts: string[] = [];
  const created = entry.created_at ? formatDay(entry.created_at.slice(0, 10)) : null;
  const deadline = deadlineText(entry, t);
  const people = entry.assignee_names.join(", ");
  const hours = entry.planned_hours
    ? t("agenda.fact_hours", { hours: hoursText(entry.planned_hours) })
    : null;
  const busy = entry.state === "IN_PROGRESS" ? t("common:phase.ticket.IN_EXECUTION") : null;

  switch (state) {
    case "not_planned":
      if (created) {
        parts.push(
          entry.created_by_name
            ? t("agenda.fact_created_by", { date: created, name: entry.created_by_name })
            : t("agenda.fact_created", { date: created }),
        );
      }
      if (entry.plan_source === "CUSTOMER_WISH" && entry.planned_start) {
        parts.push(t("agenda.fact_wished", { date: formatPlannedDay(entry.planned_start) }));
      }
      parts.push(deadline ?? t("agenda.fact_no_deadline"));
      break;
    case "planned":
    case "planned_today":
      if (busy) parts.push(busy);
      parts.push(
        state === "planned_today"
          ? t("agenda.fact_today")
          : t("agenda.fact_planned", {
              date: formatPlannedDay(entry.planned_start ?? todayIso),
            }),
      );
      if (hours) parts.push(hours);
      if (people) parts.push(people);
      if (deadline) parts.push(deadline);
      break;
    case "rolled":
      if (busy) parts.push(busy);
      parts.push(
        t("agenda.fact_planned", {
          date: formatPlannedDay(entry.rolled_from ?? entry.planned_start ?? todayIso),
        }),
      );
      if (entry.rolled_days !== null) parts.push(t("agenda.fact_late", { count: entry.rolled_days }));
      if (deadline) parts.push(deadline);
      break;
    case "review": {
      const reported = entry.reported_done_day ? formatDay(entry.reported_done_day) : null;
      if (reported) {
        parts.push(
          entry.reported_done_by_name
            ? t("agenda.fact_reported_done_by", { date: reported, name: entry.reported_done_by_name })
            : t("agenda.fact_reported_done", { date: reported }),
        );
      }
      parts.push(
        t("agenda.fact_waiting_check", { count: entry.waiting_days ?? entry.stuck_age_days ?? 0 }),
      );
      break;
    }
    case "waiting_customer": {
      const reported = entry.reported_done_day ? formatDay(entry.reported_done_day) : null;
      if (reported) parts.push(t("agenda.fact_reported_done", { date: reported }));
      if (entry.sent_to_name) parts.push(t("agenda.fact_sent_to", { name: entry.sent_to_name }));
      parts.push(t("agenda.fact_waiting_customer", { count: entry.waiting_days ?? 0 }));
      break;
    }
    case "finished": {
      if (entry.has_real_plan && entry.planned_start && entry.plan_source !== "CUSTOMER_WISH") {
        parts.push(t("agenda.fact_planned", { date: formatPlannedDay(entry.planned_start) }));
      }
      const finished = entry.settled_day;
      if (finished) {
        const after = entry.settled_days_after_plan;
        const date = formatDay(finished);
        parts.push(
          after === null
            ? t("agenda.fact_finished", { date })
            : after === 0
              ? t("agenda.fact_finished_on_the_day", { date })
              : t("agenda.fact_finished_after", { date, count: after }),
        );
        if (entry.approved_day && entry.approved_day > finished) {
          parts.push(t("agenda.fact_approved", { date: formatDay(entry.approved_day) }));
        }
      } else {
        parts.push(t("agenda.settled_plain"));
      }
      break;
    }
    case "blocked":
      return "";
  }
  return parts.filter(Boolean).join(" · ");
}
