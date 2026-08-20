/**
 * W3-H (`docs/planning/ew-gap-closing-plan.md` §2.8) — the hours panel.
 * W4-N fix 2 — a COLLAPSIBLE card, closed by default, whose collapsed
 * header carries the over/under-budget figure.
 *
 * ## W8 §4 — it is a plain OPEN card
 *
 * It used to be a `CollapsibleCard`, closed by default, on the argument
 * that it matched the requested-services card. Once the page became
 * tabs this card WAS the whole Hours tab, so the tab rendered as an
 * empty page with one button on it. Nothing here is optional detail a
 * reader should have to ask for.
 *
 * `variance_hours` is `entered - budget`, computed once, on the server
 * (`backend/reports/extra_work_hours.py`). Positive is over. It is
 * `null` when the job was never budgeted, and that case reads "no
 * budget to measure against" — NOT "0,00 over budget", which would
 * claim the crew landed exactly on a number nobody ever set. An actual
 * zero variance is a fourth, different sentence ("exactly on budget"),
 * because a job that hit its budget and a job that has no budget are
 * not the same fact. Same rule the money strip next door follows:
 * "unpriced" and "costs nothing" never render alike.
 *
 * ## The open state groups the figures by what they ARE
 *
 * W3-H drew five equal boxes in a row — Budget, Entered, Weighted,
 * Labour cost, Travel — which said "five facts of one kind" when they
 * are three kinds:
 *
 *   - Budget and Entered are ONE comparison, so they render as one:
 *     two sides of a single block with the arrow between them and the
 *     variance sentence underneath, reading left to right as "we
 *     planned this, we booked that, here is the gap".
 *   - Weighted is a DERIVATION of Entered, so it is subordinate to it —
 *     a quiet line under the comparison, not a peer of it.
 *   - Labour cost and Travel are MONEY, which the timesheets module
 *     refuses to touch on purpose. They get their own tinted group with
 *     its own heading, so nothing about a euro is dressed like an hour.
 *
 * ## The sentence under the heading is a requirement, not decoration
 *
 * Decision 12 in the plan: "the UI must say where each number comes
 * from — the hours screen states plainly that hours live in timesheets
 * and cost is computed in reporting, so nobody hunts for a wage field
 * that does not exist." That is `hours_panel.where_numbers_live`. It
 * moved into the open state with the rest of the body (the card is
 * closed by default now, and a line nobody can see is worse than a
 * short one), and it is still the first thing in that body, above every
 * figure it explains. It is not a tooltip: somebody looking for a rate
 * field will not hover a thing they do not know is there.
 *
 * ## Why this is not `HoursWeekGrid`
 *
 * `components/timesheets/HoursWeekGrid.tsx` is an EDITOR: it is bound to
 * one ISO week, takes hour types, buildings, a save handler and dirty
 * tracking, and writes `TimeEntry` rows through the week-grid endpoint.
 * This panel is a read-only roll-up on a detail page, and a job's hours
 * are not one week's — a fortnight of work has fourteen day columns and
 * no week to be bound to. Mounting the editor here would mean feeding
 * it props it does not have and suppressing its save; the honest answer
 * is a table that reads. What IS reused is the shared vocabulary — the
 * server's 2dp strings, `formatNumber` / `formatMoney`, `BoundedList` —
 * so nothing about hours or money is formatted a second way.
 *
 * ## Every null renders as an em dash with a reason
 *
 * A cost of EUR 0,00 would claim the job was free. So: no rate
 * configured, or an actor who may not see cost, prints the dash and the
 * sentence that says which of the two it is.
 *
 * ## This component does no arithmetic
 *
 * Every figure is a fixed 2dp string the server computed — the totals,
 * the variance, the cost. `Math.abs` on the variance is the single
 * exception and it is not a calculation: the sign has already been read
 * to choose the word "over" or "under", so printing it again would say
 * the direction twice and contradict it once. Adding even a subtotal
 * here would be a second place that decides what an hour or a euro is.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { fetchExtraWorkHours } from "../../api/extraWorkHours";
import type { ExtraWorkHoursReport } from "../../api/extraWorkHours";
import { useAuth } from "../../auth/AuthContext";
import { isProviderManagementRole } from "../../auth/permissions";
import { formatDate, formatMoney, formatNumber } from "../../lib/intl";
import { BoundedList } from "../BoundedList";

/** Hours on the wire are 2dp strings; this only localises the separator. */
function hours(value: string | null): string {
  return formatNumber(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * The variance sentence. Sign decides the WORDING, never a colour
 * alone — the colour below is a second signal on top of a sentence that
 * already says which way it went.
 *
 * `null` in, `null` out: no budget was set, and the caller renders the
 * "nothing to measure against" wording rather than a zero.
 */
function varianceKey(variance: string | null): {
  key: string;
  hours: string;
  tone: "over" | "under" | "on";
} | null {
  if (variance === null) return null;
  const numeric = Number.parseFloat(variance);
  if (!Number.isFinite(numeric)) return null;
  if (numeric === 0) {
    return { key: "hours_panel.variance_on", hours: "0", tone: "on" };
  }
  return {
    key:
      numeric > 0
        ? "hours_panel.variance_over"
        : "hours_panel.variance_under",
    hours: formatNumber(Math.abs(numeric), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
    tone: numeric > 0 ? "over" : "under",
  };
}

/**
 * ONE state value, not three booleans, and never set synchronously
 * inside the effect body — CLAUDE.md's frontend convention, and
 * `react-hooks/set-state-in-effect` enforces it. The initial value IS
 * the loading state, so nothing has to be assigned to enter it; every
 * later transition happens in an async callback, which is not the
 * effect body.
 *
 * The panel is mounted for ONE extra work on its own detail page, so
 * there is no prop-derived resync to key around: a different job is a
 * different page and a fresh mount.
 */
type PanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; report: ExtraWorkHoursReport };

export function ExtraWorkHoursPanel({ extraWorkId }: { extraWorkId: number }) {
  const { t } = useTranslation("extra_work");
  const { me } = useAuth();
  const [state, setState] = useState<PanelState>({ kind: "loading" });

  // The endpoint 403s anybody else, so the gate lives here and a
  // customer-side viewer never issues the request at all.
  const mayRead = isProviderManagementRole(me?.role);

  // The request fires on mount even though the card opens closed: the
  // collapsed HEADER is the variance, so there is nothing to show until
  // it has landed. That is the whole difference between this card and
  // the Preview card, which fetches only when opened because its
  // payload is a PDF nobody wants by default.
  useEffect(() => {
    if (!mayRead) return;
    let cancelled = false;
    fetchExtraWorkHours(extraWorkId)
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", report: data });
      })
      .catch((err) => {
        if (!cancelled) {
          setState({ kind: "error", message: getApiError(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [extraWorkId, mayRead]);

  if (!mayRead || state.kind === "loading") return null;

  if (state.kind === "error") {
    return (
      <div className="card" data-testid="ew-hours-panel">
        <div className="form-section">
          <div className="form-section-title">{t("hours_panel.title")}</div>
          <p className="form-error" data-testid="ew-hours-error">
            {t("hours_panel.load_error")} {state.message}
          </p>
        </div>
      </div>
    );
  }

  const report = state.report;
  const variance = varianceKey(report.rollup.variance_hours);
  // W6-H — the plan rows, in the same order the actual rows use so the
  // two halves of the grid read as one table.
  const plannedByEmployee = report.planned?.by_employee ?? [];
  const cost = report.cost;
  // One string, built once, used in the collapsed header. The volume
  // then the figure — Requested services' own grammar.
  const varianceText =
    variance === null
      ? t("hours_panel.variance_none")
      : t(variance.key, { hours: variance.hours });

  return (
    /* W8 §4 — an OPEN card, not a collapsed one. The Hours tab's only
       content was this card, shut, so the tab was an empty page with a
       button on it. Collapsing was there to fight the nine-card scroll
       the tabs already removed.
       The old collapsed header carried the entered total and the
       variance so you could read them without opening it. Both are in
       the comparison below, larger, so repeating them here would be the
       same number twice on one screen. */
    <div className="card" data-testid="ew-hours-panel">
      <div className="form-section">
        <div className="form-section-title">{t("hours_panel.title")}</div>
      {/* Decision 12: where each number lives, in plain words, above
          the figures it explains and where a person looking for a wage
          field would look. */}
      <p className="form-hint ew-hours-provenance" data-testid="ew-hours-provenance">
        {t("hours_panel.where_numbers_live")}
      </p>

      {report.visibility === "self" && (
        <p className="form-hint" data-testid="ew-hours-self-only">
          {t("hours_panel.self_only")}
        </p>
      )}

      <div className="ew-hours-groups" data-testid="ew-hours-rollup">
        {/* Group one: the planning comparison. Budget and Entered are
            two halves of one question, so they share one box. */}
        <section className="ew-hours-group">
          <h3 className="ew-hours-group-title">
            {t("hours_panel.group_hours_title")}
          </h3>
          <div className="ew-hours-compare">
            <div className="ew-hours-compare-side" data-testid="ew-hours-budget">
              <span className="ew-hours-figure-label">
                {t("hours_panel.budget_label")}
              </span>
              {report.rollup.budget_hours === null ? (
                /* Not a figure, so it is not typeset as one — an
                   unbudgeted job must not look like a budget of zero. */
                <span className="ew-hours-compare-empty">
                  {t("hours_panel.budget_not_set")}
                </span>
              ) : (
                <strong className="ew-hours-figure-value">
                  {hours(report.rollup.budget_hours)}
                </strong>
              )}
            </div>
            <span className="ew-hours-compare-arrow" aria-hidden="true">
              →
            </span>
            <div
              className="ew-hours-compare-side"
              data-testid="ew-hours-entered"
            >
              <span className="ew-hours-figure-label">
                {t("hours_panel.entered_label")}
              </span>
              <strong className="ew-hours-figure-value">
                {hours(report.rollup.entered_hours)}
              </strong>
            </div>
          </div>
          <p
            className={`ew-hours-variance ew-hours-tone-${
              variance?.tone ?? "none"
            }`}
            data-testid="ew-hours-variance"
          >
            {varianceText}
          </p>
          {/* Weighted is Entered times a factor, so it reads as a
              footnote to the comparison rather than a sixth headline. */}
          <div className="ew-hours-derived" data-testid="ew-hours-weighted">
            <span className="ew-hours-derived-label">
              {t("hours_panel.weighted_label")}
            </span>
            <strong className="ew-hours-derived-value">
              {hours(report.rollup.weighted_hours)}
            </strong>
            <span className="ew-hours-derived-hint">
              {t("hours_panel.weighted_hint")}
            </span>
          </div>
        </section>

        {/* Group two: money. Its own heading, its own tint, so a euro
            is never mistaken for an hour on a screen whose whole point
            is that timesheets record one and never the other. */}
        <section className="ew-hours-group ew-hours-group-money">
          <h3 className="ew-hours-group-title">
            {t("hours_panel.group_money_title")}
          </h3>
          <div className="ew-hours-money-row" data-testid="ew-hours-cost">
            <span className="ew-hours-figure-label">
              {t("hours_panel.cost_label")}
            </span>
            <strong className="ew-hours-money-value">
              {/* `formatMoney(null)` is the app's one em dash. A zero
                  here would say the work cost nothing. */}
              {formatMoney(cost?.total_cost ?? null)}
            </strong>
          </div>
          <p className="ew-hours-figure-meta">
            {cost === null
              ? t("hours_panel.cost_hidden")
              : cost.rate_configured
                ? t("hours_panel.cost_rate", {
                    rate: formatMoney(cost.hourly_rate),
                  })
                : t("hours_panel.cost_no_rate")}
          </p>

          {cost !== null && (
            <>
              <div className="ew-hours-money-row" data-testid="ew-hours-travel">
                <span className="ew-hours-figure-label">
                  {t("hours_panel.travel_label")}
                </span>
                <strong className="ew-hours-money-value">
                  {formatMoney(cost.travel_costs)}
                </strong>
              </div>
              <p className="ew-hours-figure-meta">
                {t("hours_panel.travel_hint")}
              </p>
            </>
          )}
        </section>
      </div>

      {report.days_omitted > 0 && (
        <p className="form-hint" data-testid="ew-hours-days-omitted">
          {t("hours_panel.days_omitted", { count: report.days_omitted })}
        </p>
      )}

      {/* CLAUDE.md #8 — a list from a SERVER collection is bounded. Rows
          scroll vertically inside `BoundedList`; the day columns scroll
          horizontally inside `table-wrap`, which is the class that rule
          already pairs with a table. */}
      <BoundedList
        size="md"
        count={report.rows.length}
        ariaLabel={t("hours_panel.grid_aria")}
        testIdPrefix="ew-hours-grid"
        className="table-wrap"
        emptyState={
          <div data-testid="ew-hours-empty">
            <p>{t("hours_panel.empty")}</p>
            <p className="form-hint">{t("hours_panel.empty_hint")}</p>
          </div>
        }
      >
        {report.rows.length > 0 && (
          <table className="table ew-hours-table">
            <thead>
              <tr>
                <th>{t("hours_panel.col_worker")}</th>
                <th>{t("hours_panel.col_hour_type")}</th>
                {report.days.map((day) => (
                  <th key={day} className="ew-hours-day-col">
                    {formatDate(day)}
                  </th>
                ))}
                <th className="ew-hours-day-col">
                  {t("hours_panel.col_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr
                  key={`${row.employee_id}:${row.hour_type_id}`}
                  data-testid="ew-hours-row"
                >
                  <td>{row.employee_name}</td>
                  <td>{row.hour_type_name}</td>
                  {report.days.map((day) => (
                    <td key={day} className="ew-hours-day-col">
                      {/* A day with no hours is blank, not "0,00": the
                          person did not work zero hours, they did not
                          work. */}
                      {row.days[day] ? hours(row.days[day]) : ""}
                    </td>
                  ))}
                  <td className="ew-hours-day-col">
                    <strong>{hours(row.hours)}</strong>
                  </td>
                </tr>
              ))}
              {/* W6-H — the PLAN, on the same day axis, one row per
                  person. Underneath the actuals rather than interleaved
                  with them: the actual rows are split by hour type and
                  a plan has none, so a planned row sitting between two
                  hour-type rows would read as a third type. */}
              {plannedByEmployee.map((planned) => (
                <tr
                  key={`planned:${planned.employee_id}`}
                  className="ew-hours-planned-row"
                  data-testid="ew-hours-planned-row"
                  data-employee-id={planned.employee_id}
                >
                  <td>{planned.employee_name}</td>
                  <td>{t("hours_panel.planned_label")}</td>
                  {report.days.map((day) => (
                    <td key={day} className="ew-hours-day-col">
                      {planned.days[day] ? hours(planned.days[day]) : ""}
                    </td>
                  ))}
                  <td className="ew-hours-day-col">
                    <strong>{hours(planned.hours)}</strong>
                    {/* Planned but not yet placed on a day. Shown on
                        the row it belongs to, because a total that
                        exceeds the visible cells with no explanation is
                        the reference system's §4.4 defect. */}
                    {Number(planned.undated_hours) > 0 && (
                      <span
                        className="muted small ew-hours-undated"
                        data-testid="ew-hours-planned-undated"
                      >
                        {" "}
                        {t("hours_panel.planned_undated", {
                          hours: hours(planned.undated_hours),
                        })}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>{t("hours_panel.col_total")}</td>
                {report.days.map((day) => (
                  <td key={day} className="ew-hours-day-col" />
                ))}
                <td className="ew-hours-day-col">
                  <strong data-testid="ew-hours-total">
                    {hours(report.totals.hours)}
                  </strong>
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </BoundedList>
      </div>
    </div>
  );
}
