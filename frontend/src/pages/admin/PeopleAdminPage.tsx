/**
 * FE-6 (Addendum D §D.3.4) — ONE "Mensen" surface: users, employees
 * and invitations as three tabs of one page.
 *
 * Each tab renders the SAME page component the old nav entry opened,
 * in `embedded` mode (the surface owns the title), behind the SAME
 * gate that entry's route carried — `AdminRoute` for users and
 * invitations, the SA/CA/BM reader gate for employees — so merging
 * three pages into one changes where they are, never who sees them.
 * The old routes redirect here (App.tsx); the per-user pages
 * (`/admin/users/:id`, `/edit`) are untouched.
 */
import { Link, Navigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../auth/AuthContext";
import {
  canAccessAdminArea,
  canReadCustomerArea,
  isBuildingManager,
} from "../../auth/permissions";
import { PageHeader } from "../../components/PageHeader";
import { EmployeesAdminPage } from "./EmployeesAdminPage";
import { InvitationsAdminPage } from "./InvitationsAdminPage";
import { UsersAdminPage } from "./UsersAdminPage";

export type PeopleTab = "users" | "employees" | "invitations";

/** ONE ordered constant; the render iterates it (CLAUDE.md). */
const PEOPLE_TABS: readonly {
  key: PeopleTab;
  labelKey: string;
  allowed: typeof canAccessAdminArea;
}[] = [
  { key: "users", labelKey: "nav.users", allowed: canAccessAdminArea },
  {
    key: "employees",
    labelKey: "nav.employees",
    allowed: (role) => canAccessAdminArea(role) || isBuildingManager(role),
  },
  {
    key: "invitations",
    labelKey: "nav.invitations",
    allowed: canAccessAdminArea,
  },
];

export function PeopleAdminPage() {
  const { t } = useTranslation("common");
  const { tab } = useParams();
  const { me } = useAuth();
  const role = me?.role;

  const visible = PEOPLE_TABS.filter((spec) => spec.allowed(role));
  const current = visible.find((spec) => spec.key === tab) ?? null;

  // No tab, or one this role may not open: land on the first it may.
  if (!current) {
    const first = visible[0];
    return first ? (
      <Navigate to={`/admin/people/${first.key}`} replace />
    ) : (
      <Navigate to="/" replace />
    );
  }

  return (
    <div data-testid="people-admin-page">
      <PageHeader
        eyebrow={t("nav.group_klanten_mensen")}
        title={t("nav.people")}
        testId="people-page-header"
      />
      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("nav.people")}
        style={{ marginBottom: 16 }}
        data-testid="people-tabs"
      >
        {visible.map((spec) => (
          <Link
            key={spec.key}
            to={`/admin/people/${spec.key}`}
            role="tab"
            aria-selected={spec.key === current.key}
            className={`composer-toggle-btn${spec.key === current.key ? " active" : ""}`}
            data-testid={`people-tab-${spec.key}`}
          >
            {t(spec.labelKey)}
          </Link>
        ))}
      </div>

      {/* The exact gate each page's route always had, per tab: the
          predicate `AdminRoute` checks for users and invitations, the
          one `CustomerReadRoute` checks for employees, with the same
          bounce. (The guard components themselves wrap their children
          in the shell, so they cannot be nested inside a page.) */}
      {current.key === "users" &&
        (canAccessAdminArea(role) ? (
          <UsersAdminPage embedded />
        ) : (
          <Navigate to="/?admin_required=ok" replace />
        ))}
      {current.key === "employees" &&
        (canReadCustomerArea(role) ? (
          <EmployeesAdminPage embedded />
        ) : (
          <Navigate to="/?admin_required=ok" replace />
        ))}
      {current.key === "invitations" &&
        (canAccessAdminArea(role) ? (
          <InvitationsAdminPage embedded />
        ) : (
          <Navigate to="/?admin_required=ok" replace />
        ))}
    </div>
  );
}
