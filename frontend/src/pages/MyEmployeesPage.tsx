import { Contact } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";
import { CustomerEmployeesDirectory } from "../components/CustomerEmployeesDirectory";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";

/**
 * Customer-facing employees directory.
 *
 * Route `/my/employees` (wrapped in `ProtectedRoute`, any authenticated
 * user). It resolves the caller's own customer via `me.customer_ids[0]`
 * and renders the shared `CustomerEmployeesDirectory`. A user with no
 * customer scope (e.g. a provider-side actor who lands here directly)
 * gets a friendly empty state instead of a broken request.
 *
 * Edit affordance is driven inside the directory: it appears for
 * CUSTOMER_USER viewers only when their own directory row carries
 * customer_access_role === "CUSTOMER_COMPANY_ADMIN". The backend
 * re-checks every PATCH regardless.
 */
export function MyEmployeesPage() {
  const { me } = useAuth();
  const { t } = useTranslation("common");

  const customerId = me?.customer_ids?.[0] ?? null;

  return (
    <div data-testid="my-employees-page">
      <PageHeader
        eyebrow={t("nav.operations_group")}
        title={t("my_employees.page_title")}
        subtitle={t("my_employees.subtitle")}
      />

      {customerId === null ? (
        <div className="card" style={{ padding: "20px 22px" }}>
          <EmptyState
            icon={Contact}
            title={t("my_employees.empty_no_customer_title")}
            description={t("my_employees.empty_no_customer_desc")}
            testId="my-employees-no-customer"
          />
        </div>
      ) : (
        <section className="card" style={{ padding: "20px 22px" }}>
          <CustomerEmployeesDirectory customerId={customerId} />
        </section>
      )}
    </div>
  );
}
