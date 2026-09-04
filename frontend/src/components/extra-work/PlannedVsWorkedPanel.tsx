/**
 * hours2 Part 1b — "Planned vs worked", on the job.
 *
 *    Design law: plan proposes, worked confirms; one record
 *    (`TimeEntry`), two doors. Hours COMPARISON lives on the job;
 *    money analysis stays in Reports.
 *
 * This file used to be `ExtraWorkHoursPanel` — the "Hours on this
 * extra work" card on the Extra Work detail page, with a worker x day
 * x hour-type grid, a budget roll-up and a labour-cost block. It moved
 * to where hours live (the operational ticket's Plan tab) and was
 * stripped to the columns that belong there:
 *
 *   Person | Planned | Worked | Difference | Weighted
 *
 * No labour cost, no rates, no travel — hours only. The money block did
 * not move: a cost on the job page is analysis, and analysis is the
 * Reports page's job.
 *
 * ## The two sides, and where each comes from
 *
 * PLANNED is `ExtraWorkPlannedHours` — the rows `PlanWorkDialog` writes
 * through `POST /api/extra-work/<id>/plan/` (`planned_hours[]`) and the
 * ticket page already reads back as `ExtraWorkRequestDetail.
 * planned_hours` (`ExtraWorkPlannedHoursRow.hours`, one row per person
 * per day per hour type). This panel is handed those rows and sums them
 * per person; it never fetches the plan itself, so it cannot disagree
 * with the "Planned hours" card beside it about what the plan says.
 *
 * WORKED is the timesheets summary narrowed to this ticket —
 * `GET /api/timesheets/summary/?source_type=TICKET&source_id=<id>` —
 * whose `by_employee` buckets are summed server-side over EVERY row
 * (never a page of them) and carry the weighted figure from each row's
 * `multiplier_snapshot`. That is the same endpoint every other total in
 * the hours module comes from, so a number here is the number the
 * admin grid shows.
 *
 * ## Whose rows
 *
 * The summary applies `restrict_entries_to_self` before any filter, so
 * a BUILDING_MANAGER reads their own line and nothing else. The page
 * says so (`selfOnly`) rather than letting one person's row be read as
 * the crew's.
 *
 * ## Overrun warns, never blocks
 *
 * A worked figure above the plan takes the standard warn tone
 * (`.ew-hours-tone-over`, the WAITING ink — "an overrun is a warning,
 * and the plan is explicit that we warn and never block"). Nothing here
 * disables anything.
 *
 * ## Nulls are "not planned", never zero
 *
 * Somebody who worked without being planned reads "—" in the Planned
 * column and no difference: a 0,00 there would claim we planned them
 * for nothing, which is a decision rather than the absence of one. A
 * person on the plan who has booked nothing reads a real 0,00 worked —
 * that is exactly the row a manager opens this panel to find.
 *
 * ## Arithmetic, and why there is some
 *
 * The old panel did none ("every figure is a fixed 2dp string the
 * server computed"). This one sums planned rows per person and takes
 * worked-minus-planned, because the two sides come from two modules
 * that may not import each other and no endpoint may join them for a
 * TICKET-tagged row. It is done in hundredths, as integers, the way
 * `lib/isoWeek.sumDecimalStrings` does — never in floats.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { fetchTimesheetSummary } from "../../api/timesheets";
import type { TimesheetSummary } from "../../api/timesheets.types";
import type { ExtraWorkPlannedHoursRow } from "../../api/types";
import { formatNumber } from "../../lib/intl";

/** A 2dp decimal string -> integer hundredths. Unparseable is 0. */
function hundredths(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const numeric = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.round(numeric * 100);
}

/** Integer hundredths -> the localised 2dp figure. */
function hours(value: number): string {
  return formatNumber(value / 100, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

interface PersonRow {
  id: number;
  name: string;
  /** null = not planned. */
  planned: number | null;
  worked: number;
  weighted: number;
}

type WorkedState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; summary: TimesheetSummary };

export function PlannedVsWorkedPanel({
  ticketId,
  companyId,
  planned,
  selfOnly,
  canBook,
  onBook,
  canPlan = false,
  onPlan,
  planLoading = false,
  crewIds = null,
  refreshNonce,
  planError = null,
}: {
  ticketId: number;
  companyId: number;
  /** The plan's rows, as the ticket page already holds them. `null`
   *  while the plan is still being read (an Extra Work ticket whose
   *  detail has not landed yet); an empty array for a ticket with no
   *  plan store at all. */
  planned: ExtraWorkPlannedHoursRow[] | null;
  /** The viewer reads only their own worked line (a BUILDING_MANAGER). */
  selfOnly: boolean;
  /** Whether the "Enter hours worked" door is offered to this viewer. */
  canBook: boolean;
  onBook: () => void;
  /** W-HOURS5 Task 4 — the "Plan the work" door lives in this card's
   *  header too, beside "Enter hours worked", both the same weight.
   *  Same handler and gate as the page header's button. */
  canPlan?: boolean;
  onPlan?: () => void;
  planLoading?: boolean;
  /** W-HOURS5 Task 2 — who is on the job's crew NOW (the plan's
   *  `ExtraWorkAssignment` user ids). A person with planned or worked
   *  hours who is not in it is marked "no longer assigned": their past
   *  plan is history and stays, and the mark says why the row is
   *  still here. `null` = unknown, no marks. */
  crewIds?: number[] | null;
  /** Bumped by the page after a booking so the worked side re-reads
   *  without a reload. */
  refreshNonce: number;
  /** W-FIX1 C3 (audit F33) — the plan read failed: say so, never load
   *  forever. */
  planError?: string | null;
}) {
  // Bound like every page: the page namespace first, `common` behind
  // it (`nsMode: "fallback"`), so the hour-type slot labels and the
  // shared verbs resolve from common.json.
  const { t } = useTranslation(["ticket_detail", "common"]);
  const [worked, setWorked] = useState<WorkedState>({ kind: "loading" });

  // ONE state value, never set synchronously in the effect body: the
  // initial value IS the loading state, and every later transition
  // happens in an async callback. A new nonce (a booking just landed)
  // keeps the last table on screen until the re-read lands, then
  // replaces it whole — the figures never mix two reads, and nothing
  // flashes to "Loading…" over a table the reader was looking at.
  useEffect(() => {
    let cancelled = false;
    fetchTimesheetSummary({
      company: companyId,
      source_type: "TICKET",
      source_id: ticketId,
    })
      .then((summary) => {
        if (!cancelled) setWorked({ kind: "ready", summary });
      })
      .catch((err) => {
        if (!cancelled) setWorked({ kind: "error", message: getApiError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId, companyId, refreshNonce]);

  /* W-HOURS5 Task 4 — ONE home for the two doors: title left, and on
     the right "Plan the work" and "Enter hours worked" as EQUAL-weight
     primaries (both green). The in-tab button that used to sit above
     this card is gone; the page header's own "Plan the work" stays. */
  const header = (
    <div className="ew-hours-compare-head">
      <div className="form-section-title">{t("hours_compare.title")}</div>
      {(canBook || (canPlan && onPlan)) && (
        <div
          style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
          data-testid="ticket-hours-compare-actions"
        >
          {canPlan && onPlan && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onPlan}
              disabled={planLoading}
              data-testid="ticket-ew-plan-open-card"
            >
              {planLoading ? t("ew_plan_loading") : t("ew_plan_button")}
            </button>
          )}
          {canBook && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onBook}
              data-testid="ticket-book-hours-open"
            >
              {t("hours_compare.book_button")}
            </button>
          )}
        </div>
      )}
    </div>
  );

  if (worked.kind === "error") {
    return (
      <div className="card" data-testid="ticket-hours-compare">
        <div className="form-section">
          {header}
          <p className="form-error" data-testid="ticket-hours-compare-error">
            {t("hours_compare.load_error")} {worked.message}
          </p>
        </div>
      </div>
    );
  }

  if (planError) {
    return (
      <div className="card" data-testid="ticket-hours-compare">
        <div className="form-section">
          {header}
          <p className="form-error" data-testid="ticket-hours-compare-plan-error">
            {t("hours_compare.plan_error")} {planError}
          </p>
        </div>
      </div>
    );
  }

  if (worked.kind === "loading" || planned === null) {
    return (
      <div className="card" data-testid="ticket-hours-compare">
        <div className="form-section">
          {header}
          <p className="muted small" data-testid="ticket-hours-compare-loading">
            {t("hours_compare.loading")}
          </p>
        </div>
      </div>
    );
  }

  const summary = worked.summary;

  // ---- one row per person on EITHER side ---------------------------
  //
  // The union, not the plan: somebody who worked the job without being
  // planned onto it is precisely the case a manager is looking for.
  const people = new Map<number, PersonRow>();
  for (const row of planned) {
    const existing = people.get(row.user_id);
    const share = hundredths(row.hours);
    if (existing) {
      existing.planned = (existing.planned ?? 0) + share;
    } else {
      people.set(row.user_id, {
        id: row.user_id,
        name: row.user_full_name || row.user_email,
        planned: share,
        worked: 0,
        weighted: 0,
      });
    }
  }
  for (const bucket of summary.by_employee) {
    const existing = people.get(bucket.employee);
    if (existing) {
      existing.worked = hundredths(bucket.hours);
      existing.weighted = hundredths(bucket.weighted_hours);
    } else {
      people.set(bucket.employee, {
        id: bucket.employee,
        name: bucket.employee_name,
        planned: null,
        worked: hundredths(bucket.hours),
        weighted: hundredths(bucket.weighted_hours),
      });
    }
  }
  const rows = [...people.values()].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  const hasPlan = planned.length > 0;
  const plannedTotal = hasPlan
    ? rows.reduce((sum, row) => sum + (row.planned ?? 0), 0)
    : null;
  const workedTotal = hundredths(summary.total_hours);
  const weightedTotal = hundredths(summary.total_weighted_hours);
  const noHours = summary.total_entries === 0;

  const difference = (row: { planned: number | null; worked: number }) =>
    row.planned === null ? null : row.worked - row.planned;
  const diffCell = (value: number | null, testId: string) => {
    if (value === null) {
      return (
        <td className="ew-hours-num muted" data-testid={testId}>
          —
        </td>
      );
    }
    // The sign is in the figure; the tone is a second signal on top of
    // it. Over the plan is a WARNING (the waiting ink), never a block.
    const tone = value > 0 ? "over" : value < 0 ? "under" : "on";
    return (
      <td
        className={`ew-hours-num ew-hours-tone-${tone}`}
        data-testid={testId}
        data-tone={tone}
      >
        {value > 0 ? "+" : ""}
        {hours(value)}
      </td>
    );
  };

  return (
    <div className="card" data-testid="ticket-hours-compare">
      <div className="form-section">
        {header}
        {selfOnly && !noHours && (
          <p className="form-hint" data-testid="ticket-hours-compare-self-only">
            {t("hours_compare.self_only")}
          </p>
        )}
        {noHours && !hasPlan ? (
          /* W-FIX1 A2 (audit F2) — a PLAN is content. This keyed on
             worked entries alone, so ticket 373 read "No hours booked
             yet" while the server held 4.00 planned hours for a person
             no longer on the crew. The table renders whenever either
             side has something to say; a removed person's past plan
             stays and is marked below (the W-HOURS5 ruling). */
          /* 1c — ONE state line. The old empty panel explained the
             timesheets module in four sentences; here the door is the
             button beside the title. */
          <p className="muted small" data-testid="ticket-hours-compare-empty">
            {t("hours_compare.empty")}
          </p>
        ) : (
          <div className="table-wrap">
            <table
              className="table ew-hours-table ew-hours-compare-table"
              data-testid="ticket-hours-compare-table"
            >
              <thead>
                <tr>
                  <th>{t("hours_compare.col_person")}</th>
                  <th className="ew-hours-num">{t("hours_compare.col_planned")}</th>
                  <th className="ew-hours-num">{t("hours_compare.col_worked")}</th>
                  <th className="ew-hours-num">
                    {t("hours_compare.col_difference")}
                  </th>
                  <th className="ew-hours-num">{t("hours_compare.col_weighted")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    data-testid="ticket-hours-compare-row"
                    data-employee-id={row.id}
                  >
                    <td>
                      {row.name}
                      {crewIds !== null && !crewIds.includes(row.id) && (
                        /* W-HOURS5 Task 2 — the ruling: a removed
                           person's past plan stays, and the row says
                           why it is still here. */
                        <span
                          className="muted small"
                          style={{ marginLeft: 6 }}
                          data-testid="ticket-hours-compare-unassigned"
                        >
                          ({t("hours_compare.no_longer_assigned")})
                        </span>
                      )}
                    </td>
                    <td className="ew-hours-num">
                      {row.planned === null ? (
                        <span
                          className="muted"
                          title={t("hours_compare.not_planned")}
                        >
                          —
                        </span>
                      ) : (
                        hours(row.planned)
                      )}
                    </td>
                    <td className="ew-hours-num">{hours(row.worked)}</td>
                    {diffCell(difference(row), "ticket-hours-compare-diff")}
                    <td className="ew-hours-num">{hours(row.weighted)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr data-testid="ticket-hours-compare-totals">
                  <td>{t("hours_compare.total")}</td>
                  <td className="ew-hours-num">
                    <strong>
                      {plannedTotal === null ? "—" : hours(plannedTotal)}
                    </strong>
                  </td>
                  <td className="ew-hours-num">
                    <strong data-testid="ticket-hours-compare-worked-total">
                      {hours(workedTotal)}
                    </strong>
                  </td>
                  {diffCell(
                    plannedTotal === null ? null : workedTotal - plannedTotal,
                    "ticket-hours-compare-diff-total",
                  )}
                  <td className="ew-hours-num">
                    <strong>{hours(weightedTotal)}</strong>
                  </td>
                </tr>
              </tfoot>
            </table>
            {/* Weighted is a payroll instrument (hours times the hour
                type's factor), not a second measure of the plan. Said
                once, under the table, so nobody compares it to Planned. */}
            <p className="muted small ew-hours-compare-note">
              {t("hours_compare.weighted_hint")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
