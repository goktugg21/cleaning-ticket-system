/**
 * W7 — ONE panel: who was planned for how many hours, and how many they
 * worked.
 *
 *     The owner: "If I enter who is supposed to work how many hours, I
 *     need to be able to see that information in the operational ticket
 *     as well. If the work is completed, I need to be able to compare: I
 *     planned this person for X hours. How many hours did they actually
 *     work?"
 *
 * And: "Right now the user has to jump between Tickets, Extra Work,
 * Hours, Contracts, Chargeable Work... that is becoming confusing." That
 * second sentence is why this is a COMPONENT and not a page. It is one
 * answer, mounted wherever the question gets asked.
 *
 * ## It reads without a legend, and that is the whole design
 *
 * The difference column carries a WORD, not a sign: "2,50 more",
 * "2,00 less", "same". A "+2,50" would need somebody to explain which
 * direction plus meant, and an explanation on screen means the design
 * failed. One colour, one meaning: over plan is tinted, nothing else is.
 * Under plan is deliberately NOT green — unfinished work also reads as
 * under plan, and the panel must not congratulate anyone for it.
 *
 * ## Never a zero it did not earn
 *
 * A person nobody planned reads "not planned", not 0,00 — writing zero
 * would state that we planned them for nothing, which is a decision
 * rather than the absence of one. A job nobody has been planned on says
 * so in place of the table.
 *
 * A WORKED figure of 0,00 is printed as 0,00: somebody is on the plan
 * and has booked nothing, which is precisely what a manager opens this
 * to find.
 *
 * ## Whose hours
 *
 * The server decides and says which answer it gave. SUPER_ADMIN and
 * COMPANY_ADMIN get the crew; BUILDING_MANAGER and STAFF get their own
 * line. On a self answer the panel titles itself "My planned and worked
 * hours" and drops the job total — because one person's row under a
 * crew heading, or beside a total that equals it, is a screen that
 * misleads without saying anything false.
 *
 * Customers never reach the endpoint at all.
 */
import { Fragment, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import {
  fetchPlannedVsActual,
  type PlannedVsActualReport,
} from "../api/plannedVsActual";
import { formatNumber } from "../lib/intl";
import { RecordHoursOnRow } from "./RecordHoursOnRow";

const HOURS = { minimumFractionDigits: 2, maximumFractionDigits: 2 };

export function PlannedVsActualHours({
  extraWorkId,
  testId = "planned-vs-actual",
}: {
  extraWorkId: number;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  const [report, setReport] = useState<PlannedVsActualReport | null>(null);
  const [error, setError] = useState("");
  // Starts TRUE and is only ever turned off. The panel is fetching from
  // its first render, so a false here would flash "nobody is planned"
  // before the answer lands — and a `setLoading(true)` inside the effect
  // body is the cascading-render the React Compiler rule refuses.
  //
  // Which leaves the question the reset was for: what happens when
  // `extraWorkId` changes under a mounted panel? It cannot. The mount
  // site keys this component by that id, which is what CLAUDE.md
  // prescribes for prop-derived state, so a different job is a different
  // component and starts true again.
  const [loading, setLoading] = useState(true);
  /** W9 — which row has its hour entry open. One at a time: two open
   *  forms on one table is two places to type the same fact. */
  const [recordingFor, setRecordingFor] = useState<number | null>(null);
  /** Bumped after a save so the table re-reads in place. The user
   *  never leaves the page, which is the whole point. */
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchPlannedVsActual(extraWorkId)
      .then((data) => {
        if (cancelled) return;
        setReport(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [extraWorkId, reloadKey]);

  const isSelf = report?.visibility === "self";
  const title = isSelf
    ? t("planned_vs_actual.title_self")
    : t("planned_vs_actual.title");

  /** The difference cell: a word, never a sign. */
  const difference = (value: string | null) => {
    if (value === null) {
      // An em dash, NOT "not planned" again: the Planned cell in this
      // same row already says that, and a row that says one thing twice
      // reads as two facts.
      return (
        <span className="pva-diff pva-diff-none" aria-hidden="true">
          —
        </span>
      );
    }
    const numeric = Number.parseFloat(value);
    if (!Number.isFinite(numeric) || numeric === 0) {
      return (
        <span className="pva-diff pva-diff-same">
          {t("planned_vs_actual.same")}
        </span>
      );
    }
    const hours = formatNumber(Math.abs(numeric), HOURS);
    return numeric > 0 ? (
      <span className="pva-diff pva-diff-over">
        {t("planned_vs_actual.more", { hours })}
      </span>
    ) : (
      <span className="pva-diff pva-diff-under">
        {t("planned_vs_actual.less", { hours })}
      </span>
    );
  };

  return (
    <div className="card" data-testid={testId}>
      <div className="section-head">
        <div>
          <div className="section-head-title">{title}</div>
        </div>
      </div>
      <div className="pva-body">
        {loading ? (
          <p className="muted small">{t("loading")}</p>
        ) : error ? (
          <p className="muted small" role="alert">
            {error}
          </p>
        ) : !report || report.people.length === 0 ? (
          <p className="muted small" data-testid={`${testId}-empty`}>
            {isSelf
              ? t("planned_vs_actual.empty_self")
              : t("planned_vs_actual.empty")}
          </p>
        ) : (
          <table className="data-table pva-table">
            <thead>
              <tr>
                <th>{t("planned_vs_actual.col_person")}</th>
                <th className="pva-num">
                  {t("planned_vs_actual.col_planned")}
                </th>
                <th className="pva-num">
                  {t("planned_vs_actual.col_worked")}
                </th>
                <th>{t("planned_vs_actual.col_difference")}</th>
                <th className="pva-action" />
              </tr>
            </thead>
            <tbody>
              {report.people.map((person) => (
                <Fragment key={person.employee_id}>
                  <tr data-testid={`${testId}-row`}>
                    <td>{person.employee_name}</td>
                    <td className="pva-num">
                      {person.planned_hours === null ? (
                        <span className="muted">
                          {t("planned_vs_actual.not_planned")}
                        </span>
                      ) : (
                        formatNumber(person.planned_hours, HOURS)
                      )}
                    </td>
                    <td className="pva-num">
                      {formatNumber(person.actual_hours, HOURS)}
                    </td>
                    <td>{difference(person.difference_hours)}</td>
                    {/* W9 — the control that closes the gap, on the row
                        that shows it. Person, job and building are
                        already known and are never asked for. */}
                    <td className="pva-action">
                      {person.can_record_hours &&
                        recordingFor !== person.employee_id && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => setRecordingFor(person.employee_id)}
                            data-testid={`${testId}-record-${person.employee_id}`}
                          >
                            {t("record_hours.open")}
                          </button>
                        )}
                    </td>
                  </tr>
                  {recordingFor === person.employee_id && (
                    <tr data-testid={`${testId}-record-row`}>
                      <td colSpan={5}>
                        <RecordHoursOnRow
                          employeeId={person.employee_id}
                          employeeName={person.employee_name}
                          extraWorkId={extraWorkId}
                          buildingId={report.building_id}
                          companyId={report.company_id}
                          onSaved={() => {
                            setRecordingFor(null);
                            setReloadKey((n) => n + 1);
                          }}
                          onCancel={() => setRecordingFor(null)}
                          testId={`${testId}-record-form`}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
            {/* The job total, only where it means something. On a self
                answer it would just repeat the one row above it. */}
            {!isSelf && (
              <tfoot>
                <tr data-testid={`${testId}-total`}>
                  <td>{t("planned_vs_actual.whole_job")}</td>
                  <td className="pva-num">
                    {report.totals.planned_hours === null ? (
                      <span className="muted">
                        {t("planned_vs_actual.not_planned")}
                      </span>
                    ) : (
                      formatNumber(report.totals.planned_hours, HOURS)
                    )}
                  </td>
                  <td className="pva-num">
                    {formatNumber(report.totals.actual_hours, HOURS)}
                  </td>
                  <td>{difference(report.totals.difference_hours)}</td>
                  <td className="pva-action" />
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>
    </div>
  );
}
