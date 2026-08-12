import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";

interface EmployeeRow {
  employee_id: number;
  employee_name: string;
  worked_hours: string;
}

interface ComparisonRow {
  building: number | null;
  building_name: string;
  contracted_hours: string;
  worked_hours: string;
  difference: string;
  employees: EmployeeRow[];
}

interface ComparisonPayload {
  year: number;
  month: number;
  from: string;
  to: string;
  rows: ComparisonRow[];
  totals: {
    contracted_hours: string;
    worked_hours: string;
    difference: string;
  };
}

/**
 * Sprint 166 §4 — the SCREEN for the hours comparison.
 *
 * Sprint 165 built `/api/reports/hours-comparison/` and reported it as
 * a feature. It was an endpoint: there was no interface, so no operator
 * could reach it. This is the missing half, and it is reachable from
 * the sidebar like every other report.
 *
 * What the page has to be honest about, and says on screen rather than
 * hiding: **a contract has no employee dimension.** It says "40 hours a
 * month at this building", never "40 hours of Ahmet". So the per-worker
 * breakdown under each building is the WORKED side only, and the page
 * states that instead of printing an invented per-person target.
 */
/**
 * Sprint 169 §6 — the comparison itself, without a page around it.
 *
 * The Reports page opens this in a MODAL and the standalone route
 * renders it under a page header. Extracting it is not tidiness: two
 * copies of a report is how the customer-scoped lists in this same
 * sprint's §8 drifted for six sprints, and a report that disagrees with
 * itself depending on where you opened it is worse than one that is
 * hard to find.
 */
export function HoursComparisonView() {
  const { t } = useTranslation(["reports", "common"]);
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [payload, setPayload] = useState<ComparisonPayload | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<number[]>([]);

  const requestKey = `${year}-${month}-${refreshKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get<ComparisonPayload>("/reports/hours-comparison/", {
        params: { year, month },
      })
      .then((response) => {
        if (cancelled) return;
        setPayload(response.data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [year, month, requestKey]);

  const months = useMemo(
    () =>
      Array.from({ length: 12 }, (_, index) => ({
        value: index + 1,
        label: new Date(2000, index, 1).toLocaleDateString(undefined, {
          month: "long",
        }),
      })),
    [],
  );

  const rows = payload?.rows ?? [];

  const number = (value: string | number) => {
    const amount = typeof value === "number" ? value : Number(value);
    return Number.isFinite(amount) ? amount.toFixed(2) : String(value);
  };

  /** Under / over / on target, as a tag the eye can sort at a glance.
   *  The SIGN is the point of the report, so it is never printed bare. */
  const deltaTag = (raw: string) => {
    const value = Number(raw);
    if (!Number.isFinite(value) || Math.abs(value) < 0.005) {
      return { cls: "cell-tag-muted", label: t("hours_comparison.on_target") };
    }
    return value < 0
      ? { cls: "cell-tag-rejected", label: t("hours_comparison.under") }
      : { cls: "cell-tag-open", label: t("hours_comparison.over") };
  };

  return (
    <div data-testid="hours-comparison-view">
      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card card-detail-pad" style={{ marginBottom: 16 }}>
        <form className="filter-bar" onSubmit={(e) => e.preventDefault()}>
          <div className="filter-field">
            <span className="filter-label">
              {t("hours_comparison.month")}
            </span>
            <select
              className="filter-control"
              value={month}
              onChange={(event) => setMonth(Number(event.target.value))}
              data-testid="hours-comparison-month"
            >
              {months.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("hours_comparison.year")}</span>
            <input
              className="filter-control"
              type="number"
              value={year}
              onChange={(event) => setYear(Number(event.target.value))}
              data-testid="hours-comparison-year"
            />
          </div>
        </form>

        <div className="filter-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setRefreshKey((n) => n + 1)}
            disabled={loading}
            data-testid="hours-comparison-refresh"
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("common:refresh")}
          </button>
        </div>

        {/* Stated, not hidden: the two sides are not symmetrical. */}
        <p className="muted small" data-testid="hours-comparison-asymmetry">
          {t("hours_comparison.asymmetry_note")}
        </p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                <th>{t("hours_comparison.col_building")}</th>
                <th className="contract-num">
                  {t("hours_comparison.col_contracted")}
                </th>
                <th className="contract-num">
                  {t("hours_comparison.col_worked")}
                </th>
                <th className="contract-num">
                  {t("hours_comparison.col_difference")}
                </th>
                <th>{t("hours_comparison.col_state")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const key = row.building ?? -1;
                const open = expanded.includes(key);
                const tag = deltaTag(row.difference);
                return (
                  <>
                    <tr key={`b-${key}`}>
                      <td className="td-subject">
                        {row.employees.length > 0 ? (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm contract-group-toggle"
                            aria-expanded={open}
                            onClick={() =>
                              setExpanded((current) =>
                                current.includes(key)
                                  ? current.filter((k) => k !== key)
                                  : [...current, key],
                              )
                            }
                            data-testid={`hours-comparison-expand-${key}`}
                          >
                            <span aria-hidden="true">{open ? "▾" : "▸"}</span>
                            {row.building_name ||
                              t("hours_comparison.no_building")}
                          </button>
                        ) : (
                          row.building_name ||
                          t("hours_comparison.no_building")
                        )}
                      </td>
                      <td className="contract-num">
                        {number(row.contracted_hours)}
                      </td>
                      <td className="contract-num">
                        {number(row.worked_hours)}
                      </td>
                      <td className="contract-num">
                        {Number(row.difference) > 0 ? "+" : ""}
                        {number(row.difference)}
                      </td>
                      <td>
                        <span className={`cell-tag ${tag.cls}`}>
                          {tag.label}
                        </span>
                      </td>
                    </tr>
                    {open &&
                      row.employees.map((employee) => (
                        <tr
                          key={`b-${key}-e-${employee.employee_id}`}
                          className="hours-comparison-employee-row"
                        >
                          <td style={{ paddingLeft: 34 }}>
                            {employee.employee_name}
                          </td>
                          {/* No contracted figure per person, and the
                              dash says so rather than a zero implying a
                              target of none. */}
                          <td className="contract-num muted-empty">—</td>
                          <td className="contract-num">
                            {number(employee.worked_hours)}
                          </td>
                          <td className="contract-num muted-empty">—</td>
                          <td />
                        </tr>
                      ))}
                  </>
                );
              })}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    {t("hours_comparison.empty")}
                  </td>
                </tr>
              )}
              {rows.length > 0 && payload && (
                <tr className="contract-grand-total">
                  <td>
                    <strong>{t("hours_comparison.total")}</strong>
                  </td>
                  <td className="contract-num">
                    <strong>{number(payload.totals.contracted_hours)}</strong>
                  </td>
                  <td className="contract-num">
                    <strong>{number(payload.totals.worked_hours)}</strong>
                  </td>
                  <td className="contract-num">
                    <strong>
                      {Number(payload.totals.difference) > 0 ? "+" : ""}
                      {number(payload.totals.difference)}
                    </strong>
                  </td>
                  <td />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
