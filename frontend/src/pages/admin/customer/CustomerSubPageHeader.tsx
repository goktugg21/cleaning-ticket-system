/**
 * FE-6 (Addendum D §D.3.4) — the customer's IN-PAGE header with tabs.
 *
 * The "Beperkt tot" sidebar swap is gone: the global nav stays where it
 * is, and a customer is a page with a header (name, status, the quick
 * facts a page chooses to show) and one row of tabs — Overzicht /
 * Gebouwen / Mensen / Permissies / Prijzen / Contracten / Werk /
 * Facturen / Documenten / Instellingen. You are never lost, because you
 * never left.
 *
 * Every tab keeps the gate its page always had: the row shows a tab
 * only when this role may open the page behind it (`AdminRoute` pages
 * for SA/CA, `CustomerReadRoute` pages for SA/CA/BM, contracts for the
 * contract readers). A tab that groups two pages (Mensen = users +
 * contacts, Werk = tickets + meerwerk, Facturen = invoices + report,
 * Instellingen = settings + labels) shows a second, smaller toggle for
 * them, again per gate — a BUILDING_MANAGER sees exactly the three
 * pages the old scoped submenu offered them.
 */
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../auth/AuthContext";
import {
  canAccessAdminArea,
  canAccessContracts,
  canReadCustomerArea,
} from "../../../auth/permissions";
import { PageHeader } from "../../../components/PageHeader";

export type CustomerTab =
  | "overview"
  | "buildings"
  | "people"
  | "permissions"
  | "pricing"
  | "contracts"
  | "work"
  | "invoices"
  | "documents"
  | "settings";

export type CustomerSubTab =
  | "users"
  | "contacts"
  | "tickets"
  | "extra_work"
  | "invoices"
  | "reports"
  | "settings"
  | "labels";

type Gate = typeof canAccessAdminArea;

interface SubTabSpec {
  key: CustomerSubTab;
  labelKey: string;
  path: string;
  allowed: Gate;
}

interface TabSpec {
  key: CustomerTab;
  labelKey: string;
  /** The route segment under `/admin/customers/:id/`; "" = the root. */
  path: string;
  allowed: Gate;
  subs?: SubTabSpec[];
}

/** ONE ordered constant, iterated by the render (CLAUDE.md: never a
 *  second hand-kept render list). */
const CUSTOMER_TABS: readonly TabSpec[] = [
  {
    key: "overview",
    labelKey: "nav.customer_submenu.overview",
    path: "",
    allowed: canReadCustomerArea,
  },
  {
    key: "buildings",
    labelKey: "nav.customer_submenu.buildings",
    path: "buildings",
    allowed: canAccessAdminArea,
  },
  {
    key: "people",
    labelKey: "nav.customer_submenu.people",
    path: "users",
    allowed: canReadCustomerArea,
    subs: [
      {
        key: "users",
        labelKey: "nav.customer_submenu.users",
        path: "users",
        allowed: canAccessAdminArea,
      },
      {
        key: "contacts",
        labelKey: "nav.customer_submenu.contacts",
        path: "contacts",
        allowed: canReadCustomerArea,
      },
    ],
  },
  {
    key: "permissions",
    labelKey: "nav.customer_submenu.permissions",
    path: "permissions",
    allowed: canAccessAdminArea,
  },
  {
    key: "pricing",
    labelKey: "nav.customer_submenu.pricing",
    path: "pricing",
    allowed: canAccessAdminArea,
  },
  {
    key: "contracts",
    labelKey: "nav.customer_submenu.contracts",
    path: "contracts",
    allowed: (role) => canAccessAdminArea(role) && canAccessContracts(role),
  },
  {
    key: "work",
    labelKey: "nav.customer_submenu.work",
    path: "tickets",
    allowed: canAccessAdminArea,
    subs: [
      {
        key: "tickets",
        labelKey: "nav.customer_submenu.tickets",
        path: "tickets",
        allowed: canAccessAdminArea,
      },
      {
        key: "extra_work",
        labelKey: "nav.customer_submenu.extra_work",
        path: "extra-work",
        allowed: canAccessAdminArea,
      },
    ],
  },
  {
    key: "invoices",
    labelKey: "nav.customer_submenu.invoices",
    path: "invoices",
    allowed: canAccessAdminArea,
    subs: [
      {
        key: "invoices",
        labelKey: "nav.customer_submenu.invoices",
        path: "invoices",
        allowed: canAccessAdminArea,
      },
      {
        key: "reports",
        labelKey: "nav.customer_submenu.reports",
        path: "reports",
        allowed: canAccessAdminArea,
      },
    ],
  },
  {
    key: "documents",
    labelKey: "nav.customer_submenu.documents",
    path: "documents",
    allowed: canAccessAdminArea,
  },
  {
    key: "settings",
    labelKey: "nav.customer_submenu.settings",
    path: "settings",
    allowed: canReadCustomerArea,
    subs: [
      {
        key: "settings",
        labelKey: "nav.customer_submenu.settings",
        path: "settings",
        allowed: canAccessAdminArea,
      },
      {
        key: "labels",
        labelKey: "nav.customer_submenu.labels",
        path: "labels",
        allowed: canReadCustomerArea,
      },
    ],
  },
];

export interface CustomerSubPageHeaderProps {
  customerName: string;
  isActive: boolean;
  /** Which tab this page IS. */
  tab: CustomerTab;
  /** Which sub-view, for the grouped tabs. */
  subTab?: CustomerSubTab;
  /** Quick facts under the name — a page passes what it knows. */
  facts?: ReactNode;
  /** Optional right-aligned action slot (e.g. "Edit basics"). */
  actions?: ReactNode;
}

export function CustomerSubPageHeader({
  customerName,
  isActive,
  tab,
  subTab,
  facts,
  actions,
}: CustomerSubPageHeaderProps) {
  const { t } = useTranslation("common");
  const { id } = useParams();
  const { me } = useAuth();
  const role = me?.role;
  const base = `/admin/customers/${id ?? ""}`;

  const visibleTabs = CUSTOMER_TABS.filter((spec) => spec.allowed(role));
  const current = CUSTOMER_TABS.find((spec) => spec.key === tab);
  const visibleSubs = (current?.subs ?? []).filter((sub) =>
    sub.allowed(role),
  );

  /** A grouped tab links to the first sub-page this role may open. */
  const targetFor = (spec: TabSpec): string => {
    const first = (spec.subs ?? []).find((sub) => sub.allowed(role));
    const path = first ? first.path : spec.path;
    return path ? `${base}/${path}` : base;
  };

  return (
    <>
      <PageHeader
        backLink={{ to: "/admin/customers", label: t("customer_view.back") }}
        eyebrow={t("nav.customers")}
        title={customerName || t("customer_form.fallback")}
        statusPill={
          !isActive ? (
            <span className="cell-tag cell-tag-closed">
              <i />
              {t("admin.status_inactive")}
            </span>
          ) : undefined
        }
        subtitle={facts}
        actions={actions}
        testId="customer-page-header"
      />

      <nav
        className="customer-tabs"
        role="tablist"
        aria-label={t("nav.customers")}
        data-testid="customer-tabs"
      >
        {visibleTabs.map((spec) => {
          const active = spec.key === tab;
          return (
            <Link
              key={spec.key}
              to={targetFor(spec)}
              role="tab"
              aria-selected={active}
              className={`customer-tab${active ? " active" : ""}`}
              data-testid={`customer-tab-${spec.key}`}
            >
              {t(spec.labelKey)}
            </Link>
          );
        })}
      </nav>

      {visibleSubs.length > 1 && (
        <div
          className="composer-toggle customer-subtabs"
          role="tablist"
          aria-label={t(current?.labelKey ?? "nav.customers")}
          data-testid="customer-subtabs"
        >
          {visibleSubs.map((sub) => {
            const active = sub.key === subTab;
            return (
              <Link
                key={sub.key}
                to={`${base}/${sub.path}`}
                role="tab"
                aria-selected={active}
                className={`composer-toggle-btn${active ? " active" : ""}`}
                data-testid={`customer-subtab-${sub.key}`}
              >
                {t(sub.labelKey)}
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
