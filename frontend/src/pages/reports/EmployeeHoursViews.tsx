import { useTranslation } from "react-i18next";

import { PeriodReportView } from "./PeriodReportView";
import type { PeriodPayload } from "./PeriodReportView";

/**
 * Sprint 178 §2 — the three employee-hours reports and the ticket report.
 *
 * Four views in one file because each is a table and nothing else: the
 * period picker, the fetch, the CSV and the PDF all live in
 * `PeriodReportView`. Splitting four ~40-line tables across four files
 * would be four imports for no separation.
 */

const DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

interface ByBuildingPayload extends PeriodPayload {
  buildings: {
    building: number | null;
    building_name: string | null;
    total: string;
    employees: { employee: number; employee_name: string; hours: string }[];
  }[];
}

export function EmployeeHoursByBuildingView() {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<ByBuildingPayload>
      endpoint="/reports/employee-hours-by-building/"
      stem="employee-hours-by-building"
      emptyHint={t("employee_hours_building_empty")}
      testIdPrefix="employee-hours-building"
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.buildings.map((bucket) => (
            <div key={bucket.building ?? "none"} style={{ marginBottom: 16 }}>
              <div className="form-section-title">
                {/* A null building is a real bucket, not a bug — hours
                    can be logged against no location by design. */}
                {bucket.building_name ?? t("no_building")} —{" "}
                {bucket.total}
              </div>
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("employee")}</th>
                    <th className="contract-num">{t("hours")}</th>
                  </tr>
                </thead>
                <tbody>
                  {bucket.employees.map((employee) => (
                    <tr key={employee.employee}>
                      <td>{employee.employee_name}</td>
                      <td className="contract-num">{employee.hours}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p className="muted small">
            {t("grand_total")}: {payload.total}
          </p>
        </div>
      )}
    </PeriodReportView>
  );
}

interface WeeklyPayload extends PeriodPayload {
  weeks: {
    iso_year: number;
    iso_week: number;
    total: string;
    employees: {
      employee: number;
      employee_name: string;
      days: Record<string, string>;
      total: string;
    }[];
  }[];
}

export function EmployeeHoursWeeklyView() {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<WeeklyPayload>
      endpoint="/reports/employee-hours-weekly/"
      stem="employee-hours-weekly"
      emptyHint={t("employee_hours_weekly_empty")}
      testIdPrefix="employee-hours-weekly"
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.weeks.map((week) => (
            <div
              key={`${week.iso_year}-${week.iso_week}`}
              style={{ marginBottom: 16 }}
            >
              <div className="form-section-title">
                {t("week_label", {
                  year: week.iso_year,
                  week: week.iso_week,
                })}{" "}
                — {week.total}
              </div>
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("employee")}</th>
                    {DAYS.map((day) => (
                      <th key={day} className="contract-num">
                        {t(`common:contract_hours.day_${day}`)}
                      </th>
                    ))}
                    <th className="contract-num">{t("total")}</th>
                  </tr>
                </thead>
                <tbody>
                  {week.employees.map((employee) => (
                    <tr key={employee.employee}>
                      <td>{employee.employee_name}</td>
                      {DAYS.map((day) => (
                        <td key={day} className="contract-num">
                          {employee.days[day]}
                        </td>
                      ))}
                      <td className="contract-num">{employee.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p className="muted small">
            {t("grand_total")}: {payload.total}
          </p>
        </div>
      )}
    </PeriodReportView>
  );
}

interface ByExtraWorkPayload extends PeriodPayload {
  extra_work: {
    source_id: number;
    title: string | null;
    total: string;
    employees: { employee: number; employee_name: string; hours: string }[];
  }[];
}

export function EmployeeHoursByExtraWorkView() {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<ByExtraWorkPayload>
      endpoint="/reports/employee-hours-by-extra-work/"
      stem="employee-hours-by-extra-work"
      // The one empty state that needs explaining rather than just
      // stating: hours only carry a job if somebody picked one when
      // entering the week (Sprint 177), so an empty answer here usually
      // means "nothing has been tagged yet", not "nobody worked".
      emptyHint={t("employee_hours_extra_work_empty")}
      testIdPrefix="employee-hours-extra-work"
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.extra_work.map((job) => (
            <div key={job.source_id} style={{ marginBottom: 16 }}>
              <div className="form-section-title">
                {job.title ?? `#${job.source_id}`} — {job.total}
              </div>
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("employee")}</th>
                    <th className="contract-num">{t("hours")}</th>
                  </tr>
                </thead>
                <tbody>
                  {job.employees.map((employee) => (
                    <tr key={employee.employee}>
                      <td>{employee.employee_name}</td>
                      <td className="contract-num">{employee.hours}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p className="muted small">
            {t("grand_total")}: {payload.total}
          </p>
        </div>
      )}
    </PeriodReportView>
  );
}

interface TicketReportPayload extends PeriodPayload {
  rows: {
    id: number;
    ticket_no: string;
    title: string;
    status: string;
    building_name: string | null;
    customer_name: string | null;
    created_at: string;
    finished_at: string | null;
    duration_days: number | null;
  }[];
  finished: number;
  average_duration_days: number | null;
}

export function TicketReportView() {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<TicketReportPayload>
      endpoint="/reports/ticket-report/"
      stem="ticket-report"
      emptyHint={t("ticket_report_empty")}
      testIdPrefix="ticket-report"
    >
      {(payload) => (
        <div className="table-wrap">
          <p className="muted small">
            {t("ticket_report_summary", {
              total: payload.total,
              finished: payload.finished,
              average:
                payload.average_duration_days === null
                  ? "—"
                  : payload.average_duration_days,
            })}
          </p>
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                <th>{t("ticket_no")}</th>
                <th>{t("ticket_title")}</th>
                <th>{t("common:status")}</th>
                <th>{t("common:building")}</th>
                <th>{t("common:customer")}</th>
                <th className="contract-num">{t("duration_days")}</th>
              </tr>
            </thead>
            <tbody>
              {payload.rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.ticket_no}</td>
                  <td>{row.title}</td>
                  <td>{row.status}</td>
                  <td>{row.building_name ?? "—"}</td>
                  <td>{row.customer_name ?? "—"}</td>
                  {/* An em dash, not a zero: an unfinished ticket has no
                      duration, and 0 would read as "took no time". */}
                  <td className="contract-num">
                    {row.duration_days ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PeriodReportView>
  );
}
