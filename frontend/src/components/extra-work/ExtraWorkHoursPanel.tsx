/**
 * W3-H (`docs/planning/ew-gap-closing-plan.md` §2.8) — the hours panel.
 *
 * Two halves, in this order:
 *
 *   1. **The roll-up** — budget hours, hours entered, and labour cost,
 *      side by side. Planned against actual is the comparison the owner
 *      asked for and the one the reference system cannot make at all:
 *      over there `hours_planed` is written by six code paths and read
 *      by nothing that decides anything.
 *   2. **The grid** — worker x day x hour type, read-only, for the hours
 *      already booked to this job.
 *
 * ## The sentence under the heading is a requirement, not decoration
 *
 * Decision 12 in the plan: "the UI must say where each number comes
 * from — the hours screen states plainly that hours live in timesheets
 * and cost is computed in reporting, so nobody hunts for a wage field
 * that does not exist." That is `hours_panel.where_numbers_live`, one
 * line, directly under the title. It is not a tooltip: somebody looking
 * for a rate field will not hover a thing they do not know is there.
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
 * sentence that says which of the two it is. Same rule the money strip
 * next door already follows for unpriced work.
 *
 * ## This component does no arithmetic
 *
 * Every figure is a fixed 2dp string the server computed — the totals,
 * the variance, the cost. Adding even a subtotal here would be a second
 * place that decides what an hour or a euro is.
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

/** The variance sentence. Sign decides the wording, never a colour alone. */
function varianceKey(variance: string | null): {
  key: string;
  hours: string;
} | null {
  if (variance === null) return null;
  const numeric = Number.parseFloat(variance);
  if (!Number.isFinite(numeric)) return null;
  if (numeric === 0) return { key: "hours_panel.variance_on", hours: "0" };
  return {
    key:
      numeric > 0
        ? "hours_panel.variance_over"
        : "hours_panel.variance_under",
    // The magnitude — the direction is in the sentence, so a minus sign
    // in front of "under budget" would say it twice and contradict once.
    hours: formatNumber(Math.abs(numeric), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
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
      <div className="card" style={{ marginBottom: 16 }} data-testid="ew-hours-panel">
        <h2 className="card-title">{t("hours_panel.title")}</h2>
        <p className="form-error" data-testid="ew-hours-error">
          {t("hours_panel.load_error")} {state.message}
        </p>
      </div>
    );
  }

  const report = state.report;
  const variance = varianceKey(report.rollup.variance_hours);
  const cost = report.cost;

  return (
    <div className="card" style={{ marginBottom: 16 }} data-testid="ew-hours-panel">
      <h2 className="card-title">{t("hours_panel.title")}</h2>
      {/* Decision 12: where each number lives, in plain words, where a
          person looking for a wage field would look. */}
      <p className="form-hint" data-testid="ew-hours-provenance">
        {t("hours_panel.where_numbers_live")}
      </p>

      {report.visibility === "self" && (
        <p className="form-hint" data-testid="ew-hours-self-only">
          {t("hours_panel.self_only")}
        </p>
      )}

      <div className="ew-hours-rollup" data-testid="ew-hours-rollup">
        <div className="ew-hours-figure" data-testid="ew-hours-budget">
          <span className="ew-hours-figure-label">
            {t("hours_panel.budget_label")}
          </span>
          <strong className="ew-hours-figure-value">
            {report.rollup.budget_hours === null
              ? t("hours_panel.budget_not_set")
              : hours(report.rollup.budget_hours)}
          </strong>
        </div>

        <div className="ew-hours-figure" data-testid="ew-hours-entered">
          <span className="ew-hours-figure-label">
            {t("hours_panel.entered_label")}
          </span>
          <strong className="ew-hours-figure-value">
            {hours(report.rollup.entered_hours)}
          </strong>
          <span className="ew-hours-figure-meta">
            {variance === null
              ? t("hours_panel.variance_none")
              : t(variance.key, { hours: variance.hours })}
          </span>
        </div>

        <div className="ew-hours-figure" data-testid="ew-hours-weighted">
          <span className="ew-hours-figure-label">
            {t("hours_panel.weighted_label")}
          </span>
          <strong className="ew-hours-figure-value">
            {hours(report.rollup.weighted_hours)}
          </strong>
          <span className="ew-hours-figure-meta">
            {t("hours_panel.weighted_hint")}
          </span>
        </div>

        <div className="ew-hours-figure" data-testid="ew-hours-cost">
          <span className="ew-hours-figure-label">
            {t("hours_panel.cost_label")}
          </span>
          <strong className="ew-hours-figure-value">
            {/* `formatMoney(null)` is the app's one em dash. A zero here
                would say the work cost nothing. */}
            {formatMoney(cost?.total_cost ?? null)}
          </strong>
          <span className="ew-hours-figure-meta">
            {cost === null
              ? t("hours_panel.cost_hidden")
              : cost.rate_configured
                ? t("hours_panel.cost_rate", {
                    rate: formatMoney(cost.hourly_rate),
                  })
                : t("hours_panel.cost_no_rate")}
          </span>
        </div>

        {cost !== null && (
          <div className="ew-hours-figure" data-testid="ew-hours-travel">
            <span className="ew-hours-figure-label">
              {t("hours_panel.travel_label")}
            </span>
            <strong className="ew-hours-figure-value">
              {formatMoney(cost.travel_costs)}
            </strong>
            <span className="ew-hours-figure-meta">
              {t("hours_panel.travel_hint")}
            </span>
          </div>
        )}
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
  );
}
