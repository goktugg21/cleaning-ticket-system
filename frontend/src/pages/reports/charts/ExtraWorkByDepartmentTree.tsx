import { useTranslation } from "react-i18next";
import type { ReportFilters } from "../../../api/reports";
import { fetchExtraWorkByDepartment } from "../../../api/reports";
import type {
  ExtraWorkByDepartmentBuildingBucket,
  ExtraWorkByDepartmentDeptBucket,
} from "../../../api/reports.types";
import { BoundedList } from "../../../components/BoundedList";
import { useReport } from "../../../hooks/useReport";
import { customerLabelName } from "../../../lib/customerLabelName";
import { formatMoney } from "../../../lib/intl";
import { ExportButtons } from "./ExportButtons";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

/**
 * Sprint 131 — one customer's Extra Work grouped Building -> Department ->
 * Work Type, reproducing the owner's father's reference "Extra Works by
 * Department" report on-screen. Sibling of `ExtraWorkRevenueByBuildingChart`
 * (Sprint 124) — same card shell, same filters, same `ExportButtons`
 * wiring — but a nested collapsible tree instead of a bar chart, since the
 * data is a grouping, not a single ranked axis.
 *
 * The tree renders SUMMARY rows only (count + total per building /
 * department / work type) — never the individual Extra Work rows the JSON
 * payload also carries under `work_types[].rows`. A single work type can
 * hold hundreds of rows for a busy customer; the full numbered listing is
 * what the PDF detail section is for (CLAUDE.md #8 — no unbounded list
 * from a server collection). The top-level building list is additionally
 * wrapped in `BoundedList` for the same reason, one level up.
 *
 * Native `<details>/<summary>` drives the expand/collapse state — no
 * custom open-state tracking needed, and it is keyboard- and
 * screen-reader-accessible by default.
 */
export function ExtraWorkByDepartmentTree({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchExtraWorkByDepartment,
    filters,
    refreshKey,
  });

  const buildings = data?.buildings ?? [];

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 200 }}
      data-testid="chart-card-extra-work-by-department"
    >
      <h3 className="section-title">{t("ew_by_department_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("ew_by_department_subtitle")}
      </p>

      {loading && (
        <div className="loading-bar" style={{ marginTop: 12, height: 120 }}>
          <div className="loading-bar-fill" />
        </div>
      )}
      {error && (
        <div className="alert-error" role="alert" style={{ marginTop: 12 }}>
          {error}{" "}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={retry}
            style={{ marginLeft: 8 }}
          >
            {t("retry")}
          </button>
        </div>
      )}
      {!loading &&
        !error &&
        data &&
        (buildings.length === 0 ? (
          <div
            className="muted small"
            data-testid="ew-by-department-empty"
            style={{ padding: "24px 0", textAlign: "center" }}
          >
            {t("ew_by_department_empty")}
          </div>
        ) : (
          <BoundedList
            size="lg"
            count={buildings.length}
            ariaLabel={t("ew_by_department_title")}
            testIdPrefix="ew-by-department"
          >
            <ul
              className="ew-department-tree"
              data-testid="ew-by-department-tree"
            >
              {buildings.map((building) => (
                <BuildingNode key={building.building_id} building={building} t={t} />
              ))}
            </ul>
          </BoundedList>
        ))}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("ew_by_department_total", { amount: formatMoney(data.totals.total) })}{" "}
          · {t("ew_revenue_incl_vat")}
        </p>
      )}

      <ExportButtons
        dimension="extra_work_by_department"
        filters={filters}
        disabled={loading || !!error}
      />
    </section>
  );
}

interface NodeProps {
  t: (key: string, options?: Record<string, unknown>) => string;
}

function BuildingNode({
  building,
  t,
}: NodeProps & { building: ExtraWorkByDepartmentBuildingBucket }) {
  return (
    <li className="ew-department-tree-building">
      <details data-testid="ew-by-department-building">
        <summary className="ew-department-tree-summary">
          <span className="ew-department-tree-name">
            {building.building_name}
          </span>
          <span className="ew-department-tree-meta">
            {t("ew_by_department_item_count", { count: building.count })} ·{" "}
            {formatMoney(building.total)}
          </span>
        </summary>
        <ul className="ew-department-tree-departments">
          {building.departments.map((dept) => (
            <DepartmentNode
              key={dept.department_id ?? "untagged"}
              dept={dept}
              t={t}
            />
          ))}
        </ul>
      </details>
    </li>
  );
}

function DepartmentNode({
  dept,
  t,
}: NodeProps & { dept: ExtraWorkByDepartmentDeptBucket }) {
  return (
    <li>
      <details data-testid="ew-by-department-department">
        <summary className="ew-department-tree-summary ew-department-tree-summary-dept">
          <span className="ew-department-tree-name">
            {/* Sprint 187 §4 — most nodes of this tree read "Algemeen"
                in the English UI, because nearly every record now
                carries the auto-seeded label and this was the last
                place printing it raw. Both levels, not just this
                one. */}
            {customerLabelName(dept.department_name, t) ||
              t("ew_by_department_untagged_department")}
          </span>
          <span className="ew-department-tree-meta">
            {t("ew_by_department_item_count", { count: dept.count })} ·{" "}
            {formatMoney(dept.total)}
          </span>
        </summary>
        <ul className="ew-department-tree-worktypes">
          {dept.work_types.map((wt) => (
            <li
              key={wt.work_type_id ?? "untagged"}
              className="ew-department-tree-worktype-row"
              data-testid="ew-by-department-worktype"
            >
              <span className="ew-department-tree-name">
                {customerLabelName(wt.work_type_name, t) ||
                  t("ew_by_department_untagged_work_type")}
              </span>
              <span className="ew-department-tree-meta">
                {t("ew_by_department_item_count", { count: wt.count })} ·{" "}
                {formatMoney(wt.total)}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}
