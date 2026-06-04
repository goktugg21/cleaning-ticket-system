import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import type { CustomerAdmin } from "../../../api/types";
import { CustomerEmployeesDirectory } from "../../../components/CustomerEmployeesDirectory";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Customer-scoped employees directory (provider-admin entry point).
 *
 * Route `/admin/customers/:id/employees` (wrapped in `AdminRoute`, so
 * SUPER_ADMIN / COMPANY_ADMIN only). Mirrors the other customer-scoped
 * sub-pages: a `CustomerSubPageHeader` over the shared
 * `CustomerEmployeesDirectory` body.
 */
export function CustomerEmployeesPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setLoadError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    getCustomer(numericId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  return (
    <div data-testid="customer-employees-page">
      <CustomerSubPageHeader
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
      />

      {loadError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {loadError}
        </div>
      )}

      {numericId !== null && (
        <>
          <p
            className="section-explainer"
            data-testid="customer-employees-explainer"
          >
            {t("customer_employees.explainer")}
          </p>
          <section className="card" style={{ padding: "20px 22px" }}>
            <h3 className="section-title">
              {t("customer_employees.section_title")}
            </h3>
            <CustomerEmployeesDirectory customerId={numericId} />
          </section>
        </>
      )}
    </div>
  );
}
