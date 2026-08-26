import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import { StatusBadge } from "../../components/StatusBadge";
import { hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { PeriodReportView } from "./PeriodReportView";
import type { PeriodPayload } from "./PeriodReportView";
import type { ReportFilters } from "../../api/reports";

/**
 * Sprint 178 §2 — the three employee-hours reports and the ticket report.
 *
 * Four views in one file because each is a table and nothing else: the
 * period picker, the fetch, the CSV and the PDF all live in
 * `PeriodReportView`. Splitting four ~40-line tables across four files
 * would be four imports for no separation.
 *
 * Sprint 180 §1 — all four take the Reports page's `filters` and pass
 * them straight through. They hold no filter state of their own: the
 * shell owns the period and the page owns the company and the building,
 * which is the arrangement that keeps the CSV and the screen describing
 * the same slice.
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

/** Every one of the four takes exactly this. */
interface ReportViewProps {
  filters: ReportFilters;
}

interface ByBuildingPayload extends PeriodPayload {
  buildings: {
    building: number | null;
    building_name: string | null;
    total: string;
    employees: { employee: number; employee_name: string; hours: string }[];
  }[];
}

export function EmployeeHoursByBuildingView({ filters }: ReportViewProps) {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<ByBuildingPayload>
      endpoint="/reports/employee-hours-by-building/"
      stem="employee-hours-by-building"
      emptyHint={t("employee_hours_building_empty")}
      testIdPrefix="employee-hours-building"
      filters={filters}
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.buildings.map((bucket) => (
            <div key={bucket.building ?? "none"} style={{ marginBottom: 16 }}>
              <div className="form-section-title report-group-title">
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
          <p className="muted small report-grand-total">
            {t("grand_total")}: {payload.total}
          </p>
        </div>
      )}
    </PeriodReportView>
  );
}

interface WeeklyHourTypeBucket {
  hour_type: number;
  hour_type_name: string;
  hour_type_code: string | null;
  days: Record<string, string>;
  total: string;
}

interface WeeklyPayload extends PeriodPayload {
  weeks: {
    iso_year: number;
    iso_week: number;
    total: string;
    /** Sprint 180 §3 — the Monday-to-Sunday column totals for the week. */
    day_totals: Record<string, string>;
    employees: {
      employee: number;
      employee_name: string;
      days: Record<string, string>;
      total: string;
      /** Sprint 180 §3 — the split under the person's own row. */
      hour_types: WeeklyHourTypeBucket[];
    }[];
  }[];
}

export function EmployeeHoursWeeklyView({ filters }: ReportViewProps) {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<WeeklyPayload>
      endpoint="/reports/employee-hours-weekly/"
      stem="employee-hours-weekly"
      emptyHint={t("employee_hours_weekly_empty")}
      testIdPrefix="employee-hours-weekly"
      filters={filters}
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.weeks.map((week) => (
            <div
              key={`${week.iso_year}-${week.iso_week}`}
              style={{ marginBottom: 16 }}
            >
              <div className="form-section-title report-group-title">
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
                    {/* Sprint 180 §3 — normal, overtime and sick hours
                        are paid differently, so a week summed into one
                        number cannot be handed to payroll. */}
                    <th>{t("hour_type")}</th>
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
                    // A Fragment per person, not a nested table: the
                    // person's combined row and the hour-type rows under
                    // it are one group, and nesting a table inside a
                    // cell would give the sub-rows their own column
                    // widths — the split would stop lining up with the
                    // weekday columns it is a split OF.
                    <Fragment key={employee.employee}>
                      <tr>
                        <td>{employee.employee_name}</td>
                        <td className="muted">—</td>
                        {DAYS.map((day) => (
                          <td key={day} className="contract-num">
                            {employee.days[day]}
                          </td>
                        ))}
                        <td className="contract-num">{employee.total}</td>
                      </tr>
                      {employee.hour_types.map((bucket) => (
                        <tr key={bucket.hour_type}>
                          <td />
                          <td className="muted small">
                            {hourTypeLabelFrom(bucket.hour_type_name, undefined, t)}
                            {bucket.hour_type_code
                              ? ` (${bucket.hour_type_code})`
                              : ""}
                          </td>
                          {DAYS.map((day) => (
                            <td key={day} className="contract-num muted small">
                              {bucket.days[day]}
                            </td>
                          ))}
                          <td className="contract-num muted small">
                            {bucket.total}
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
                <tfoot>
                  {/* Sprint 180 §3 — "how much did the team work on
                      Wednesday" was answerable only by adding a column
                      up with a finger. Summed server-side from the same
                      buckets the rows are, so it cannot disagree with
                      them. */}
                  <tr data-testid={`weekly-day-totals-${week.iso_year}-${week.iso_week}`}>
                    <th>{t("total")}</th>
                    <th />
                    {DAYS.map((day) => (
                      <th key={day} className="contract-num">
                        {week.day_totals[day]}
                      </th>
                    ))}
                    <th className="contract-num">{week.total}</th>
                  </tr>
                </tfoot>
              </table>
            </div>
          ))}
          <p className="muted small report-grand-total">
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

export function EmployeeHoursByExtraWorkView({ filters }: ReportViewProps) {
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
      filters={filters}
    >
      {(payload) => (
        <div className="table-wrap">
          {payload.extra_work.map((job) => (
            <div key={job.source_id} style={{ marginBottom: 16 }}>
              <div className="form-section-title report-group-title">
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
          <p className="muted small report-grand-total">
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

export function TicketReportView({ filters }: ReportViewProps) {
  const { t } = useTranslation(["reports", "common"]);
  return (
    <PeriodReportView<TicketReportPayload>
      endpoint="/reports/ticket-report/"
      stem="ticket-report"
      emptyHint={t("ticket_report_empty")}
      testIdPrefix="ticket-report"
      filters={filters}
    >
      {(payload) => (
        <div className="table-wrap">
          {/* Sprint 179B §4 — this line sat flush against the table it
              summarises. Same breathing room the group titles now get. */}
          <p className="muted small report-summary-line">
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
                  <td>
                    <StatusBadge
                      status={{ kind: "ticket", value: row.status }}
                      variant="cell"
                    />
                  </td>
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

/** One category line, in the buildings breakdown and in the roll-up.
 *  Both come from the same server-side builder, so they cannot be
 *  shaped differently. */
interface MeldingenCategoryRow {
  category: number | null;
  category_name: string | null;
  category_name_en: string | null;
  category_slug: string | null;
  category_color: string | null;
  count: number;
}

interface MeldingenByCategoryPayload extends PeriodPayload {
  buildings: {
    building: number | null;
    building_name: string | null;
    total: number;
    categories: MeldingenCategoryRow[];
  }[];
  /** W13 — the same period rolled up ACROSS buildings, one line per
   *  group. "How many tickets did we open in 2026, and what are the
   *  groups?" is this list. */
  categories: MeldingenCategoryRow[];
  total: number;
  uncategorised: number;
}

/**
 * Two readings of one period, in the order they are asked for.
 *
 * FIRST, the groups: "how many tickets did we open in 2026? What are the
 * groups of these tickets?" — W13's question, and it is answered by the
 * table at the top without the reader adding anything up.
 *
 * THEN, per building: "how many meldingen per category per building",
 * the monthly customer review. Same shell as the three hours reports
 * (period picker, CSV, PDF, empty state), same building-outside /
 * rows-inside shape as `employee-hours-by-building`.
 *
 * An UNCATEGORISED bucket arrives with `category_name: null` and is
 * rendered as a named row rather than dropped: the report's total has to
 * equal the number of meldingen in the period, and "how much is still
 * untagged" is the number that says whether the taxonomy is being used.
 */
export function MeldingenByCategoryView({ filters }: ReportViewProps) {
  const { t, i18n } = useTranslation(["reports", "common"]);
  /* W14 §1 — THE READER'S LANGUAGE, ON THE ONE SURFACE THAT WAS TOLD TO
     PICK AND NEVER DID.
     `reports/category_report.py::_category_row` ships BOTH labels and
     says so in as many words: "neither is resolved here. The reader's
     language is a CLIENT concern." This client then rendered
     `category_name` — the Dutch column — unconditionally, so an English
     reader met "Storing" in the report while the ticket list beside it
     said "Malfunction". `i18n.language` is the same value the rest of
     the page is rendered in; the Dutch label stays the fallback for an
     English label nobody filled in, matching `label_for`. */
  const label = (row: MeldingenCategoryRow) =>
    i18n.language.startsWith("en")
      ? row.category_name_en || row.category_name
      : row.category_name;
  return (
    <PeriodReportView<MeldingenByCategoryPayload>
      endpoint="/reports/meldingen-by-category/"
      stem="meldingen-by-category"
      emptyHint={t("meldingen_category_empty")}
      testIdPrefix="meldingen-category"
      filters={filters}
    >
      {(payload) => (
        <div className="table-wrap">
          {/* W13 — the groups, before the buildings. */}
          {payload.categories.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div className="form-section-title report-group-title">
                {t("meldingen_groups_title")} — {payload.total}
              </div>
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("common:ticket_categories.field_label")}</th>
                    <th className="contract-num">{t("meldingen_count")}</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.categories.map((row) => (
                    <tr
                      key={row.category ?? "none"}
                      data-testid="meldingen-group-row"
                    >
                      <td>
                        {label(row) ? (
                          <>
                            <span
                              className="ticket-category-chip"
                              style={
                                row.category_color
                                  ? { background: row.category_color }
                                  : undefined
                              }
                              aria-hidden="true"
                            />
                            {label(row)}
                          </>
                        ) : (
                          <span className="muted-empty">
                            {t("meldingen_uncategorised")}
                          </span>
                        )}
                      </td>
                      <td className="contract-num">{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {payload.buildings.map((bucket) => (
            <div
              key={bucket.building ?? "none"}
              style={{ marginBottom: 16 }}
            >
              <div className="form-section-title report-group-title">
                {bucket.building_name ?? t("no_building")} — {bucket.total}
              </div>
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("common:ticket_categories.field_label")}</th>
                    <th className="contract-num">{t("meldingen_count")}</th>
                  </tr>
                </thead>
                <tbody>
                  {bucket.categories.map((row) => (
                    <tr key={row.category ?? "none"}>
                      <td>
                        {label(row) ?? (
                          <span className="muted-empty">
                            {t("meldingen_uncategorised")}
                          </span>
                        )}
                      </td>
                      <td className="contract-num">{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p className="muted small report-grand-total">
            {t("grand_total")}: {payload.total} — {t("meldingen_uncategorised")}
            : {payload.uncategorised}
          </p>
        </div>
      )}
    </PeriodReportView>
  );
}
