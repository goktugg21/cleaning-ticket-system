import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listBuildings, listCompanies } from "../../api/admin";
import type { ReportFilters } from "../../api/reports";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useReportsFilters } from "../../hooks/useReportsFilters";
import { AgeBucketsChart } from "./charts/AgeBucketsChart";
import { ManagerThroughputChart } from "./charts/ManagerThroughputChart";
import { SLABreachRateChart } from "./charts/SLABreachRateChart";
import { SLADistributionChart } from "./charts/SLADistributionChart";
import { StatusDistributionChart } from "./charts/StatusDistributionChart";
import { TicketsByBuildingChart } from "./charts/TicketsByBuildingChart";
import { TicketsByCustomerChart } from "./charts/TicketsByCustomerChart";
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

export function ReportsPage() {
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
    listCompanies({ page_size: 200 }).then((response) => {
      if (cancelled) return;
      setCompanies(response.results);
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
    const params: Parameters<typeof listBuildings>[0] = { page_size: 200 };
    if (isSuperAdmin && filters.company !== undefined) {
      params.company = filters.company;
    }
    listBuildings(params)
      .then((response) => {
        if (cancelled) return;
        setBuildings(response.results);
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
        <TicketsByCustomerChart filters={apiFilters} refreshKey={refreshKey} />
        <TicketsByBuildingChart filters={apiFilters} refreshKey={refreshKey} />
      </div>
    </div>
  );
}
