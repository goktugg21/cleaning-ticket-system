import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { PageHeader } from "../../components/PageHeader";
import { BuildingTypesTab } from "./BuildingTypesTab";
import { HourTypesTab } from "./HourTypesTab";
import { ManagedUnitsTab } from "./ManagedUnitsTab";
import { WorkTypesTab } from "./WorkTypesTab";
import { ContractTypesTab } from "./contracts/ContractTypesTab";

/**
 * Sprint 178 §1 — ONE place for every per-company catalog.
 *
 * Before this, a company's catalogs were spread across three unrelated
 * pages: hour types and work types under Hours, managed units under
 * Services, contract types under Contracts. Each was reachable, none was
 * findable — an operator setting a company up had to already know where
 * three separate screens were.
 *
 * ## What this page is NOT
 *
 * It is not a rewrite. Every tab below renders the SAME component the old
 * page renders, so there is exactly one implementation of each catalog
 * and the two entry points cannot drift. **The old entry points all still
 * work** — nothing was moved or removed, and any path anyone already uses
 * still lands where it did.
 *
 * ## Services
 *
 * Services and service categories are deliberately a LINK rather than a
 * tab. They are not a name-and-active-flag catalog: the services screen
 * carries prices, VAT, per-customer overrides and a bulk price-adjust
 * run. Embedding it would either duplicate that page or reduce it to the
 * parts that fit `CatalogTab`, and neither is honest. A pointer to the
 * real screen is.
 */

type Tab =
  | "hour_types"
  | "work_types"
  | "contract_types"
  | "building_types"
  | "managed_units";

const TABS: { key: Tab; labelKey: string }[] = [
  { key: "hour_types", labelKey: "catalogs.tab_hour_types" },
  { key: "work_types", labelKey: "catalogs.tab_work_types" },
  { key: "contract_types", labelKey: "catalogs.tab_contract_types" },
  { key: "building_types", labelKey: "catalogs.tab_building_types" },
  { key: "managed_units", labelKey: "catalogs.tab_managed_units" },
];

export function CatalogsAdminPage() {
  const { t } = useTranslation("common");
  const [tab, setTab] = useState<Tab>("hour_types");

  return (
    <div>
      <PageHeader
        title={t("catalogs.title")}
        subtitle={t("catalogs.subtitle")}
        testId="catalogs-page-header"
      />

      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("catalogs.tabs_aria")}
        style={{ marginBottom: 16 }}
      >
        {/* Iterating the exported TABS constant rather than repeating
            five buttons: CLAUDE.md records what a second, independently
            maintained render list costs (Sprint 126's headerless
            permission column, invisible for three sprints). */}
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={`composer-toggle-btn ${tab === entry.key ? "active" : ""}`}
            onClick={() => setTab(entry.key)}
            data-testid={`catalogs-tab-${entry.key}`}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </div>

      {tab === "hour_types" && <HourTypesTab />}
      {tab === "work_types" && <WorkTypesTab />}
      {tab === "contract_types" && <ContractTypesTab />}
      {tab === "building_types" && <BuildingTypesTab />}
      {tab === "managed_units" && <ManagedUnitsTab />}

      {/* Sprint 179B §4 — `card-detail-pad`, the padding every detail
          card carries (Sprint 163 §3 named it for exactly this). `.card`
          deliberately has none, because plenty of cards hold a
          full-bleed table; this one holds a heading, a sentence and a
          button, and all three rendered flush against the border. */}
      <div className="card card-detail-pad" style={{ marginTop: 16 }}>
        <div className="form-section-title">
          {t("catalogs.services_title")}
        </div>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("catalogs.services_hint")}
        </p>
        <Link
          to="/admin/services"
          className="btn btn-secondary btn-sm"
          data-testid="catalogs-services-link"
        >
          {t("catalogs.services_link")}
        </Link>
      </div>
    </div>
  );
}
