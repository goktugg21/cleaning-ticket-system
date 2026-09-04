/**
 * P-10 A4 (Addendum D §D.21, amended) — THE CARD FACTS: three per card,
 * one per line, short dates, the rest behind "Details".
 *
 * The owner's rule: "the most important details on the card; if it
 * doesn't fit, open something." P-9's one joined sentence overflowed a
 * 210px column on every real record, so the sentence became a list —
 * each line a faint label and a value — and the list is cut at three;
 * whatever else the state knows sits in the card's Details fold. The
 * table (the owner's, per state):
 *
 *   not planned      Created {date} by {who} · Deadline {date} — {n} days
 *                    left/over, or "none" · People {names} / "nobody yet"
 *   planned          Planned {date} [{time}] [· {n} h] · Deadline · People
 *                    (today inside a one-day plan: "Today")   + Created
 *   planned window,  Planned {start} – {end} · day {k} of {n} · Deadline ·
 *   today inside it  People                                   + Created
 *   rolled           Planned {date} — {n} days late · Deadline (red when
 *                    over) · People                           + Created
 *   check (the       Reported done {date} — {n} days ago · By {who} ·
 *   manager's today) Planned {date}                    + Created, Deadline
 *   reported done    Reported done {date} · Waiting on {manager} — {n}
 *   (the strips)     days · Planned {date}
 *   waiting for the  Reported done {date} by {who} · Sent to {contact} ·
 *   customer         Waiting {n} days                 + Planned, Deadline
 *   finished         Finished {date} — on the day / {n} days after the plan
 *                    · Deadline {date} — {n} days early/late · People
 *                    + Planned, Reported done (time, who), Manager check
 *                    (date, who), Customer approval (date, who), Created
 *
 * Every day printed here is one the SERVER decided in its own zone (the
 * `*_day` fields) and is printed short (`lib/shortDate.ts`): `Wed 26 Aug`,
 * no year unless it differs from today's. People are their own line,
 * never inside a date. A plain .ts on purpose (fast refresh).
 */
import type { TFunction } from "i18next";

import type { WorkPlanEntry } from "../../api/workPlan";
import { localeCode } from "../../lib/intl";
import { daysBetween, shortDay, shortDayTime, shortRange } from "../../lib/shortDate";

export type CardFactState =
  | "not_planned"
  | "planned"
  | "planned_today"
  | "planned_window"
  | "rolled"
  | "check"
  | "review"
  | "waiting_customer"
  | "finished"
  | "blocked";

export interface CardFactLine {
  key: string;
  label: string;
  value: string;
  /** `late` paints the value red; `strong` bolds it; default is plain. */
  tone?: "late" | "strong";
}

export interface CardFacts {
  state: CardFactState;
  /** At most three. */
  lines: CardFactLine[];
  /** The rest, for the Details fold. Empty when the card says it all. */
  details: CardFactLine[];
}

/** Which row of the table this entry is on. */
export function cardFactState(entry: WorkPlanEntry, todayIso: string): CardFactState {
  if (entry.ticket_status === "WAITING_CUSTOMER_APPROVAL") return "waiting_customer";
  if (entry.ticket_status === "WAITING_MANAGER_REVIEW") {
    // The responsible manager's today card (rule 8, personal since
    // P-10 A2) asks; every other reading of the same job reports.
    return entry.placement === "REVIEW" ? "check" : "review";
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
  if (entry.planned_start <= todayIso && todayIso <= end) {
    return end === entry.planned_start ? "planned_today" : "planned_window";
  }
  return "planned";
}

function hoursText(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

/** The facts, per the table. `t` is the `staff_slots` namespace. */
export function cardFacts(entry: WorkPlanEntry, todayIso: string, t: TFunction): CardFacts {
  const state = cardFactState(entry, todayIso);
  const locale = localeCode();
  const day = (iso: string | null | undefined) => shortDay(iso, locale, todayIso);
  const line = (key: string, label: string, value: string, tone?: CardFactLine["tone"]): CardFactLine =>
    tone ? { key, label, value, tone } : { key, label, value };
  const lbl = (name: string) => t(`agenda.lbl_${name}`);

  // -- the reusable values -------------------------------------------
  const created = (): CardFactLine => {
    const date = day(entry.created_day);
    return line(
      "created",
      lbl("created"),
      entry.created_by_name ? t("agenda.val_on_by", { date, name: entry.created_by_name }) : date,
    );
  };
  const people = (): CardFactLine => {
    const names = entry.assignee_names.join(", ");
    const extra = entry.assignee_count - entry.assignee_names.length;
    const value = names ? (extra > 0 ? `${names} +${extra}` : names) : t("agenda.val_nobody");
    return line("people", lbl("people"), value);
  };
  const hasDeadline = entry.due_kind === "DEADLINE" && !!entry.due_date;
  /** Live: date and countdown; red once over. */
  const deadlineLive = (): CardFactLine => {
    if (!hasDeadline || !entry.due_date) return line("deadline", lbl("deadline"), t("agenda.val_none"));
    const date = day(entry.due_date);
    const left = entry.days_until_due ?? daysBetween(todayIso, entry.due_date);
    if (left < 0) return line("deadline", lbl("deadline"), t("agenda.val_days_over", { date, count: -left }), "late");
    if (left === 0) return line("deadline", lbl("deadline"), t("agenda.val_deadline_today", { date }), "strong");
    return line("deadline", lbl("deadline"), t("agenda.val_days_left", { date, count: left }));
  };
  /** Over: how the finish stood against the deadline, past tense. */
  const deadlineSettled = (): CardFactLine => {
    if (!hasDeadline || !entry.due_date) return line("deadline", lbl("deadline"), t("agenda.val_none"));
    const date = day(entry.due_date);
    if (!entry.settled_day) return line("deadline", lbl("deadline"), date);
    const diff = daysBetween(entry.due_date, entry.settled_day);
    if (diff > 0) return line("deadline", lbl("deadline"), t("agenda.val_days_late_by", { date, count: diff }));
    if (diff < 0) return line("deadline", lbl("deadline"), t("agenda.val_days_early", { date, count: -diff }));
    return line("deadline", lbl("deadline"), t("agenda.val_on_the_day", { date }));
  };
  const plannedPlain = (): CardFactLine =>
    line("planned", lbl("planned"), shortRange(entry.planned_start, entry.planned_end, locale, todayIso));
  const withHours = (value: string) =>
    entry.planned_hours ? t("agenda.val_with_hours", { value, hours: hoursText(entry.planned_hours) }) : value;
  const reported = (withWho: boolean): CardFactLine => {
    const date = day(entry.reported_done_day);
    return line(
      "reported",
      lbl("reported_done"),
      withWho && entry.reported_done_by_name
        ? t("agenda.val_on_by", { date, name: entry.reported_done_by_name })
        : date,
    );
  };

  switch (state) {
    case "not_planned": {
      // P-15 §0.4 — the wish is a FACT on the strip, never a column:
      // "Wished for {date}" leads the card when the customer's wish is
      // the record's only date.
      if (entry.wished_day) {
        const wished = line("wished", lbl("wished"), day(entry.wished_day));
        return {
          state,
          lines: [wished, deadlineLive(), people()],
          details: [created()],
        };
      }
      const lines = [created(), deadlineLive(), people()];
      return { state, lines, details: [] };
    }
    case "planned":
    case "planned_today": {
      const start = entry.planned_start ?? todayIso;
      const isToday = state === "planned_today";
      const dayText = isToday
        ? entry.start_time
          ? t("agenda.val_today_at", { time: entry.start_time })
          : t("agenda.val_today")
        : entry.planned_end && entry.planned_end !== start
          ? shortRange(start, entry.planned_end, locale, todayIso)
          : shortDayTime(start, entry.start_time, locale, todayIso);
      const planned = line("planned", lbl("planned"), withHours(dayText), isToday ? "strong" : undefined);
      return { state, lines: [planned, deadlineLive(), people()], details: [created()] };
    }
    case "planned_window": {
      const start = entry.planned_start ?? todayIso;
      const end = entry.planned_end ?? start;
      const k = daysBetween(start, todayIso) + 1;
      const n = daysBetween(start, end) + 1;
      const planned = line(
        "planned",
        lbl("planned"),
        withHours(
          t("agenda.val_window_day", { range: shortRange(start, end, locale, todayIso), k, n }),
        ),
        "strong",
      );
      return { state, lines: [planned, deadlineLive(), people()], details: [created()] };
    }
    case "rolled": {
      const from = entry.rolled_from ?? entry.planned_end ?? entry.planned_start;
      const range = shortRange(entry.planned_start, from, locale, todayIso);
      const late = entry.rolled_days ?? (from ? daysBetween(from, todayIso) : 0);
      const planned = line("planned", lbl("planned"), t("agenda.val_days_late", { date: range, count: late }), "late");
      return { state, lines: [planned, deadlineLive(), people()], details: [created()] };
    }
    case "check": {
      const ago = entry.waiting_days ?? entry.stuck_age_days ?? 0;
      const lines = [
        line(
          "reported",
          lbl("reported_done"),
          t("agenda.val_days_ago", { date: day(entry.reported_done_day), count: ago }),
          "strong",
        ),
        line("by", lbl("by"), entry.reported_done_by_name ?? t("agenda.val_unknown_person")),
        plannedPlain(),
      ];
      return { state, lines, details: [created(), deadlineLive()] };
    }
    case "review": {
      const managers = entry.manager_names.length
        ? entry.manager_names.join(", ")
        : t("agenda.val_the_manager");
      const lines = [
        reported(false),
        line(
          "waiting_on",
          lbl("waiting_on"),
          t("agenda.val_waiting_on", { names: managers, count: entry.waiting_days ?? 0 }),
        ),
        plannedPlain(),
      ];
      return { state, lines, details: [] };
    }
    case "waiting_customer": {
      const lines = [
        reported(true),
        line("sent_to", lbl("sent_to"), entry.sent_to_name ?? t("agenda.val_the_customer")),
        line("waiting", lbl("waiting"), t("agenda.val_days", { count: entry.waiting_days ?? 0 })),
      ];
      return { state, lines, details: [plannedPlain(), deadlineLive()] };
    }
    case "finished": {
      const date = day(entry.settled_day);
      const after = entry.settled_days_after_plan;
      // P-15 4.2 — a missing finish date is NO line, never the label
      // printed as its own value ("Afgerond: Afgerond").
      const finished = !entry.settled_day
        ? null
        : line(
            "finished",
            lbl("finished"),
            after === null
              ? date
              : after === 0
                ? t("agenda.val_on_the_day", { date })
                : t("agenda.val_days_after_plan", { date, count: after }),
          );
      const details: CardFactLine[] = [plannedPlain()];
      if (entry.reported_done_day) {
        const when = shortDayTime(entry.reported_done_day, entry.reported_done_time, locale, todayIso);
        details.push(
          line(
            "reported",
            lbl("reported_done"),
            entry.reported_done_by_name
              ? t("agenda.val_on_by", { date: when, name: entry.reported_done_by_name })
              : when,
          ),
        );
      }
      if (entry.manager_checked_day) {
        details.push(
          line(
            "manager_check",
            lbl("manager_check"),
            entry.manager_checked_by_name
              ? t("agenda.val_on_by", { date: day(entry.manager_checked_day), name: entry.manager_checked_by_name })
              : day(entry.manager_checked_day),
          ),
        );
      }
      if (entry.approved_day) {
        // P-15 §0.3 — an on-behalf approval is the MANAGER's check
        // counting as the sign-off, and says so; never a provider's
        // hand presented as the customer's.
        details.push(
          line(
            "approval",
            lbl("customer_approval"),
            entry.approved_on_behalf
              ? t("agenda.val_approved_on_behalf", {
                  date: day(entry.approved_day),
                  name: entry.approved_by_name ?? t("agenda.val_the_manager"),
                })
              : entry.approved_by_name
                ? t("agenda.val_on_by", { date: day(entry.approved_day), name: entry.approved_by_name })
                : day(entry.approved_day),
          ),
        );
      }
      details.push(created());
      return {
        state,
        lines: [...(finished ? [finished] : []), deadlineSettled(), people()],
        details,
      };
    }
    case "blocked":
      return { state, lines: [], details: [] };
  }
}

/** The facts as ONE sentence ("Planned Wed 26 Aug · Deadline none ·
 *  People Ahmet") for the surfaces that print a line rather than a
 *  list — the ticket detail's header. Same facts, same words. */
export function cardFactSentence(entry: WorkPlanEntry, todayIso: string, t: TFunction): string {
  return cardFacts(entry, todayIso, t)
    .lines.map((row) => `${row.label} ${row.value}`)
    .join(" · ");
}
