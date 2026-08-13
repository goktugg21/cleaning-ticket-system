import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HoursComparisonView } from "./HoursComparisonView";
import { HoursComparisonChart } from "./charts/HoursComparisonChart";
import { WorkerHoursView } from "./WorkerHoursView";
import {
  EmployeeHoursByBuildingView,
  EmployeeHoursByExtraWorkView,
  EmployeeHoursWeeklyView,
  TicketReportView,
} from "./EmployeeHoursViews";
import { WorkerHoursCardTiles } from "./charts/WorkerHoursCardTiles";
import { listAllBuildings, listAllCompanies } from "../../api/admin";
import type { ReportFilters } from "../../api/reports";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useReportsFilters } from "../../hooks/useReportsFilters";
import { AgeBucketsChart } from "./charts/AgeBucketsChart";
import { ExtraWorkRevenueChart } from "./charts/ExtraWorkRevenueChart";
import { ManagerThroughputChart } from "./charts/ManagerThroughputChart";
import { SLABreachRateChart } from "./charts/SLABreachRateChart";
import { SLADistributionChart } from "./charts/SLADistributionChart";
import { StatusDistributionChart } from "./charts/StatusDistributionChart";
import { TicketsByBuildingChart } from "./charts/TicketsByBuildingChart";
import { TicketsByCustomerChart } from "./charts/TicketsByCustomerChart";
import { TicketsByOriginChart } from "./charts/TicketsByOriginChart";
import { TicketsByTypeChart } from "./charts/TicketsByTypeChart";
import { TicketsOverTimeChart } from "./charts/TicketsOverTimeChart";

const RANGE_PRESETS: Array<{
  key: "last_7" | "last_30" | "last_90";
  labelKey: string;
}> = [
  { key: "last_7", labelKey: "preset_last_7" },
  { key: "last_30", labelKey: "preset_last_30" },
  { key: "last_90", labelKey: "preset_last_90" },
];

/**
 * Sprint 178 §2 — the four reports, as ONE list that both the cards and
 * the modals iterate.
 *
 * A second, independently maintained array for the modals is exactly the
 * defect CLAUDE.md records from Sprint 126: the `documents` permission
 * group rendered a headerless column and stayed invisible for three
 * sprints because two consumers each had their own list. One constant,
 * two consumers, and the compiler sees every entry.
 */
const REPORT_CARDS = [
  {
    key: "hours_building" as const,
    testId: "employee-hours-building",
    titleKey: "employee_hours_building_title",
    subtitleKey: "employee_hours_building_subtitle",
    View: EmployeeHoursByBuildingView,
  },
  {
    key: "hours_weekly" as const,
    testId: "employee-hours-weekly",
    titleKey: "employee_hours_weekly_title",
    subtitleKey: "employee_hours_weekly_subtitle",
    View: EmployeeHoursWeeklyView,
  },
  {
    key: "hours_extra_work" as const,
    testId: "employee-hours-extra-work",
    titleKey: "employee_hours_extra_work_title",
    subtitleKey: "employee_hours_extra_work_subtitle",
    View: EmployeeHoursByExtraWorkView,
  },
  {
    key: "tickets" as const,
    testId: "ticket-report",
    titleKey: "ticket_report_title",
    subtitleKey: "ticket_report_subtitle",
    View: TicketReportView,
  },
];

export function ReportsPage() {
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [workerHoursOpen, setWorkerHoursOpen] = useState(false);
  /** Sprint 178 §2 — the four new reports. ONE piece of state naming
   *  which is open, rather than four booleans: two cannot be open at
   *  once, and four booleans is four chances for them to be. */
  const [openReport, setOpenReport] = useState<
    null | "hours_building" | "hours_weekly" | "hours_extra_work" | "tickets"
  >(null);
  const { me } = useAuth();
  const { t } = useTranslation(["reports", "common"]);
  const { filters, setFilter, setRangePreset } = useReportsFilters();

  const [refreshKey, setRefreshKey] = useState(0);

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);
  const [buildingsLoaded, setBuildingsLoaded] = useState(false);

  const isSuperAdmin = me?.role === "SUPER_ADMIN";
  const isCompanyAdmin = me?.role === "COMPANY_ADMIN";
  const isBuildingManager = me?.role === "BUILDING_MANAGER";

  // Companies dropdown is only meaningful for SUPER_ADMIN. Fetch lazily.
  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    listAllCompanies().then((response) => {
      if (cancelled) return;
      setCompanies(response);
    });
    return () => {
      cancelled = true;
    };
  }, [isSuperAdmin]);

  // Buildings dropdown:
  //   SUPER_ADMIN: only when a specific company is selected.
  //   COMPANY_ADMIN: all buildings under their (sole) company.
  //   BUILDING_MANAGER: their assigned buildings only.
  const buildingFetchKey = useMemo(() => {
    if (isSuperAdmin) {
      return filters.company !== undefined ? `company:${filters.company}` : null;
    }
    if (isCompanyAdmin || isBuildingManager) return "self";
    return null;
  }, [isSuperAdmin, isCompanyAdmin, isBuildingManager, filters.company]);

  useEffect(() => {
    if (buildingFetchKey === null) {
      setBuildings([]);
      setBuildingsLoaded(false);
      return;
    }
    let cancelled = false;
    setBuildingsLoaded(false);
    const params: Parameters<typeof listAllBuildings>[0] = {};
    if (isSuperAdmin && filters.company !== undefined) {
      params.company = filters.company;
    }
    listAllBuildings(params)
      .then((response) => {
        if (cancelled) return;
        setBuildings(response);
      })
      .finally(() => {
        if (!cancelled) setBuildingsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [buildingFetchKey, isSuperAdmin, filters.company]);

  // BUILDING_MANAGER with exactly one assignment: auto-select it (and lock).
  useEffect(() => {
    if (!isBuildingManager) return;
    if (!buildingsLoaded) return;
    if (buildings.length !== 1) return;
    if (filters.building === buildings[0].id) return;
    setFilter("building", buildings[0].id);
  }, [isBuildingManager, buildingsLoaded, buildings, filters.building, setFilter]);

  const buildingDropdownLocked =
    isBuildingManager && buildingsLoaded && buildings.length === 1;

  const apiFilters: ReportFilters = useMemo(
    () => ({
      from: filters.from,
      to: filters.to,
      company: filters.company,
      building: filters.building,
    }),
    [filters.from, filters.to, filters.company, filters.building],
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("eyebrow")}
          </div>
          <h2 className="page-title" data-testid="reports-page-title">
            {t("title")}
          </h2>
          <p className="page-sub">{t("subtitle")}</p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            data-testid="refresh-reports"
            onClick={() => setRefreshKey((n) => n + 1)}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("common:refresh")}
          </button>
        </div>
      </div>

      <section
        className="card"
        style={{ padding: "16px 18px", marginBottom: 16 }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            alignItems: "flex-end",
          }}
        >
          <div className="filter-field">
            <span className="filter-label">{t("filter_date_range")}</span>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {RANGE_PRESETS.map((preset) => {
                const active = filters.preset === preset.key;
                return (
                  <button
                    key={preset.key}
                    type="button"
                    className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
                    data-testid={`range-preset-${preset.key}`}
                    onClick={() => setRangePreset(preset.key)}
                    aria-pressed={active}
                  >
                    {t(preset.labelKey)}
                  </button>
                );
              })}
              <span
                className={`btn btn-sm ${filters.preset === "custom" ? "btn-primary" : "btn-secondary"}`}
                style={{ cursor: "default" }}
                aria-pressed={filters.preset === "custom"}
              >
                {t("preset_custom")}
              </span>
            </div>
          </div>

          <div className="filter-field">
            <span className="filter-label">{t("filter_from")}</span>
            <input
              className="filter-control"
              type="date"
              value={filters.from}
              onChange={(event) => setFilter("from", event.target.value)}
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("filter_to")}</span>
            <input
              className="filter-control"
              type="date"
              value={filters.to}
              onChange={(event) => setFilter("to", event.target.value)}
            />
          </div>

          {isSuperAdmin && (
            <div className="filter-field">
              <span className="filter-label">{t("filter_company")}</span>
              <select
                className="filter-control"
                data-testid="filter-company"
                value={filters.company === undefined ? "" : String(filters.company)}
                onChange={(event) => {
                  const v = event.target.value;
                  setFilter("company", v === "" ? undefined : Number(v));
                }}
              >
                <option value="">{t("filter_all_companies")}</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {(isSuperAdmin && filters.company !== undefined) || isCompanyAdmin || isBuildingManager ? (
            <div className="filter-field">
              <span className="filter-label">{t("filter_building")}</span>
              <select
                className="filter-control"
                data-testid="filter-building"
                value={filters.building === undefined ? "" : String(filters.building)}
                onChange={(event) => {
                  const v = event.target.value;
                  setFilter("building", v === "" ? undefined : Number(v));
                }}
                disabled={buildingDropdownLocked || !buildingsLoaded}
              >
                <option value="">{t("filter_all_buildings")}</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>

      </section>

      {/* Sprint 171 §1 — the comparison is a CHART CARD in the grid
          below, immediately after Tickets-by-building, rather than the
          full-width banner it was. It read as one odd thing above the
          reports instead of one OF them. */}
      {comparisonOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("hours_comparison.title")}
          data-testid="hours-comparison-modal"
          onClick={(event) => {
            if (event.target === event.currentTarget) setComparisonOpen(false);
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
            paddingTop: "6vh",
            overflowY: "auto",
          }}
        >
          <div
            className="card"
            style={{
              width: "min(96vw, 1180px)",
              padding: 24,
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              overflowY: "auto",
            }}
          >
            <div className="section-head" style={{ marginBottom: 12 }}>
              <div className="section-head-title">
                {t("hours_comparison.title")}
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setComparisonOpen(false)}
                data-testid="hours-comparison-close"
              >
                {t("common:cancel")}
              </button>
            </div>
            <HoursComparisonView />
          </div>
        </div>
      )}

      {workerHoursOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("worker_hours.title")}
          data-testid="worker-hours-modal"
          onClick={(event) => {
            if (event.target === event.currentTarget) setWorkerHoursOpen(false);
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
            paddingTop: "6vh",
            overflowY: "auto",
          }}
        >
          <div
            className="card"
            style={{
              width: "min(96vw, 1320px)",
              padding: 24,
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              overflowY: "auto",
            }}
          >
            <div className="section-head" style={{ marginBottom: 12 }}>
              <div className="section-head-title">{t("worker_hours.title")}</div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setWorkerHoursOpen(false)}
                data-testid="worker-hours-close"
              >
                {t("common:cancel")}
              </button>
            </div>
            <WorkerHoursView />
          </div>
        </div>
      )}

      {/* Extra Work revenue is its own report (SoT §7.2), not a generic
          ticket count — render it FIRST and full-width, above the grid of
          ticket-count charts. */}
      <ExtraWorkRevenueChart filters={apiFilters} refreshKey={refreshKey} />

      {/* Extra Work by building / by customer — origin="EXTRA_WORK" narrows
          to Extra Work-origin tickets only. Grouped here with the revenue
          card as the dedicated Extra Work reporting block (SoT §7.2). The
          GENERIC by-building / by-customer cards stay in the ticket-count
          grid below, unchanged. */}
      <div
        className="reports-grid"
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(420px, 100%), 1fr))",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <TicketsByBuildingChart
          origin="EXTRA_WORK"
          filters={apiFilters}
          refreshKey={refreshKey}
        />
        <TicketsByCustomerChart
          origin="EXTRA_WORK"
          filters={apiFilters}
          refreshKey={refreshKey}
        />
      </div>

      <div
        // Sprint 20 follow-up: the previous template `minmax(420px, 1fr)`
        // forced every card to be at least 420px wide, which on a
        // ≤420px viewport overflowed the workspace and got clipped by
        // its `overflow-x: clip` rule, hiding the right edge of every
        // chart. `min(420px, 100%)` tells the auto-fit algorithm to
        // back off to the available width on a phone, producing a
        // single full-width column. Desktop layout is unchanged.
        className="reports-grid"
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(420px, 100%), 1fr))",
          gap: 16,
        }}
      >
        <StatusDistributionChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsOverTimeChart filters={apiFilters} refreshKey={refreshKey} />
        <ManagerThroughputChart filters={apiFilters} refreshKey={refreshKey} />
        <AgeBucketsChart filters={apiFilters} refreshKey={refreshKey} />
        <SLADistributionChart filters={apiFilters} refreshKey={refreshKey} />
        <SLABreachRateChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsByTypeChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsByOriginChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsByCustomerChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsByBuildingChart filters={apiFilters} refreshKey={refreshKey} />
        <HoursComparisonChart
          refreshKey={refreshKey}
          onOpen={() => setComparisonOpen(true)}
        />
        {/* Sprint 171 §4 — the Worker Hour Report, as a card opening a
            modal, the shape §1 settled for the comparison. No nav
            child: a nav child is a sub-page as far as an operator is
            concerned, which is the thing §1 removed. */}
        <section
          className="card"
          style={{ padding: "20px 22px", minHeight: 360 }}
          data-testid="chart-card-worker-hours"
        >
          <h3 className="section-title">{t("worker_hours.title")}</h3>
          <p className="muted small" style={{ marginBottom: 8 }}>
            {t("worker_hours.subtitle")}
          </p>
          {/* Sprint 172 §4 — the card was a title, two lines and a
              button while every neighbour carried a chart. It shows the
              four figures the modal computes for the current span, so
              the grid reads as one set of tiles and the card answers
              something on its own. */}
          <WorkerHoursCardTiles refreshKey={refreshKey} />
          <p className="muted small" style={{ marginTop: 10 }}>
            {t("worker_hours.card_hint")}
          </p>
          <div style={{ marginTop: 10 }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setWorkerHoursOpen(true)}
              data-testid="open-worker-hours"
            >
              {t("worker_hours.open")}
            </button>
          </div>
        </section>

        {/* Sprint 178 §2 — four more reports, the SAME card-opens-a-modal
            shape Sprint 171 settled. No new nav children: a nav child is
            a sub-page as far as an operator is concerned. Iterating a
            constant rather than repeating four near-identical sections,
            for the reason CLAUDE.md records about second render lists. */}
        {REPORT_CARDS.map((card) => (
          <section
            key={card.key}
            className="card"
            style={{ padding: "20px 22px", minHeight: 220 }}
            data-testid={`chart-card-${card.testId}`}
          >
            <h3 className="section-title">{t(card.titleKey)}</h3>
            <p className="muted small" style={{ marginBottom: 8 }}>
              {t(card.subtitleKey)}
            </p>
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setOpenReport(card.key)}
                data-testid={`open-${card.testId}`}
              >
                {t("open_report")}
              </button>
            </div>
          </section>
        ))}
      </div>

      {REPORT_CARDS.map((card) =>
        openReport === card.key ? (
          <div
            key={card.key}
            role="dialog"
            aria-modal="true"
            aria-label={t(card.titleKey)}
            data-testid={`${card.testId}-modal`}
            onClick={(event) => {
              if (event.target === event.currentTarget) setOpenReport(null);
            }}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.4)",
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "center",
              zIndex: 100,
              padding: 16,
              paddingTop: "6vh",
              overflowY: "auto",
            }}
          >
            <div
              className="card"
              style={{
                width: "min(96vw, 1320px)",
                padding: 24,
                maxHeight: "85vh",
                display: "flex",
                flexDirection: "column",
                overflowY: "auto",
              }}
            >
              <div className="section-head" style={{ marginBottom: 12 }}>
                <div className="section-head-title">{t(card.titleKey)}</div>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setOpenReport(null)}
                  data-testid={`${card.testId}-close`}
                >
                  {t("common:cancel")}
                </button>
              </div>
              <card.View />
            </div>
          </div>
        ) : null,
      )}
    </div>
  );
}
