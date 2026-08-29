/**
 * FE-6 (Addendum D §D.3.4) — ONE "Diensten & catalogi" surface: the
 * services screen and the catalogs screen as two tabs of one page.
 *
 * Same rule as the Mensen surface: each tab renders the SAME page it
 * always was, in `embedded` mode, behind the SAME `AdminRoute` gate.
 * The old routes redirect here (App.tsx).
 */
import { Link, Navigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../auth/AuthContext";
import { canAccessAdminArea } from "../../auth/permissions";
import { PageHeader } from "../../components/PageHeader";
import { CatalogsAdminPage } from "./CatalogsAdminPage";
import { ServicesAdminPage } from "./ServicesAdminPage";

export type ServicesCatalogsTab = "services" | "catalogs";

const SERVICES_CATALOGS_TABS: readonly {
  key: ServicesCatalogsTab;
  labelKey: string;
}[] = [
  { key: "services", labelKey: "nav.services" },
  { key: "catalogs", labelKey: "nav.catalogs" },
];

export function ServicesCatalogsPage() {
  const { t } = useTranslation("common");
  const { tab } = useParams();
  const { me } = useAuth();
  const current =
    SERVICES_CATALOGS_TABS.find((spec) => spec.key === tab) ?? null;

  if (!current) {
    return <Navigate to="/admin/services-catalogs/services" replace />;
  }

  return (
    <div data-testid="services-catalogs-page">
      <PageHeader
        eyebrow={t("nav.group_systeem")}
        title={t("nav.services_catalogs")}
        testId="services-catalogs-page-header"
      />
      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("nav.services_catalogs")}
        style={{ marginBottom: 16 }}
        data-testid="services-catalogs-tabs"
      >
        {SERVICES_CATALOGS_TABS.map((spec) => (
          <Link
            key={spec.key}
            to={`/admin/services-catalogs/${spec.key}`}
            role="tab"
            aria-selected={spec.key === current.key}
            className={`composer-toggle-btn${spec.key === current.key ? " active" : ""}`}
            data-testid={`services-catalogs-tab-${spec.key}`}
          >
            {t(spec.labelKey)}
          </Link>
        ))}
      </div>

      {/* The same predicate `AdminRoute` checks on both old routes. */}
      {!canAccessAdminArea(me?.role) ? (
        <Navigate to="/?admin_required=ok" replace />
      ) : current.key === "services" ? (
        <ServicesAdminPage embedded />
      ) : (
        <CatalogsAdminPage embedded />
      )}
    </div>
  );
}
